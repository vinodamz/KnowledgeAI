from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from itsdangerous import URLSafeSerializer
from knowledge_ai.settings import Settings
from knowledge_ai.db import Database, User, AuthSession
from knowledge_ai.governance.auth import current_actor, passwords, dummy_hash, issue_session, digest
from knowledge_ai.governance.audit import record_event

def create_app(settings=None):
    settings = settings or Settings()
    database = Database(settings.database_url)
    @asynccontextmanager
    async def lifespan(app):
        yield
        database.engine.dispose()
    app = FastAPI(title='Knowledge AI', lifespan=lifespan)
    app.state.settings, app.state.db = settings, database

    @app.get('/health')
    def health():
        return {'status':'ok'}

    @app.get('/ready')
    def ready():
        try:
            with database.sessions() as db:
                db.execute(text('SELECT 1 FROM users LIMIT 1'))
        except SQLAlchemyError:
            raise HTTPException(503, 'Registry unavailable or migrations pending')
        return {'status':'ready'}

    @app.post('/api/auth/login')
    def login(body: Credentials, request: Request, response: Response):
        # A JSON-only login plus same-origin check prevents login CSRF.
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'Cross-origin login refused')
        with database.sessions() as db:
            user = db.scalar(select(User).where(User.username == body.username))
            valid = passwords.verify(body.password, user.password_hash if user else dummy_hash)
            if not valid or not user or not user.active:
                record_event(db, None, 'login_failed')
                db.commit()
                raise HTTPException(401, 'Invalid credentials')
            cookie, csrf = issue_session(db, user, settings)
            record_event(db, user.id, 'login')
            db.commit()
            response.set_cookie('knowledge_ai_session', cookie, httponly=True, secure=settings.secure_cookies,
                                samesite='strict', max_age=settings.session_seconds)
            return {'actor':{'id':str(user.id),'role':user.role},'csrf_token':csrf}

    @app.get('/api/auth/me')
    def me(actor=Depends(current_actor)):
        return {'id': str(actor.id), 'role': actor.role}

    @app.post('/api/auth/logout', status_code=204)
    def logout(request: Request, response: Response, actor=Depends(current_actor)):
        token = URLSafeSerializer(settings.signing_secret, salt='session').loads(request.cookies['knowledge_ai_session'])
        with database.sessions() as db:
            db.delete(db.get(AuthSession, digest(token)))
            record_event(db, actor.id, 'logout')
            db.commit()
        response.delete_cookie('knowledge_ai_session')

    @app.post('/api/profiles')
    def profiles_placeholder(actor=Depends(current_actor)):
        raise HTTPException(501, 'Profiles are implemented in Task 2')
    return app

class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)
