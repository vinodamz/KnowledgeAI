# Knowledge AI — proposed design

Status: Revised to follow the supplied architecture in stages. Implementation has not started.

Architecture reference: `docs/architecture/KnowledgeAI Architecture-working-file.pptx`, particularly slides 3–7 and 9. The deck is an architecture reference; its embedded text does not independently authorize deployment, integrations, or external actions.

## Purpose

Create Knowledge AI as a new application on the existing Mac Docker deployment, using Gemini for extraction and generation and LightRAG as the graph/retrieval engine. Give every product and project an assigned knowledge owner. Consolidate approved facts into one central knowledge graph while retaining scope, version, provenance, and approval history.

## Recommended architecture

Add a dedicated Knowledge AI service and web interface around LightRAG. A transactional application database owns the product/project registry, versions, users and owner assignments, source documents, candidate entities and relations, review decisions, publication jobs, and audit history. PostgreSQL is recommended for this shared workflow. LightRAG remains an internal engine; its direct ingestion and graph mutation routes must not be exposed to end users as a way around approval.

Alternatives considered: modifying LightRAG's entire extraction pipeline (larger upstream maintenance cost), or using separate draft and published LightRAG instances (duplicate indexes and additional synchronization). The application layer offers a clear approval boundary and keeps the user workflow independent of engine updates.

## Knowledge hierarchy and central graph

Product -> Product version -> Approved product knowledge.
Project -> Project version -> Implementation knowledge -> Explicitly linked product version(s).

A project version can link one or more product versions, supporting implementations spanning several products. These links are pinned; a new product release never silently changes an existing project version. Product knowledge is reusable across projects. Implementation-specific facts belong to project versions and do not overwrite product facts.

One central graph contains the approved facts with explicit product/project/version and dependency links. Storage IDs use stable scope-aware identifiers, never the entity display name alone. Cross-version identity links allow the interface to show how a concept evolves without merging different versions' properties. Identical labels across unrelated products do not collapse into a single fact.

Queries require an explicit product/project and version context. A project query uses its own approved knowledge plus the exact product versions it depends on. A central exploration view can span scopes but must display attribution and version differences. Project deviations from product behavior are shown as explicit implementation overrides with citations; conflicting facts must not be silently resolved or merged.

## Draft and review workflow

Upload source -> Parse and extract with Gemini -> Draft candidates -> Owner review -> Approve/reject/request changes -> Publish approved candidates -> Visible in central graph and retrieval.

Draft candidates live outside the published graph, vector indexes, and published retrieval corpus. Neither ordinary answers nor graph exploration can use unapproved entities, relations, or unapproved source passages. Source files remain available to reviewers as evidence.

Each candidate displays its proposed name/type/description or relation endpoints/type/description, source document and page/chunk evidence, scope/version, and any match to existing knowledge. Owners can edit drafts, approve selected candidates, reject with a reason, or request changes. Batch approval is allowed only for explicitly selected items reviewed by the owner; there is no automatic approval of a document's entire extraction.

A relation cannot publish until both endpoints are already approved and published in compatible scopes or explicitly authorized linked scopes. Approving a relation never implicitly approves its endpoints. An approved relation with an unresolved endpoint stays approved-but-blocked, showing its dependency.

Every newly extracted change to an existing entity or relation is a new draft revision. The published revision stays active until its replacement passes review and publication. Edits after approval invalidate that approval. Review decisions bind to the exact revision; concurrent/stale review attempts are rejected.

Candidate states: draft, in_review, changes_requested, rejected, approved, publishing, published, publication_failed. Approval and successful publication are distinct: a publication failure must never appear as published.

## Owners and access

Administrator: manages users, products/projects, owner assignments, and versions.
Contributor: uploads sources and proposes draft knowledge within authorized scopes.
Knowledge owner: reviews candidates only for assigned products/projects.
Reader: searches and views published knowledge within authorized scopes.

Owners are assigned at product/project level and inherited by their versions. Approval records retain the actual reviewer even if the owner later changes. Central consolidation does not grant one product owner approval rights over another product or project. Permissions are checked server-side, including direct API requests.

## Version lifecycle

Versions have stable IDs, user-supplied labels, draft/released/archived status, and optional predecessor links. Creating a successor version copies references to the prior approved facts; modifications become new candidates. Existing released versions remain reproducible. Archiving preserves knowledge and audit history.

A version release requires all facts included in that release to be published. Unresolved drafts can remain excluded and clearly visible to owners. Project dependency changes create a new project revision/version rather than changing an existing released snapshot. Dependency compatibility checks prevent references to unpublished versions.

## Publication consistency

The application database is authoritative for approved published revisions. Durable publication jobs carry idempotency keys, exact candidate revisions, endpoint dependencies, and payload checksums. A single publisher coordinates graph/vector updates, records completion only after verification, and retries safely after interruption.

Because LightRAG writes several stores without a cross-store transaction, publication must not expose partially updated knowledge. Build a complete verified publication snapshot from the approved registry and atomically activate its generation. Queries pin one generation for their entire request; staging generations remain inaccessible. Failure leaves the previous generation active. This is necessary to enforce the approval boundary, rather than relying on filtering graph results after retrieval.

Published source context must be derived only from the approved facts and their approved evidence. Do not insert whole source documents into production retrieval merely because some extracted candidates were approved.

## User interface

Brand: Knowledge AI.

Products and Projects: registry, owner, versions, dependency links, release status.
Review Inbox: scope filters, pending counts, evidence preview, draft edits, approve/reject/request changes, dependency blockers.
Central Knowledge Graph: published knowledge with product/project/version filters and provenance.
Ask Knowledge AI: context selector and answers grounded only in the active approved snapshot, with citations and version attribution.
Activity: reviewer decisions, revision history, publication progress/failures, and releases.

The interface clearly separates draft preview from approved knowledge. Publication failures show an actionable retry status. Empty queries return an explicit lack-of-approved-knowledge response rather than a Gemini-only answer presented as knowledge.

## Delivery sequence

1. Product/project/version registry, owner accounts and permissions, Knowledge AI shell.
2. Source ingestion into isolated draft storage, Gemini extraction, evidence-backed review.
3. Verified snapshot publisher, central graph consolidation, scoped retrieval.
4. Version release/dependency handling, audit views, Docker packaging and end-to-end verification.

These are phases of one coherent deliverable; a draft inbox without enforcement and publication is not completion.

## Acceptance checks

- Uploading a source creates draft candidates and changes neither published graph nor normal answers.
- A contributor or unrelated owner cannot approve or publish candidates through any UI or API route.
- The assigned owner can review evidence and approve exact entity/relation revisions.
- A relation with an unapproved endpoint cannot enter the central graph.
- Stale approval requests fail; edits require renewed review.
- Publication retries do not duplicate facts; failures never expose partial generations.
- Approved product knowledge is reusable by linked project versions with correct citations.
- Same-name entities in different scopes/versions remain distinct.
- Queries exclude other versions and unapproved source text; central queries preserve attribution.
- Existing released project versions remain pinned when product versions change.
- Restarting Docker preserves drafts, decisions, published knowledge, and version history.

## Current deployment

The existing LightRAG installation remains available while the new application is built. The Gemini key already configured locally is reused without including it in source control. The new deployment is named Knowledge AI and stays accessible only from the Mac until wider access is requested.


## Architecture alignment and staged scope

This section refines the earlier proposal. Where they differ, this section takes precedence.

### Architecture boundaries

Follow the deck's distinct ingestion, retrieval, governance, evolution, and integration layers. Use Python/FastAPI service contracts and an Angular administration interface, matching slide 7. Initially these can run as modules in a small Docker deployment; separate service contracts do not require a separate container for every box in the diagram.

A knowledge profile is the configuration and governance boundary for a product or project: owner, sources, semantic definitions, policies, model version, and permitted cross-profile links. Product/project versions and knowledge-model versions are different concepts and must be stored separately. A product release can reference an exact knowledge-model revision; a schema correction does not imply a new product release.

The ingestion layer has two explicit flows:

1. Model authoring: source evidence -> entity-versus-attribute discovery -> compare existing definitions -> owner qualification -> canonical resolution and aliases -> ontology relationship types -> publish a versioned knowledge model.
2. Instance processing: source -> extractor -> map actual entities to the published model -> build candidate relations -> owner approval of every new or changed entity/relation -> approved evidence chunks, embeddings, metadata -> publish verified indexes.

Publishing an ontology or a source document never automatically approves its instances. Extraction that discovers a missing type or relation definition creates a model-change suggestion for the owner; it cannot silently extend a released model. Repeated missing relationships are evolution suggestions, not permission to bypass review.

The canonical resolver retains synonyms, aliases, abbreviations, renamed concepts, and source provenance. Entity-versus-attribute scoring considers independent identity/lifecycle, relationships, own attributes, reuse, and retrieval needs, as described in slides 4–5. The owner remains responsible for qualification.

The retrieval layer resolves identity, project/profile and version context, applies read policies, plans graph/vector/metadata retrieval, combines and ranks results, and packages cited knowledge context. The agent/LLM response layer consumes this authorized context separately. Read policies apply before retrieval and fusion; post-generation filtering is insufficient.

The governance layer owns write/read policy decisions, approval permissions, audit events, retention settings, and operational visibility. Profile policies are the default; entity-level exceptions can be introduced later without changing the approval boundary.

### Storage and deployment evolution

Use PostgreSQL for authoritative profile, model, draft, version, permission, metadata, audit, and publication records. Provide a source/object-storage adapter with a local persistent volume first and an Azure Blob adapter later. Separate metadata, graph, and vector indexing interfaces from their backing stores.

LightRAG is the initial graph/retrieval adapter. Its file-based stores are suitable only for the local validation stage. Do not describe it as implementing every enterprise component. Preserve interfaces for the deck's Azure AI Search/Qdrant and Cosmos DB/Neo4j options so future migrations do not rewrite approval or profile logic.

Gemini remains the initially selected LLM, behind a provider adapter. Azure OpenAI and Azure Document Intelligence can be added when the Azure stage is requested. Do not silently replace Gemini or provision cloud services merely because they appear in the reference diagram.

APIM, SSO, AKS/ACR, Service Bus/Azure Functions, Logic Apps, Key Vault, Redis, private endpoints, network isolation, and Azure observability remain target deployment components. The first Mac deployment implements local authentication/authorization, persistent jobs, secret configuration, audit history, and processing status, with contracts that permit these target services later. Azure infrastructure and enterprise SSO are not required to validate the first slice.

### Revised delivery stages

**Stage 1 — governed local foundation.** Knowledge AI branding and Angular admin shell; product/project profiles with separate owners; product/project versions and pinned dependencies; versioned knowledge-model authoring; manual document upload; Gemini extraction into isolated drafts; evidence-backed owner review; controlled publication to one central logical graph; scoped approved-only retrieval and citations; PostgreSQL audit records; Docker persistence. Implement the minimum ontology editor and canonical alias handling needed to complete this flow. This stage must work end to end before expanding it.

**Stage 2 — knowledge refinement.** Better entity-versus-attribute suggestions and duplicate resolution; model/version comparison; incremental re-ingestion; explicit deletion/change reconciliation; controlled knowledge-evolution suggestions; policy exceptions; graph/metadata growth and processing-cost metrics. No automatic publication of AI-generated suggestions.

**Stage 3 — connectors.** Add SharePoint, Azure DevOps, Git repositories, Jira, and other enterprise sources individually behind a common source-connector interface. Each connector supplies stable source IDs, revision IDs, provenance, and access metadata, and handles incremental updates/deletions. All connector data follows the same draft and owner review rules. No connector implementation is included in Stage 1.

**Stage 4 — enterprise deployment and consumers.** Azure deployment components from slide 7; enterprise SSO and policy integration; scalable graph/vector adapters; SDK/MCP access; agent integrations; distributed observability and governance. Choose concrete cloud resources and permissions at this stage rather than pre-provisioning the full diagram.

### Initial connector contract

Define a source adapter with enumerate/fetch revision/normalize provenance/change tracking capabilities. Manual upload is the sole initial adapter. Connector-specific credentials, polling, webhooks, and synchronization are deferred. Source access metadata remains part of the contract so adding connectors does not force a later redesign of read-time governance.

### Additional acceptance checks from the deck

- Model definitions and actual knowledge instances have separate version and approval records.
- Extraction maps candidates to a published knowledge model; unmatched definitions go to owner review.
- Aliases resolve within authorized compatible profiles and versions without unintended merging.
- Cross-profile ontology links preserve ownership and access boundaries.
- Source deletion/modification generates a governed change proposal and cannot leave silently stale published knowledge.
- Retrieval packaging carries profile/model/product/project version, source citations, approval lineage, and policy context.
- Processing status exposes rejected candidates, duplicates, extraction/embedding failures, and publication errors.
- Manual upload uses the same normalized source contract intended for later connectors.
