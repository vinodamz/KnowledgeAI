"""Versioned ontology and immutable published definitions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='002_ontology'
down_revision='001_profiles'
branch_labels=depends_on=None
TABLES=['knowledge_model_revisions','entity_types','relation_types','canonical_concepts','model_links']
def upgrade():
    op.create_table('knowledge_model_revisions',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('profile_id',sa.Uuid(),sa.ForeignKey('profiles.id'),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('status',sa.String(20),nullable=False),
        sa.Column('semantic_description',sa.Text(),nullable=False),
        sa.UniqueConstraint('profile_id','revision'),sa.CheckConstraint("status in ('draft','published')"))
    op.create_table('entity_types',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('model_revision_id',sa.Uuid(),sa.ForeignKey('knowledge_model_revisions.id'),nullable=False),
        sa.Column('name',sa.String(200),nullable=False),sa.Column('attributes',JSONB(),nullable=False),
        sa.Column('scores',JSONB(),nullable=False),sa.Column('qualification',sa.Text()),
        sa.Column('qualified_by',sa.Uuid(),sa.ForeignKey('users.id')),sa.UniqueConstraint('model_revision_id','name'))
    op.create_table('relation_types',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('model_revision_id',sa.Uuid(),sa.ForeignKey('knowledge_model_revisions.id'),nullable=False),
        sa.Column('source_type_id',sa.Uuid(),sa.ForeignKey('entity_types.id'),nullable=False),
        sa.Column('target_type_id',sa.Uuid(),sa.ForeignKey('entity_types.id'),nullable=False),
        sa.Column('name',sa.String(200),nullable=False))
    op.create_table('canonical_concepts',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('profile_id',sa.Uuid(),sa.ForeignKey('profiles.id'),nullable=False),
        sa.Column('model_revision_id',sa.Uuid(),sa.ForeignKey('knowledge_model_revisions.id'),nullable=False),
        sa.Column('name',sa.String(200),nullable=False),sa.Column('aliases',JSONB(),nullable=False),
        sa.Column('provenance',JSONB(),nullable=False))
    op.create_table('model_links',
        sa.Column('model_revision_id',sa.Uuid(),sa.ForeignKey('knowledge_model_revisions.id'),primary_key=True),
        sa.Column('target_model_revision_id',sa.Uuid(),sa.ForeignKey('knowledge_model_revisions.id'),primary_key=True))
    op.add_column('knowledge_versions',sa.Column('model_revision_id',sa.Uuid(),sa.ForeignKey('knowledge_model_revisions.id')))
    op.execute("""CREATE FUNCTION protect_model() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.status='published' THEN RAISE EXCEPTION 'Published model is immutable'; END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$""")
    op.execute('CREATE TRIGGER immutable_model BEFORE UPDATE OR DELETE ON knowledge_model_revisions FOR EACH ROW EXECUTE FUNCTION protect_model()')
    op.execute("""CREATE FUNCTION protect_definition() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE key uuid; state text;
    BEGIN
      IF TG_OP='DELETE' THEN key=OLD.model_revision_id; ELSE key=NEW.model_revision_id; END IF;
      IF TG_OP='UPDATE' AND OLD.model_revision_id<>NEW.model_revision_id THEN RAISE EXCEPTION 'Cannot move definitions'; END IF;
      SELECT status INTO state FROM knowledge_model_revisions WHERE id=key FOR UPDATE;
      IF state<>'draft' THEN RAISE EXCEPTION 'Published definitions are immutable'; END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      IF TG_TABLE_NAME='canonical_concepts' THEN
      IF NOT EXISTS(SELECT 1 FROM knowledge_model_revisions WHERE id=key AND profile_id=NEW.profile_id) THEN RAISE EXCEPTION 'Concept scope mismatch'; END IF;
      END IF;
      IF TG_TABLE_NAME='relation_types' THEN
      IF (NOT EXISTS(SELECT 1 FROM entity_types WHERE id=NEW.source_type_id AND model_revision_id=key) OR NOT EXISTS(SELECT 1 FROM entity_types WHERE id=NEW.target_type_id AND model_revision_id=key)) THEN RAISE EXCEPTION 'Relation endpoints must belong to model'; END IF;
      END IF;
      RETURN NEW;
    END $$""")
    for name in TABLES[1:]: op.execute(f'CREATE TRIGGER immutable_definition BEFORE INSERT OR UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION protect_definition()')
    op.execute("""CREATE FUNCTION validate_model_binding() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.model_revision_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM knowledge_model_revisions WHERE id=NEW.model_revision_id AND profile_id=NEW.profile_id AND status='published') THEN RAISE EXCEPTION 'Version requires exact published model in same profile'; END IF;
      RETURN NEW;
    END $$""")
    op.execute('CREATE TRIGGER valid_model_binding BEFORE INSERT OR UPDATE ON knowledge_versions FOR EACH ROW EXECUTE FUNCTION validate_model_binding()')
def downgrade():
    op.execute('DROP TRIGGER valid_model_binding ON knowledge_versions')
    op.execute('DROP FUNCTION validate_model_binding()')
    op.drop_column('knowledge_versions','model_revision_id')
    for name in reversed(TABLES): op.drop_table(name)
    op.execute('DROP FUNCTION protect_definition()')
    op.execute('DROP FUNCTION protect_model()')
