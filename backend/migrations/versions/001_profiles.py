"""Profile governance and exact version pins."""
from alembic import op
import sqlalchemy as sa
revision = '001_profiles'
down_revision = '000_identity'
branch_labels = depends_on = None

def upgrade():
    op.create_table('profiles', sa.Column('id',sa.Uuid(),primary_key=True), sa.Column('kind',sa.String(20),nullable=False),sa.Column('name',sa.String(200),nullable=False),sa.Column('owner_id',sa.Uuid(),sa.ForeignKey('users.id'),nullable=False),sa.Column('archived',sa.Boolean(),nullable=False),sa.CheckConstraint("kind in ('product','project')"))
    op.create_table('knowledge_versions',sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('profile_id',sa.Uuid(),sa.ForeignKey('profiles.id'),nullable=False),sa.Column('label',sa.String(200),nullable=False),sa.Column('predecessor_id',sa.Uuid(),sa.ForeignKey('knowledge_versions.id')),sa.Column('status',sa.String(20),nullable=False),sa.UniqueConstraint('profile_id','label'),sa.CheckConstraint("status in ('draft','released','archived')"))
    op.create_table('project_dependencies',sa.Column('project_version_id',sa.Uuid(),sa.ForeignKey('knowledge_versions.id'),primary_key=True),sa.Column('product_version_id',sa.Uuid(),sa.ForeignKey('knowledge_versions.id'),primary_key=True))
    op.create_table('profile_grants',sa.Column('profile_id',sa.Uuid(),sa.ForeignKey('profiles.id'),primary_key=True),sa.Column('user_id',sa.Uuid(),sa.ForeignKey('users.id'),primary_key=True),sa.Column('read',sa.Boolean(),nullable=False),sa.Column('contribute',sa.Boolean(),nullable=False))
    # Immutable payload guard also covers direct ORM updates by future modules.
    op.execute("""CREATE FUNCTION protect_version_payload() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Versions must be archived, not deleted'; END IF;
      IF OLD.status IN ('released','archived') AND
         ((to_jsonb(NEW)-'status') IS DISTINCT FROM (to_jsonb(OLD)-'status') OR (NEW.status <> OLD.status AND NOT (OLD.status='released' AND NEW.status='archived'))) THEN
        RAISE EXCEPTION 'Released and archived version payloads are immutable';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute('CREATE TRIGGER immutable_version BEFORE UPDATE OR DELETE ON knowledge_versions FOR EACH ROW EXECUTE FUNCTION protect_version_payload()')
    op.execute("""CREATE FUNCTION protect_dependency() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE target uuid; state text;
    BEGIN
      IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'Replace dependencies on draft versions only'; END IF;
      IF TG_OP='DELETE' THEN target=OLD.project_version_id; ELSE target=NEW.project_version_id; END IF;
      SELECT status INTO state FROM knowledge_versions WHERE id=target FOR UPDATE;
      IF state <> 'draft' THEN RAISE EXCEPTION 'Released and archived pins are immutable'; END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      IF NOT EXISTS (SELECT 1 FROM knowledge_versions v JOIN profiles p ON p.id=v.profile_id WHERE v.id=NEW.product_version_id AND v.status='released' AND p.kind='product') OR NOT EXISTS (SELECT 1 FROM knowledge_versions v JOIN profiles p ON p.id=v.profile_id WHERE v.id=target AND p.kind='project') THEN RAISE EXCEPTION 'Invalid project product dependency'; END IF;
      RETURN NEW;
    END $$""")
    op.execute('CREATE TRIGGER immutable_dependency BEFORE INSERT OR UPDATE OR DELETE ON project_dependencies FOR EACH ROW EXECUTE FUNCTION protect_dependency()')

def downgrade():
    op.drop_table('profile_grants')
    op.drop_table('project_dependencies')
    op.execute('DROP FUNCTION protect_dependency()')
    op.drop_table('knowledge_versions')
    op.execute('DROP FUNCTION protect_version_payload()')
    op.drop_table('profiles')
