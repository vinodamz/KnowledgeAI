# Knowledge AI

Governed, version-aware product and implementation knowledge, consolidated into one central knowledge graph.

## Current status

Architecture and implementation planning. Application implementation has not started. The existing local LightRAG prototype is a separate deployment, not the completed Knowledge AI application.

## Documents

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
