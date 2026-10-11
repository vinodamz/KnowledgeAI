"""Exact revision decisions with append-only history."""
from alembic import op
revision='004_review'
down_revision='003_sources_candidates'
branch_labels=None
depends_on=None

def upgrade():
    op.execute("""ALTER TABLE draft_candidates DROP CONSTRAINT draft_candidates_state_check;
    ALTER TABLE draft_candidates ADD CONSTRAINT draft_candidates_state_check CHECK(state IN ('pending','approved','rejected','changes_requested'));
    CREATE TABLE review_decisions (
      id uuid PRIMARY KEY,candidate_id uuid NOT NULL,candidate_revision integer NOT NULL,
      actor_id uuid NOT NULL REFERENCES users(id), decision text NOT NULL CHECK(decision IN ('approve','reject','request_changes')),
      previous_state text NOT NULL,reason text,checksum text NOT NULL,created_at timestamptz NOT NULL,
      FOREIGN KEY(candidate_id,candidate_revision) REFERENCES draft_candidates(id,revision));
    CREATE FUNCTION protect_review_decision() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Review history is append only'; END $$;
    CREATE TRIGGER immutable_review_decision BEFORE UPDATE OR DELETE ON review_decisions FOR EACH ROW EXECUTE FUNCTION protect_review_decision();
    """)

def downgrade():
    op.execute("DROP TABLE review_decisions; DROP FUNCTION protect_review_decision(); UPDATE draft_candidates SET state='pending' WHERE state='changes_requested'; ALTER TABLE draft_candidates DROP CONSTRAINT draft_candidates_state_check; ALTER TABLE draft_candidates ADD CONSTRAINT draft_candidates_state_check CHECK(state IN ('pending','approved','rejected'))")
