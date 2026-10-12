# Knowledge AI local development preview

Copy `.env.example` to `.env`. Replace the database password and signing secret with separately generated random values (URL-safe values are suitable). The signing secret must have at least 32 characters. Never commit `.env`.

Run `docker compose --env-file .env -f deploy/compose.yml up --build -d`. The migration service upgrades PostgreSQL before the API and worker start. The API is available at `http://127.0.0.1:9631`; `/health` checks the process and `/ready` checks the migrated registry. The Angular UI and same-origin API proxy run by default at `http://localhost:9630`. Login through the UI. This is a development preview: nine isolated browser acceptance scenarios passed; Task 8 review sign-off and immutable release/source-change workflows remain pending.

Run `scripts/bootstrap-admin.sh YOUR_USERNAME` from a terminal. It prompts for a password of at least 12 characters and confirmation, refuses duplicate usernames, and records the bootstrap audit event. There is no public registration route.

POST JSON username/password to `/api/auth/login`. Successful login sets an HttpOnly, SameSite=Strict signed session cookie and returns `csrf_token`. Supply that token as `X-CSRF-Token` on mutations. GET `/api/auth/me` returns identity; POST `/api/auth/logout` revokes the server session. Login refuses a foreign Origin. For a future HTTPS deployment set `KNOWLEDGE_AI_SECURE_COOKIES=true`. The included UI proxy preserves the original origin/host to satisfy same-origin login. GET `/api/auth/csrf` securely recovers the session token after refresh or in a new tab.

The worker processes durable Gemini extraction jobs and builds verified, isolated LightRAG publication generations using the configured Ollama embedding model. No engine routes or LightRAG mutations are exposed. The existing LightRAG prototype is not imported.

For tests, start isolated PostgreSQL on loopback port 55432 with database `knowledgeai_test`, user `postgres`, password `testpassword`, then run `cd backend && uv run pytest -q`. An alternative PostgreSQL URL can be supplied as `KNOWLEDGE_AI_TEST_DATABASE_URL`; the database name must end in `_test`. Tests migrate and truncate identity tables in that disposable test database.

On this Mac, use `cd backend && UV_PROJECT_ENVIRONMENT=/tmp/knowledge-ai-backend-venv uv sync` once, then `UV_PROJECT_ENVIRONMENT=/tmp/knowledge-ai-backend-venv uv run --no-sync pytest -q` to keep installed dependencies outside the synced Documents folder.

For Gemini extraction/answers set `KNOWLEDGE_AI_GEMINI_API_KEY` and `KNOWLEDGE_AI_GEMINI_MODEL` in local `.env`. The default embedding provider is native Ollama through `http://host.docker.internal:11434` with `nomic-embed-text` (768 dimensions). Keep provider identity consistent with sealed publication generations.

Current Mac checkpoint verification: Docker UI and API builds passed; PostgreSQL migrations completed; API readiness, same-origin proxy login, authenticated identity, CSRF recovery and empty registry passed; rendered browser login and navigation checked. Separate automated browser acceptance passed nine scenarios against disposable `knowledgeai_ui_test`, using real governance/publication/retrieval services and LightRAG SDK with deterministic injected providers. This does not establish live Gemini/Ollama behavior or final production-backend compatibility; Task 9 owns that proof. Local administrator credentials are in gitignored `secrets/Knowledge AI login.txt`; do not commit or share that file.

## Isolated browser acceptance

Build the production UI with `deploy/Dockerfile.ui` or `npm --prefix frontend run build` using supported Node 24. Start the opt-in test API from `backend` with `KNOWLEDGE_AI_UI_TEST=1 uv run uvicorn tests.ui_server:app --host 127.0.0.1 --port 9635`; it creates/resets only the disposable `knowledgeai_ui_test` database on test PostgreSQL port 55432 and temporary object/generation directories. The test module is excluded from production Docker images. Do not run fixtures against the development preview registry.

Serve the built UI/proxy with `python3 frontend/scripts/serve_test_build.py` on loopback 9636, then run `npm --prefix frontend run test:e2e -- e2e/owner-review.spec.ts`. The nine scenarios cover governed owner publication, contributor/reader restrictions, stale revisions/session recovery, manual upload, administration/dependency grants, model authoring, delayed/out-of-order profile scope changes, and status-monitor failure/recovery without discarding open review inputs.
