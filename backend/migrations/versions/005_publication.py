"""Immutable publication generations, durable jobs and central CAS pointer."""
from alembic import op
revision='005_publication'
down_revision='004_review'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('''
    CREATE TABLE publication_generations(id uuid PRIMARY KEY, scope_manifest jsonb NOT NULL,
      status text NOT NULL CHECK(status IN ('staging','verified','active','retired','failed')),
      verification jsonb, created_at timestamptz NOT NULL);
    CREATE TABLE active_publication(singleton integer PRIMARY KEY CHECK(singleton=1),
      generation_id uuid REFERENCES publication_generations(id));
    INSERT INTO active_publication VALUES(1,NULL);
    CREATE TABLE publication_jobs(id uuid PRIMARY KEY, actor_id uuid NOT NULL REFERENCES users(id),
      profile_id uuid NOT NULL REFERENCES profiles(id),version_id uuid NOT NULL REFERENCES knowledge_versions(id),
      idempotency_key text NOT NULL,selection jsonb NOT NULL,status text NOT NULL
      CHECK(status IN ('queued','building','published','publication_failed')),attempts integer NOT NULL DEFAULT 0,
      generation_id uuid REFERENCES publication_generations(id),expected_active_id uuid REFERENCES publication_generations(id),
      error text, created_at timestamptz NOT NULL,UNIQUE(actor_id,idempotency_key));
    CREATE FUNCTION protect_publication_manifest() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.scope_manifest IS DISTINCT FROM OLD.scope_manifest OR
         (OLD.status IN ('verified','active','retired') AND NEW.verification IS DISTINCT FROM OLD.verification)
      THEN RAISE EXCEPTION 'Publication snapshot is immutable'; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_publication_manifest BEFORE UPDATE ON publication_generations
      FOR EACH ROW EXECUTE FUNCTION protect_publication_manifest();
    ''')

def downgrade():
    op.execute('DROP TABLE publication_jobs,active_publication,publication_generations; DROP FUNCTION protect_publication_manifest()')
