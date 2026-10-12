# Knowledge AI

Governed, version-aware product and implementation knowledge, consolidated into one central knowledge graph.

## Current status

Stage 1 development preview is implemented and running locally. Backend tasks 1–7 passed their review gates: authentication, profiles/versions, model authoring, Gemini draft extraction, exact-revision owner review, verified publication and scoped cited retrieval. The Angular administration UI builds and runs in Docker; nine browser acceptance scenarios passed against an isolated PostgreSQL/real-SDK test stack with deterministic injected providers. Task 8 review sign-off and Task 9 release snapshots/source changes/operating proof remain pending. Stage 1 is not yet complete.

Open **http://localhost:9630** for Knowledge AI. The API binds to loopback port 9631. The existing LightRAG prototype on port 9621 remains separate.

Start with `docker compose --env-file .env -f deploy/compose.yml up --build -d`, then bootstrap an administrator as described in [local setup](docs/runbooks/local-setup.md). Secrets and local login files are excluded from Git.

## Documents

- [Install on another PC using Docker](docs/runbooks/install-on-another-pc.md)
- [Build/publish portable Docker images](.github/workflows/publish-demo-images.yml)
- [Architecture reference](docs/architecture/KnowledgeAI%20Architecture-working-file.pptx)
- [Design specification](docs/superpowers/specs/2026-10-11-knowledge-ai-design.md)
- [Stage 1 implementation plan and later roadmap](docs/superpowers/plans/2026-10-11-knowledge-ai.md)

## Core rules

- Each product/project has an assigned knowledge owner.
- Every new or changed entity and relation remains in draft until its owner approves the exact revision.
- Only approved and successfully published knowledge enters graph/vector/metadata retrieval.
- Product, project, and knowledge-model versions remain distinct.
- Project versions depend on pinned product versions.
- Separate ingestion, retrieval, governance, evolution, and integration boundaries follow the supplied architecture.

## Delivery order

1. Governed local foundation with manual uploads, model authoring, draft review, publication, and approved-only retrieval.
2. Knowledge refinement, incremental changes, reconciliation, and operational metrics.
3. Connectors added individually: SharePoint, Azure DevOps, Git, Jira, then other systems.
4. Enterprise Azure deployment, SSO, SDK/MCP, and agent integrations.

Initial target: Docker on macOS; Angular administration UI; Python/FastAPI; PostgreSQL; Gemini; LightRAG behind a replaceable indexing adapter.

No credentials, source documents being indexed, or live knowledge data belong in this repository.
