# Knowledge AI local development preview

Copy `.env.example` to `.env`. Replace the database password and signing secret with separately generated random values (URL-safe values are suitable). The signing secret must have at least 32 characters. Never commit `.env`.

Run `docker compose --env-file .env -f deploy/compose.yml up --build -d`. The migration service upgrades PostgreSQL before the API and worker start. The API is available at `http://127.0.0.1:9631`; `/health` checks the process and `/ready` checks the migrated registry. The Angular UI and same-origin API proxy run by default at `http://localhost:9630`. Login through the UI. This is a development preview: full browser acceptance and immutable release/source-change workflows are still pending.

Run `scripts/bootstrap-admin.sh YOUR_USERNAME` from a terminal. It prompts for a password of at least 12 characters and confirmation, refuses duplicate usernames, and records the bootstrap audit event. There is no public registration route.

POST JSON username/password to `/api/auth/login`. Successful login sets an HttpOnly, SameSite=Strict signed session cookie and returns `csrf_token`. Supply that token as `X-CSRF-Token` on mutations. GET `/api/auth/me` returns identity; POST `/api/auth/logout` revokes the server session. Login refuses a foreign Origin. For a future HTTPS deployment set `KNOWLEDGE_AI_SECURE_COOKIES=true`. The included UI proxy preserves the original origin/host to satisfy same-origin login. GET `/api/auth/csrf` securely recovers the session token after refresh or in a new tab.

The worker processes durable Gemini extraction jobs and builds verified, isolated LightRAG publication generations using the configured Ollama embedding model. No engine routes or LightRAG mutations are exposed. The existing LightRAG prototype is not imported.

For tests, start isolated PostgreSQL on loopback port 55432 with database `knowledgeai_test`, user `postgres`, password `testpassword`, then run `cd backend && uv run pytest -q`. An alternative PostgreSQL URL can be supplied as `KNOWLEDGE_AI_TEST_DATABASE_URL`; the database name must end in `_test`. Tests migrate and truncate identity tables in that disposable test database.

On this Mac, use `cd backend && UV_PROJECT_ENVIRONMENT=/tmp/knowledge-ai-backend-venv uv sync` once, then `UV_PROJECT_ENVIRONMENT=/tmp/knowledge-ai-backend-venv uv run --no-sync pytest -q` to keep installed dependencies outside the synced Documents folder.

For Gemini extraction/answers set `KNOWLEDGE_AI_GEMINI_API_KEY` and `KNOWLEDGE_AI_GEMINI_MODEL` in local `.env`. The default embedding provider is native Ollama through `http://host.docker.internal:11434` with `nomic-embed-text` (768 dimensions). Keep provider identity consistent with sealed publication generations.

Current Mac checkpoint verification: Docker UI and API builds passed; PostgreSQL migrations completed; API readiness, same-origin proxy login, authenticated identity, CSRF recovery and empty registry passed; rendered browser login and navigation checked. Separate automated browser acceptance continues against disposable `knowledgeai_ui_test`, not the preview registry. Local administrator credentials are in gitignored `secrets/Knowledge AI login.txt`; do not commit or share that file.
