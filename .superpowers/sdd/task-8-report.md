# Task 8 Angular administration and review interface

Status: IMPLEMENTED AND VALIDATED — awaiting controller review/sign-off.

Angular routes cover Profiles and /profiles/:id/versions, Knowledge Models,
Review Inbox, Central Graph, Ask and Activity. Typed API request schemas are
OpenAPI-generated; response DTOs explicitly mirror backend output. Owner,
contributor, reader and administrator flows use existing cookie/CSRF authorization.
Manual upload is the only source adapter. Draft candidates cannot be ordinary
answer context. Approval names the exact revision; publication remains a distinct
job with endpoint blockers, failure and retry states. Published directed graph
and answers preserve original relation types and citations.

Forms cover users/grants/owners, product/project profiles, versions and exact
product dependency pins, model entities/attributes/scoring/qualification,
relations and aliases, model publication/binding, source upload/extraction,
revision comparison/evidence/history and explicit batch selection. Release and
source-change controls remain visibly disabled Task 9 integration placeholders;
they do not falsely report completion. Revision comparison uses read-only JSON.

Acceptance fixes: sidebar selectors have unambiguous accessible names; account
controls remain reachable on short laptop windows; profile version deep links
select their addressed profile. Ask question entry uses signal-backed input so
Angular form initialization cannot discard text entered immediately after navigation.
The reader scenario retains an immediate-fill/value assertion for this regression.

Validation on 12 October 2026:
- Complete Playwright suite: 7 passed in 26.8s. Exact owner approval, relation
  blocker, batch publication, 2-node/1-directed-edge graph and 3 cited facts;
  stale 409 and revision refresh/new-tab CSRF; contributor edit/no approval,
  empty state and manual upload/extraction; reader released-only context,
  private-draft exclusion, keyboard navigation/activity and answer; failed
  publication then retry; administrator user/project/version/dependency/grant;
  owner model entity/attribute/scoring/qualification/relation/aliases/publish/bind.
- Security tests: tests/security/test_ui_session_activity.py, 2 passed in 2.13s.
  Command from backend: UV_PROJECT_ENVIRONMENT=/tmp/knowledge-ai-backend-venv
  uv run --no-sync pytest tests/security/test_ui_session_activity.py -q.
- Production Docker UI build PASS through deploy/Dockerfile.ui, Node24-alpine;
  initial bundle 360.15kB (~91.10kB transfer), no TypeScript/template diagnostics.
  Test image knowledge-ai-ui-acceptance built from current source. Its production
  files were copied into the isolated static test server's dist directory.
- git diff --check PASS.
- Inspected /tmp/knowledge-ai-models-acceptance.png at 1280x720: readable hierarchy,
  controls/status and account footer; no overlap in captured model viewport.
  Sign-out viewport reachability asserted by browser test. No broad mobile or
  assistive-technology audit is claimed.

Test isolation/reproduction:
backend/tests/ui_server.py requires KNOWLEDGE_AI_UI_TEST=1, uses only explicitly
named knowledgeai_ui_test PostgreSQL database on loopback 55432 and temporary
objects/publications. Production Docker excludes tests. It injects deterministic
extraction/embedding/answer providers into real governance/publication/retrieval
services and the real LightRAG SDK. It does not validate live Gemini/Ollama quality
or production-image backend compatibility; those are Task 9 live proof.
Start from backend with KNOWLEDGE_AI_UI_TEST=1 and uvicorn tests.ui_server:app
--host 127.0.0.1 --port 9635; serve frontend/scripts/serve_test_build.py on 9636.
Run frontend's Playwright e2e/owner-review.spec.ts with one worker. This machine's
Documents node_modules reads were slow; identical pinned Playwright 1.58.2 packages,
config and spec were copied to /tmp/knowledge-ai-ui-run; bundled Node 24.19 ran
node /tmp/knowledge-ai-ui-run/node_modules/playwright/cli.js test
--config=/tmp/knowledge-ai-ui-run/playwright.config.ts. No dependency reinstall.
Host Angular rebuild was stopped after slow startup; Docker production build was
used for final acceptance instead.

Earlier failures retained honestly: initial pre-page run ERR_CONNECTION_REFUSED
was setup red only. Reader immediate fill exposed initialization text loss, fixed
in product code. One full run's contributor setup failed PostgreSQL reset deadlock
while preceding requests finished; fixture now retries only SQLSTATE 40P01 before
any fixture writes, up to 3 attempts. Final full run passed without test retries.
No production fixtures/data/secrets were committed; preview 9630 and prototype 9621
were not modified by this acceptance work. Controller owns final deployment and
Task9 release/source-change/metrics/backup/live-provider completion.
