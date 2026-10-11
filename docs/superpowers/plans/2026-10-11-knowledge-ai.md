# Knowledge AI Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Delegation requires the user's choice.

**Goal:** Deliver a local Knowledge AI application with versioned product/project profiles, owner-reviewed knowledge, one central approved graph, and scoped cited retrieval.

**Architecture:** Follow the reference deck's ingestion, retrieval, governance, evolution, and integration boundaries. A PostgreSQL registry is authoritative; source extraction writes isolated drafts, and verified immutable publication generations feed LightRAG. Angular consumes FastAPI contracts; Gemini is a configurable provider.

**Tech Stack:** Python 3.12+, FastAPI/Pydantic, SQLAlchemy/Alembic, PostgreSQL, Angular/TypeScript, pytest, Playwright, Docker Compose, Gemini, LightRAG adapter.

## Global constraints

- Architecture reference: `docs/architecture/KnowledgeAI Architecture-working-file.pptx`, slides 3–7 and 9.
- Design: `docs/superpowers/specs/2026-10-11-knowledge-ai-design.md`; its architecture-alignment section takes precedence.
- Manual upload is the only Stage 1 source adapter. External connectors are separate later deliverables.
- Each product/project has its own assigned owner; approved knowledge consolidates centrally.
- Approval binds the exact candidate revision. Editing invalidates approval.
- Relations cannot publish unless both endpoints are published or included as approved endpoints in the same verified generation.
- Keep product versions, project versions, and knowledge-model versions distinct.
- Project versions pin exact product versions; released snapshots cannot be silently changed.
- Unauthorized, unapproved, staged, rejected, or failed knowledge cannot enter ordinary retrieval, citations, or model context.
- Gemini remains the initial provider; cloud infrastructure and Azure OpenAI are not provisioned during Stage 1.
- Secrets are supplied through local configuration; never committed. Indexed documents and database volumes are excluded from Git.
- Local ports bind to `127.0.0.1`; LightRAG engine mutation endpoints remain internal.
- Existing LightRAG prototype data is not automatically approved or migrated into Knowledge AI.
- No deployment dates or cloud budgets are assumed.

## Deliverable and file map

```text
backend/pyproject.toml
backend/alembic.ini
backend/migrations/versions/
backend/knowledge_ai/app.py
backend/knowledge_ai/settings.py
backend/knowledge_ai/db.py
backend/knowledge_ai/common/contracts.py
backend/knowledge_ai/governance/{auth,policy,audit}.py
backend/knowledge_ai/profiles/{models,service,routes}.py
backend/knowledge_ai/ontology/{models,resolver,service,routes}.py
backend/knowledge_ai/ingestion/{sources,parser,gemini,extraction,jobs,routes}.py
backend/knowledge_ai/review/{models,service,routes}.py
backend/knowledge_ai/publication/{models,builder,worker,routes}.py
backend/knowledge_ai/retrieval/{contracts,planner,service,routes}.py
backend/knowledge_ai/adapters/{object_store,lightrag}.py
backend/tests/{unit,integration,security}/
frontend/src/app/{core,profiles,models,review,graph,ask,activity}/
frontend/e2e/
deploy/{compose.yml,Dockerfile.api,Dockerfile.ui,Dockerfile.worker}
.env.example
scripts/{bootstrap-admin,verify-stage1}.sh
docs/runbooks/{local-setup,publication-recovery,backup-restore}.md
```

Organize files by responsibility. The initial service can be a modular application plus worker, rather than deploying every architecture box independently. PostgreSQL integration tests must use PostgreSQL, not SQLite substitutions for transaction/locking behavior.

## Delivery sequence and review gates

Each task is a separate commit and reviewable milestone. Write the behavioral test first, observe its failure, implement the contract, then pass the focused tests. Do not expose a partially governed ingestion route as a completed release.

### Task 1 — runnable foundation and owner authentication

**Files:** `backend/pyproject.toml`, `backend/knowledge_ai/{app,settings,db}.py`, `backend/knowledge_ai/governance/{auth,policy,audit}.py`, `backend/tests/security/test_identity.py`, `deploy/compose.yml`, `.env.example`, `scripts/bootstrap-admin.sh`.

**Contract:** `Actor(id: UUID, role: Literal['admin','owner','contributor','reader'])`; `authorize(actor, action, profile_id) -> None` raises a 403 refusal. Bootstrap an administrator through a local terminal command; use hashed passwords and authenticated server sessions. No public user-registration endpoint.

- [ ] Add an authentication regression test:
  ```python
  def test_anonymous_cannot_create_profile(client):
      assert client.post('/api/profiles', json={'name': 'Product A', 'kind': 'product'}).status_code == 401
  ```
- [ ] Run `cd backend && uv run pytest tests/security/test_identity.py -q`; observe refusal before adding protected routes.
- [ ] Create FastAPI app, settings validation, PostgreSQL connection/migrations, session authentication, CSRF protection for cookie-authenticated mutations, owner/admin/contributor/reader roles, and audit event insertion. Reject missing signing secrets at startup.
- [ ] Add health/readiness routes. Compose runs API, worker, PostgreSQL and UI with persistent volumes and loopback-only exposed ports. The indexing engine is reached through an internal adapter.
- [ ] Run focused authentication tests; verify invalid sessions and anonymous mutations are rejected and readiness fails when PostgreSQL is unavailable.
- [ ] Commit as `feat: add governed Knowledge AI foundation`.

**Exit:** A signed-in actor can use the application; identity is enforced by the API.

### Task 2 — profiles, separate owners, versions and dependency pins

**Files:** `profiles/{models,service,routes}.py`, `migrations/versions/001_profiles.py`, `tests/integration/test_profile_versions.py`, `tests/security/test_profile_owners.py`.

**Contract:** `Profile(id, kind, name, owner_id)`; `KnowledgeVersion(id, profile_id, label, predecessor_id, status)`; `ProjectDependency(project_version_id, product_version_id)`; `create_version(actor, profile_id, label, predecessor_id=None) -> KnowledgeVersion`.

- [ ] Add a cross-owner refusal test:
  ```python
  def test_owner_cannot_modify_another_profile(owner_b, product_a, client):
      r = client.patch(f'/api/profiles/{product_a.id}', actor=owner_b, json={'name': 'Changed'})
      assert r.status_code == 403
  ```
- [ ] Run `uv run pytest tests/security/test_profile_owners.py tests/integration/test_profile_versions.py -q` and capture failures.
- [ ] Add profile/version/dependency tables with unique version labels within each profile, foreign keys, owner assignments, predecessor links, and explicit draft/released/archived status. Admin assignment does not transfer approval authority implicitly to unrelated owners.
- [ ] Implement CRUD and authorization. Reject a project dependency on an incompatible/unreleased product version; allow multiple pinned product dependencies. Released version payloads are immutable.
- [ ] Test that a new product version leaves existing project dependency IDs unchanged, released versions reject mutation, and archive retains records.
- [ ] Commit as `feat: add knowledge profiles and pinned versions`.

**Exit:** Product/project knowledge and ownership cannot be conflated.

### Task 3 — versioned knowledge model and canonical resolver

**Files:** `ontology/{models,resolver,service,routes}.py`, `migrations/versions/002_ontology.py`, `tests/unit/test_canonical_resolver.py`, `tests/integration/test_model_publication.py`.

**Contract:** `KnowledgeModelRevision(id, profile_id, revision, status)`; `EntityType(id, model_revision_id, name, attributes)`; `RelationType(id, source_type_id, target_type_id, name)`; `CanonicalConcept(id, profile_id, name, aliases)`; `resolve_concept(profile_id, model_revision_id, label) -> Match | None`. Product/project versions reference exact model revision IDs.

- [ ] Test scoped alias resolution:
  ```python
  def test_alias_does_not_cross_unlinked_profiles(resolver, profiles):
      resolver.add_alias(profiles.a, 'PLC', 'Programmable Controller')
      assert resolver.resolve(profiles.b, 'PLC') is None
  ```
- [ ] Run `uv run pytest tests/unit/test_canonical_resolver.py tests/integration/test_model_publication.py -q`; verify failing behavior.
- [ ] Implement owner-editable model drafts with entity/attribute definitions, canonical labels, aliases, relation endpoint constraints, cross-profile links and profile semantic descriptions. Make published model revisions immutable.
- [ ] Add entity-versus-attribute scoring fields: identity, lifecycle, relationships, own attributes, reuse, retrieval rationale. Treat AI scores as suggestions requiring owner qualification.
- [ ] Test duplicate alias ambiguity, normalized label matches, model publication permissions, and independent product versus model version IDs.
- [ ] Commit as `feat: add versioned knowledge models and canonical resolution`.

**Exit:** Extraction has a published model to map against; missing definitions cannot extend it automatically.

### Task 4 — manual sources, extraction jobs and evidence-backed drafts

**Files:** `ingestion/{sources,parser,gemini,extraction,jobs,routes}.py`, `adapters/object_store.py`, `review/models.py`, `migrations/versions/003_sources_candidates.py`, `tests/integration/test_draft_ingestion.py`.

**Contract:** `SourceRevision(source_id, revision_id, profile_id, knowledge_version_id, model_revision_id, content_hash, provenance, access_policy)`; `Evidence(source_revision_id, page, chunk_id, start, end, excerpt)`; `Candidate(id, revision, kind, payload, evidence, state)`; `SourceAdapter.fetch_revision(source_id, revision_id) -> SourceRevision`; `extract(source_revision, model_revision) -> list[Candidate]`.

- [ ] Add an isolation test:
  ```python
  def test_upload_creates_drafts_without_publishing(api, graph, vectors, published_chunks):
      api.upload_fixture('product_manual.txt')
      api.wait_for_extraction()
      assert api.candidates()
      assert graph.count() == vectors.count() == published_chunks.count() == 0
  ```
- [ ] Run `uv run pytest tests/integration/test_draft_ingestion.py -q`; observe the isolation test fail before ingestion exists.
- [ ] Implement manual upload with stable IDs, hashes, size/type validation, safe filename handling and persistent object storage. Initially support TXT, Markdown and text-based PDF; explicitly reject image-only PDFs pending an OCR adapter.
- [ ] Implement asynchronous extraction jobs with durable statuses, retries and bounded Gemini calls. Validate structured Gemini output against the published model; unknown definitions become model suggestions, not published types. Preserve source/page/chunk evidence.
- [ ] Store entity/relation candidate revisions and raw extraction records only in draft storage. A re-upload of the same profile/version/model/content hash does not create duplicate jobs; a different source revision does.
- [ ] Test malformed output, provider errors, unauthorized upload, duplicate source hashes, missing types, failure recovery and absence of writes to every published store.
- [ ] Commit as `feat: extract manual sources into isolated review drafts`.

**Exit:** Uploads produce reviewable evidence, never immediate published knowledge.

### Task 5 — exact-revision review and relation dependency checks

**Files:** `review/{service,routes}.py`, `governance/policy.py`, `tests/integration/test_review_lifecycle.py`, `tests/security/test_review_permissions.py`.

**Contract:** `review_candidate(actor, candidate_id, expected_revision, decision, reason=None) -> ReviewDecision`; `edit_candidate(actor, candidate_id, expected_revision, payload) -> Candidate`; decisions: approve/reject/request_changes. Approved-but-blocked is a computed publication readiness status.

- [ ] Add stale-review and endpoint tests:
  ```python
  def test_stale_revision_cannot_be_approved(review, candidate, owner):
      review.edit_candidate(owner, candidate.id, 1, {'description': 'Corrected'})
      assert review.approve_http(owner, candidate.id, 1).status_code == 409

  def test_relation_approval_does_not_approve_endpoints(review, relation, owner):
      review.approve(owner, relation.id, relation.revision)
      assert review.endpoint_states(relation.id) == ['draft', 'draft']
      assert review.ready_to_publish(relation.id) is False
  ```
- [ ] Run `uv run pytest tests/integration/test_review_lifecycle.py tests/security/test_review_permissions.py -q`; observe the missing behavior.
- [ ] Implement database transactions and optimistic revision checks. Require the assigned scope owner; bind approval to a checksum of payload/evidence. Record actor, timestamp, previous state and reason in audit history.
- [ ] Editing creates a new revision and invalidates approval; the existing published revision remains active. Batch decisions enumerate exact candidate/revision pairs and enforce the same checks for each.
- [ ] Validate relation endpoints and cross-profile links; refuse publication readiness until approved endpoints are present in the target generation.
- [ ] Test wrong-owner calls, contributor approval, batch stale revisions, evidence changes, rejection reasons, and owner reassignment preserving past reviewer attribution.
- [ ] Commit as `feat: enforce owner approval for exact knowledge revisions`.

**Exit:** Neither UI nor direct API requests can bypass review.

### Task 6 — verified publication generations and recovery

**Files:** `publication/{models,builder,worker,routes}.py`, `adapters/lightrag.py`, `migrations/versions/004_publication.py`, `tests/integration/test_publication_generation.py`, `docs/runbooks/publication-recovery.md`.

**Contract:** `PublicationGeneration(id, scope_manifest, status)`; `build_generation(approved_manifest) -> GenerationReport`; `activate_generation(generation_id, expected_active_id) -> None`; `IndexAdapter.build(generation_id, approved_entities, approved_relations, approved_evidence) -> IndexReport`. Store separate physical workspaces per staging generation while presenting one central logical approved graph.

- [ ] Add fault-injection test:
  ```python
  def test_partial_index_failure_never_activates(stores, publisher, active_generation):
      stores.vectors.fail_next_write()
      result = publisher.publish_approved()
      assert result.status == 'publication_failed'
      assert publisher.active_id() == active_generation.id
  ```
- [ ] Run `uv run pytest tests/integration/test_publication_generation.py -q`; observe failure.
- [ ] Implement durable jobs with revision checksums, idempotency keys, a single publication writer, staging workspaces and generation manifests. Include approved endpoint closure and scope-aware stable IDs; never key solely on display labels.
- [ ] Build graph, vectors and approved evidence from the authoritative registry through the adapter. Do not ingest full original documents merely because some candidates are approved. Follow LightRAG storage contracts when using its custom-graph insertion interfaces.
- [ ] Verify all indexed facts, endpoint references, approved evidence and store counts against the manifest before activation. Transactionally swap the active pointer using compare-and-swap; requests retain their original generation until completion.
- [ ] Test process interruption at every store write/verification/activation boundary, duplicate retries, stale approval revisions, unavailable embeddings and failed active-pointer races. Publication status changes to published only after successful activation.
- [ ] Commit as `feat: publish approved knowledge through verified generations`.

**Exit:** Partial publication cannot leak into the active graph or answers.

### Task 7 — authorized retrieval, fusion and cited responses

**Files:** `retrieval/{contracts,planner,service,routes}.py`, `adapters/lightrag.py`, `tests/security/test_retrieval_scope.py`, `tests/integration/test_cited_answers.py`.

**Contract:** `RetrievalContext(actor_id, profile_id, knowledge_version_id, generation_id)`; `retrieve(context, query) -> KnowledgeContext`; `KnowledgeContext(items, citations, model_versions, policy_context)`; `answer(context, query) -> Answer`.

- [ ] Test draft/version exclusion:
  ```python
  def test_answer_context_excludes_draft_and_other_versions(service, seeded_context):
      result = service.retrieve(seeded_context, 'operating limits')
      assert all(item.approved for item in result.items)
      assert {item.version_id for item in result.items} <= seeded_context.allowed_version_ids
  ```
- [ ] Run `uv run pytest tests/security/test_retrieval_scope.py tests/integration/test_cited_answers.py -q`; verify missing behavior.
- [ ] Resolve identity and pinned project dependencies, then enforce read policy before graph/vector/metadata retrieval. Create scoped indexes/views where the adapter cannot enforce filters natively; never retrieve unauthorized candidates then merely remove them after generation.
- [ ] Plan retrieval stores, fuse and deduplicate authorized evidence, rank results, and package citations plus profile/product/project/model versions. Mark implementation overrides explicitly; preserve unresolved contradictions.
- [ ] Generate the final Gemini answer only from authorized approved context. With no approved context, return an explicit insufficient-knowledge response rather than a Gemini-only fallback.
- [ ] Test cross-owner read grants, forbidden profile traversal, version mixing, central exploration attribution, forged scope parameters, stale generations, citations and prompt injection in source text.
- [ ] Commit as `feat: retrieve approved version-scoped knowledge with citations`.

**Exit:** Answers and graph views share the same governance boundary.

### Task 8 — Angular administration and review experience

**Files:** `frontend/src/app/{core,profiles,models,review,graph,ask,activity}/`, `frontend/e2e/owner-review.spec.ts`, `deploy/Dockerfile.ui`.

**Contract:** Angular routes `/profiles`, `/profiles/:id/versions`, `/models`, `/review`, `/graph`, `/ask`, `/activity`; generated typed API models reflect the backend schemas.

- [ ] Add browser acceptance assertions:
  ```typescript
  await ownerPage.getByRole('link', {name: 'Review Inbox'}).click();
  await expect(ownerPage.getByText('Draft')).toBeVisible();
  await ownerPage.getByRole('button', {name: 'Approve entity', exact: true}).click();
  await expect(ownerPage.getByText('Approved — awaiting publication')).toBeVisible();
  ```
- [ ] Run `cd frontend && npx playwright test e2e/owner-review.spec.ts`; capture failing behavior before pages exist.
- [ ] Build Knowledge AI navigation, profile/version/dependency forms, model definition editor, evidence pane, candidate revision comparison and explicit selection review. Show endpoint blockers and publication failure/retry states.
- [ ] Build the published central graph with profile/version filters, Ask with pinned context and citations, and audit/activity pages. Draft preview must have explicit labeling and cannot be selected as ordinary answer context.
- [ ] Test owner/contributor/reader UI flows, keyboard use, empty states, stale revision conflict handling and refresh persistence. UI hiding complements server-side authorization.
- [ ] Commit as `feat: add Knowledge AI administration and review interface`.

**Exit:** A user can complete the governed flow without direct engine access.

### Task 9 — release snapshots, source changes and operating proof

**Files:** `profiles/service.py`, `ingestion/sources.py`, `publication/worker.py`, `tests/integration/test_release_snapshot.py`, `tests/integration/test_source_change_proposal.py`, `scripts/verify-stage1.sh`, `docs/runbooks/{local-setup,backup-restore}.md`.

**Contract:** `release_version(actor, version_id, generation_id) -> ReleaseSnapshot`; `propose_source_change(actor, source_id, revision_id, change_kind) -> ChangeProposal`. Released snapshots are immutable; mutable authoring occurs in a successor version.

- [ ] Test pinned releases and change proposals:
  ```python
  def test_new_product_release_preserves_existing_project_snapshot(releases, project):
      before = releases.snapshot(project.version_id)
      releases.create_product_successor()
      assert releases.snapshot(project.version_id) == before
  ```
- [ ] Run `uv run pytest tests/integration/test_release_snapshot.py tests/integration/test_source_change_proposal.py -q`; observe failures.
- [ ] Implement release manifests including published candidate revisions, knowledge-model revision and product dependency pins. Exclude unresolved drafts explicitly. Block release if included facts are not published.
- [ ] Treat source updates/deletions as owner-reviewed change proposals. Display affected facts as source-change pending; do not silently remove/modify released snapshots. Stop claiming a fact is current without showing its stale-source condition. Detailed automated reconciliation remains Stage 2.
- [ ] Add operational counts/statuses for pending/rejected/duplicate candidates, extraction/embedding/publication failures and processing duration. Create backup/restore instructions covering PostgreSQL, sources and active generation manifests.
- [ ] Verify upload -> draft -> owner review -> publication -> scoped graph -> cited answer, wrong-owner refusal, relation blockers, failure recovery, release pins and Docker restart persistence. Run API integration/security tests and Angular browser tests once the final implementation passes focused tests.
- [ ] Commit as `feat: complete governed local Knowledge AI release`.

**Exit:** Stage 1 is complete only after the entire governed path and restart recovery are demonstrated.

## Later-stage plans

These stages have independent implementation plans after Stage 1 acceptance; they are not required to begin the governed local foundation.

| Stage | Deliverables | Required acceptance |
|---|---|---|
| 2: Refinement | Better discovery scoring, resolver suggestions, model diffs, incremental indexing, deletion reconciliation, evolution suggestions, policy exceptions, cost/growth metrics | Suggestions remain drafts; migrations retain provenance; incremental changes match a verified full rebuild; released snapshots remain reproducible |
| 3: Connectors | SharePoint, ADO, Git, Jira, then requested enterprise systems | Each adapter supplies stable source/revision IDs, normalized provenance/access policy, retry-safe synchronization and change/deletion events; every candidate follows owner approval |
| 4: Enterprise | APIM/SSO, AKS/ACR, Service Bus/Functions, Logic Apps, Key Vault, Azure storage/search/graph adapters, SDK/MCP, agents, telemetry and private networking | Identity and policy parity, no public engine access, authorized context parity, backup/recovery proof, approved resource/budget configuration |

Do not prebuild connectors to demonstrate architecture alignment. The manual adapter proves the common source contract first.

## Self-review and implementation start

- [ ] Map every Stage 1 requirement to a task and acceptance test.
- [ ] Confirm auth and review checks exist on all mutation paths, including retries and administrative operations.
- [ ] Confirm draft source passages cannot enter published retrieval.
- [ ] Confirm all version concepts and storage adapters have explicit identities/contracts.
- [ ] Confirm failures leave the last verified generation active.
- [ ] Begin Task 1 only when implementation is requested; this repository currently contains planning documents, not completed application code.
