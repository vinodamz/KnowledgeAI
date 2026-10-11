import hashlib
import hmac
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
        from knowledge_ai.profiles.models import Profile, ProfileGrant
        owned = frozenset(db.scalars(select(Profile.id).where(Profile.owner_id == user.id)))
        grants = list(db.scalars(select(ProfileGrant).where(ProfileGrant.user_id == user.id)))
        return Actor(id=user.id, role=user.role, owned_profile_ids=owned,
                     read_profile_ids=frozenset(g.profile_id for g in grants if g.read),
                     contribute_profile_ids=frozenset(g.profile_id for g in grants if g.contribute))

def issue_session(db, user, settings):
    token = secrets.token_urlsafe(32)
    csrf = session_csrf(token, settings)
    db.add(AuthSession(token_hash=digest(token), user_id=user.id, csrf_hash=digest(csrf),
                       expires_at=datetime.now(timezone.utc)+timedelta(seconds=settings.session_seconds)))
    cookie = URLSafeSerializer(settings.signing_secret, salt='session').dumps(token)
    return cookie, csrf


def session_csrf(token, settings):
    """Stable per authenticated session; recoverable across tabs without rotating peers."""
    return hmac.new(settings.signing_secret.encode(), ("csrf:" + token).encode(), hashlib.sha256).hexdigest()
