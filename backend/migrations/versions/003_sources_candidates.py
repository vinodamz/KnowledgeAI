"""Immutable manual source revisions and isolated extraction drafts."""
from alembic import op
revision='003_sources_candidates'
down_revision='002_ontology'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('''CREATE TABLE source_revisions (
      revision_id uuid PRIMARY KEY, source_id uuid NOT NULL,
      profile_id uuid NOT NULL REFERENCES profiles(id),
      knowledge_version_id uuid NOT NULL REFERENCES knowledge_versions(id),
      model_revision_id uuid NOT NULL REFERENCES knowledge_model_revisions(id),
      content_hash text NOT NULL, object_key text NOT NULL,
      provenance jsonb NOT NULL, access_policy jsonb NOT NULL,
      uploaded_by uuid NOT NULL REFERENCES users(id), chunks jsonb NOT NULL,
      UNIQUE(profile_id,knowledge_version_id,model_revision_id,content_hash));
    CREATE TABLE extraction_jobs (
      id uuid PRIMARY KEY,source_revision_id uuid NOT NULL UNIQUE REFERENCES source_revisions(revision_id),
      status text NOT NULL CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
      attempts integer NOT NULL CHECK(attempts>=0),available_at timestamptz NOT NULL,
      lease_until timestamptz,lease_token uuid,error text);
    CREATE INDEX extraction_jobs_poll ON extraction_jobs(status,available_at);
    CREATE TABLE draft_candidates (
      id uuid NOT NULL,revision integer NOT NULL CHECK(revision>0),
      source_revision_id uuid NOT NULL REFERENCES source_revisions(revision_id),
      kind text NOT NULL CHECK(kind IN ('entity','relation','model_suggestion')),
      payload jsonb NOT NULL,evidence jsonb NOT NULL,
      state text NOT NULL CHECK(state IN ('pending','approved','rejected')),
      PRIMARY KEY(id,revision), UNIQUE(id,revision));
    CREATE INDEX draft_candidates_source ON draft_candidates(source_revision_id);
    CREATE TABLE raw_extractions (
      id uuid PRIMARY KEY,job_id uuid NOT NULL UNIQUE REFERENCES extraction_jobs(id),
      source_revision_id uuid NOT NULL REFERENCES source_revisions(revision_id),output jsonb NOT NULL);
    CREATE FUNCTION protect_source_revision() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Source revisions are immutable'; END $$;
    CREATE TRIGGER immutable_source_revision BEFORE UPDATE ON source_revisions FOR EACH ROW EXECUTE FUNCTION protect_source_revision();
    CREATE FUNCTION protect_candidate_revision() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE source_row source_revisions; version_row knowledge_versions;
    BEGIN
      IF TG_OP='UPDATE' AND (NEW.id<>OLD.id OR NEW.revision<>OLD.revision OR NEW.source_revision_id<>OLD.source_revision_id OR NEW.kind<>OLD.kind OR NEW.payload IS DISTINCT FROM OLD.payload OR NEW.evidence IS DISTINCT FROM OLD.evidence) THEN
        RAISE EXCEPTION 'Candidate content changes require a new revision';
      END IF;
      IF TG_OP='INSERT' THEN
        SELECT * INTO source_row FROM source_revisions WHERE revision_id=NEW.source_revision_id;
        PERFORM 1 FROM profiles WHERE id=source_row.profile_id FOR UPDATE;
        SELECT * INTO version_row FROM knowledge_versions WHERE id=source_row.knowledge_version_id FOR UPDATE;
        IF version_row.status<>'draft' OR version_row.model_revision_id<>source_row.model_revision_id THEN
          RAISE EXCEPTION 'Candidate requires current bound draft version';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_candidate_content BEFORE INSERT OR UPDATE ON draft_candidates FOR EACH ROW EXECUTE FUNCTION protect_candidate_revision();
    ''')

def downgrade():
    op.execute('DROP TABLE raw_extractions, draft_candidates, extraction_jobs, source_revisions; DROP FUNCTION IF EXISTS protect_source_revision(), protect_candidate_revision()')
