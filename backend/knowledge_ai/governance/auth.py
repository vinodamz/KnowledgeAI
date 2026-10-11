import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Request
from itsdangerous import URLSafeSerializer, BadSignature
from pwdlib import PasswordHash
from sqlalchemy import select
from knowledge_ai.db import User, AuthSession
from knowledge_ai.governance.policy import Actor

passwords = PasswordHash.recommended()
dummy_hash = passwords.hash(secrets.token_urlsafe(32))
def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def current_actor(request: Request):
    cookie = request.cookies.get('knowledge_ai_session')
    if not cookie:
        raise HTTPException(401, 'Authentication required')
    try:
        token = URLSafeSerializer(request.app.state.settings.signing_secret, salt='session').loads(cookie)
    except BadSignature:
        raise HTTPException(401, 'Invalid session')
    with request.app.state.db.sessions() as db:
        session = db.get(AuthSession, digest(token))
        user = db.get(User, session.user_id) if session else None
        if not session or session.expires_at <= datetime.now(timezone.utc) or not user or not user.active:
            raise HTTPException(401, 'Invalid or expired session')
        if request.method not in {'GET','HEAD','OPTIONS'}:
            supplied = request.headers.get('X-CSRF-Token', '')
            if not secrets.compare_digest(digest(supplied), session.csrf_hash):
                raise HTTPException(403, 'CSRF token required')
        return Actor(id=user.id, role=user.role)

def issue_session(db, user, settings):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=digest(token), user_id=user.id, csrf_hash=digest(csrf),
                       expires_at=datetime.now(timezone.utc)+timedelta(seconds=settings.session_seconds)))
    cookie = URLSafeSerializer(settings.signing_secret, salt='session').dumps(token)
    return cookie, csrf
