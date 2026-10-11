"""Identity registry and audit history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '000_identity'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('users', sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('username', sa.String(200), nullable=False, unique=True), sa.Column('password_hash', sa.String(), nullable=False), sa.Column('role', sa.String(20), nullable=False), sa.Column('active', sa.Boolean(), nullable=False), sa.CheckConstraint("role in ('admin','owner','contributor','reader')"))
    op.create_table('auth_sessions', sa.Column('token_hash', sa.String(64), primary_key=True), sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False), sa.Column('csrf_hash', sa.String(64), nullable=False), sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('audit_events', sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('actor_id', sa.Uuid(), sa.ForeignKey('users.id')), sa.Column('action', sa.String(100), nullable=False), sa.Column('profile_id', sa.Uuid()), sa.Column('details', postgresql.JSONB(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))

def downgrade():
    op.drop_table('audit_events')
    op.drop_table('auth_sessions')
    op.drop_table('users')
