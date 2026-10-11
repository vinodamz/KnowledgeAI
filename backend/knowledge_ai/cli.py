import argparse
import getpass
from sqlalchemy import select
from knowledge_ai.settings import Settings
from knowledge_ai.db import Database, User
from knowledge_ai.governance.auth import passwords
from knowledge_ai.governance.audit import record_event

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('username')
    args = parser.parse_args()
    if not 1 <= len(args.username) <= 200:
        parser.error('Username must have between 1 and 200 characters')
    password = getpass.getpass('Administrator password: ')
    if not 12 <= len(password) <= 1024:
        parser.error('Password must have between 12 and 1024 characters')
    if password != getpass.getpass('Confirm password: '):
        parser.error('Passwords do not match')
    db = Database(Settings().database_url)
    with db.sessions() as session:
        if session.scalar(select(User).where(User.username == args.username)):
            parser.error('Username already exists; no changes made')
        user = User(username=args.username, password_hash=passwords.hash(password), role='admin')
        session.add(user)
        session.flush()
        record_event(session, user.id, 'bootstrap_admin')
        session.commit()
    db.engine.dispose()

if __name__ == '__main__':
    main()
