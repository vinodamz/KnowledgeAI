# Knowledge AI local foundation

Copy `.env.example` to `.env`. Replace the database password and signing secret with separately generated random values (URL-safe values are suitable). The signing secret must have at least 32 characters. Never commit `.env`.

Run `docker compose --env-file .env -f deploy/compose.yml up --build -d`. The migration service upgrades PostgreSQL before the API and worker start. The API is available at `http://127.0.0.1:9631`; `/health` checks the process and `/ready` checks the migrated registry. The UI placeholder is optional through `--profile ui-placeholder`; the Angular UI and same-origin proxy arrive in Task 8 on port 9630.

Run `scripts/bootstrap-admin.sh YOUR_USERNAME` from a terminal. It prompts for a password of at least 12 characters and confirmation, refuses duplicate usernames, and records the bootstrap audit event. There is no public registration route.

POST JSON username/password to `/api/auth/login`. Successful login sets an HttpOnly, SameSite=Strict signed session cookie and returns `csrf_token`. Supply that token as `X-CSRF-Token` on mutations. GET `/api/auth/me` returns identity; POST `/api/auth/logout` revokes the server session. Login refuses a foreign Origin. For a future HTTPS deployment set `KNOWLEDGE_AI_SECURE_COOKIES=true`. UI proxy must preserve the original origin/host to satisfy same-origin login.

The worker is a runnable host awaiting durable ingestion/publication handlers. No engine routes or LightRAG mutations are exposed. The existing LightRAG prototype is not imported.

For tests, start isolated PostgreSQL on loopback port 55432 with database `knowledgeai_test`, user `postgres`, password `testpassword`, then run `cd backend && uv run pytest -q`. An alternative PostgreSQL URL can be supplied as `KNOWLEDGE_AI_TEST_DATABASE_URL`; the database name must end in `_test`. Tests migrate and truncate identity tables in that disposable test database.

On this Mac, use `cd backend && UV_PROJECT_ENVIRONMENT=/tmp/knowledge-ai-backend-venv uv sync` once, then `UV_PROJECT_ENVIRONMENT=/tmp/knowledge-ai-backend-venv uv run --no-sync pytest -q` to keep installed dependencies outside the synced Documents folder.
