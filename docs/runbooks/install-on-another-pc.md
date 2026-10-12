# Install Knowledge AI on another computer

This installs the reviewed demo checkpoint from `codex/demo-stage-1`. Release snapshots and source-change features under development on `codex/stage-1` are not included in this demo image.

The stack includes the Angular app, API, worker, PostgreSQL and Ollama. It downloads `nomic-embed-text` automatically. Gemini requires your own API key. Database records, documents, graph files, credentials and your Mac's existing data are not included in images.

## 1. Prepare the computer

Install Git and Docker Desktop on Windows/macOS, or Docker Engine with the Compose plugin on Linux. On Windows, use Docker's Linux containers. Start Docker and verify `docker compose version` works. Internet access is needed for images, the embedding model and Gemini requests.

Clone the private repository using a GitHub account with access:

```sh
git clone --branch codex/demo-stage-1 https://github.com/vinodamz/KnowledgeAI.git
cd KnowledgeAI
```

## 2. Create private configuration

The following command works in macOS/Linux terminals and Windows PowerShell; it uses Docker's Python, so Python need not be installed on the PC:

```sh
docker run --rm -v "${PWD}:/work" -w /work python:3.12-slim python scripts/create-docker-env.py
```

Open `.env` in a text editor. Replace `PASTE_YOUR_GEMINI_API_KEY_HERE` with your Gemini API key. The script generates separate random database and session secrets, prints none of them, and refuses to overwrite an existing `.env`.

Keep `.env` private. On Windows, save it as `.env`, not `.env.txt`. If ports 9630/9631 are occupied, change `KNOWLEDGE_AI_UI_PORT` and `KNOWLEDGE_AI_API_PORT` in that file.

## 3A. Install using the published images

The publishing workflow builds both `linux/amd64` (Intel/AMD PCs) and `linux/arm64` (Apple Silicon/ARM). Check that the [image publishing run](https://github.com/vinodamz/KnowledgeAI/actions/workflows/publish-demo-images.yml) succeeded before pulling.

Images are private. Sign in to GitHub Container Registry using your GitHub username and a classic personal access token with `read:packages` and access to these packages; enter the token at Docker's password prompt:

```sh
docker login ghcr.io -u YOUR_GITHUB_USERNAME
docker compose --env-file .env -f deploy/compose.portable.yml pull
docker compose --env-file .env -f deploy/compose.portable.yml up -d
```

Images: `ghcr.io/vinodamz/knowledge-ai-api:demo` and `ghcr.io/vinodamz/knowledge-ai-ui:demo`. The API image is also used by migration and worker services. Each build additionally publishes an immutable full Git-commit tag; set `KNOWLEDGE_AI_IMAGE_TAG` to that commit to pin an exact build.

## 3B. Build locally instead

If registry authentication is unavailable, build from the cloned source. No registry token is needed:

```sh
docker compose --env-file .env -f deploy/compose.portable.yml -f deploy/compose.portable-build.yml build
docker compose --env-file .env -f deploy/compose.portable.yml -f deploy/compose.portable-build.yml up -d --pull missing
```

The build chooses the host's native architecture. Base images and the embedding model still require internet access. On the first startup, model download can take a few minutes. Wait for `embedding-model` and `migrate` to finish successfully; an exited code 0 for those services is normal.

## 4. Create your administrator

```sh
docker compose --env-file .env -f deploy/compose.portable.yml exec api python -m knowledge_ai.cli vinod
```

Enter a new password of at least 12 characters and confirm it. There is no default password; existing usernames are preserved. Open **http://localhost:9630** (or your configured UI port) and sign in.

Create owner accounts and assign each product/project's owner. Define and qualify its knowledge model, bind the model to a draft knowledge version, upload a document, review exact entity/relation revisions as that owner, and publish selected approved facts. Graph and Ask use published facts only. Reader access to draft knowledge versions is excluded; use owner/contributor accounts for this demo's authoring workflow.

## Check and restart

```sh
docker compose --env-file .env -f deploy/compose.portable.yml ps -a
docker compose --env-file .env -f deploy/compose.portable.yml logs --tail 100 api worker embedding-model
docker compose --env-file .env -f deploy/compose.portable.yml restart
```

API readiness is at `http://localhost:9631/ready` by default. Named Docker volumes preserve PostgreSQL, uploaded documents, publication generations and embedding models across restarts. `docker compose ... down` stops services while preserving volumes; do not add `-v` unless intentionally deleting the local installation's data. These commands create a fresh installation; they do not transfer your Mac's knowledge records.

To update published images, pull again and run `up -d`. Back up data before changing the image tag. Release/source-change operating features remain a separate Stage 1 delivery gate.
