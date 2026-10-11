# Publication generations and recovery

PostgreSQL is authoritative. Approval alone does not publish a fact. A generation is
visible only after its complete scoped indexes pass verification and the central
`active_publication` pointer changes in the same transaction as job success.

## Request and observe

An assigned owner sends `POST /api/publications` with `profile_id`, `version_id`,
`idempotency_key`, and `candidates: [{candidate_id, revision}]` (1–200 unique pairs).
Only that selection is added; unrelated approvals are never swept into publication.
The response is a durable job, not an assertion that publication has completed.

Use `GET /api/publications/{id}` or `GET /api/publications?version_id=...` (latest100).
States are `queued`, `building`, `published`, and `publication_failed`. Candidate
`published` and `active_generation_id` are computed from the current manifest.
`GET /api/versions/{id}/publication` returns the scoped active manifest, including
original typed/directed relations and exact approved evidence attribution.
Ordinary readers cannot inspect authoring draft versions or unpublished job selections.

## Failure and retry

1. Check the durable failure status and the worker's sanitized failure category.
   Index/provider errors intentionally omit source text, response bodies and secrets.
2. Restore PostgreSQL, the publication volume or local Ollama as appropriate.
   Settings are `KNOWLEDGE_AI_PUBLICATION_DIRECTORY`, `KNOWLEDGE_AI_EMBEDDING_BASE_URL`,
   `KNOWLEDGE_AI_EMBEDDING_MODEL`, and `KNOWLEDGE_AI_EMBEDDING_DIMENSIONS` (default768).
   Docker uses `http://host.docker.internal:11434`; native local runs use
   `http://127.0.0.1:11434`. The default model is `nomic-embed-text`.
3. The original requester may `POST /api/publications/{id}/retry`. If the selected
   revision, approval, ownership or scope changed, review the latest revision and
   submit a new request with a new idempotency key. A new owner submits their own job.
4. Verify `published` and the active generation after the retry. Every attempt
   allocates a fresh generation UUID/workspace; partial directories are never reused.

A PostgreSQL session advisory lock permits one publisher at a time across processes.
It remains held while expensive index work runs outside registry transactions and
row locks. Process death releases it. The next worker rebuilds an interrupted
`building` job with a new generation ID, marking the old staging generation failed.
Live lock ownership, current attempt identity, checksum approvals, latest selected
revisions, assigned ownership and scope are rechecked before activation. A pointer
compare-and-swap rejects a concurrent activation. Failure after the activation commit
cannot relabel the active job as failed.

Old approved exact revisions stay active while edits are pending. Retained facts
are copied from the verified prior manifest, without applying latest-draft readiness
to them. Old endpoint revisions remain when retained relations need those revisions.
Releases and successor inheritance are separate Task9 contracts; the manifest already
separates source profile/version attribution from target logical profile/version.

## Physical layout and verification

`<publication_directory>/<generation_uuid>/g<generation_uuid>_v<version_uuid>/`
contains official pinned `lightrag-hku==1.5.4` JSON KV, NanoVectorDB and NetworkX stores.
Each version has a distinct physical graph/vector/chunk index. One central registry
manifest presents them as a single logical approved graph. The API container mounts
the publication volume read-only; only the internal worker writes it.

Stable node IDs contain target version, candidate UUID and revision, never just a
label. Because LightRAG's graph is undirected, a relation becomes
`source — source-port — target-port — target`. The two ports identify the exact
relation, type and direction, preserving parallel relations and self loops. The
registry manifest remains the original user-facing relation representation.

Each indexed chunk is one approved fact with its approved excerpt spans and exact
source/model/candidate attribution. Original source chunks/documents are not inserted.
Verification compares every graph node/edge, vector metadata/content, chunk payload,
endpoint and evidence reference, and exact inventory counts against the manifest.
It independently checks persisted GraphML, persisted KV and decoded persisted vector
matrices (shape, finite/nonzero values, exact match), then records per-partition file
SHA256 digests and the canonical manifest digest. Completed files and seal are fsynced.
Persisted chunk content, file attribution and source IDs are compared directly to the
manifest-derived approved chunks independently of SDK memory. The sealed report records
embedding provider (`ollama`), model and dimensions without endpoint URLs or credentials.
The seal is checked again immediately before the registry activation transaction.

## Retrieval integration (Task7)

Call `publication.reader.pin_generation(db)` once per request, then
`verified_partition(db, actor, settings, generation_id, version_id)` for each explicitly
authorized version. This verifies authorization before touching any engine files and
refuses staging/verified/failed generations. Draft versions require owner/contributor/
admin access. Retired generations support requests already pinned to an older snapshot.
The function returns only that physical partition and its exact approved facts.
Reader resolution rejects a different embedding provider, model or dimension setting
before any index file access. Task7 must use the sealed identity for query embeddings;
changing models requires rebuilding a generation, even when dimensions stay equal.

Read sealed files directly; do not initialize/finalize a LightRAG instance for queries,
write response caches, migrate stores, or retrieve globally and filter afterward.
No ordinary request may select arbitrary retired generations; the server pins them.
Dependency pins do not themselves grant access. Missing/corrupt partitions fail closed.
Task7 supplies retrieval/ranking and Task9 supplies immutable released version snapshots.

## Storage retention

Do not delete active or retired generations while requests/releases may reference them.
Failed staging directories are unreachable but retained for diagnosis; retries do not
reuse them. Automatic garbage collection, leases for long-running reads and release-aware
retention are not implemented here. Plan explicit retention after Task9 establishes
release references. No prototype LightRAG data is imported or approved automatically.
