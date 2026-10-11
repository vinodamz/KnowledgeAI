# Approved retrieval and cited answers

The API reads sealed official LightRAG 1.5.4 graph/KV/NanoVectorDB files directly,
without constructing LightRAG, modifying caches, initializing stores or flushing.
Each request pins one server-resolved central generation. Public clients cannot
supply generation, role, grants or allowed-version overrides. Retired generations
are available only through previously resolved trusted internal contexts.

`GET /api/available-contexts` lists readable profile/version choices.
`POST /api/ask` accepts `{profile_id, version_id, query}` (query 1–4000 characters).
`GET /api/graph?version_ids=<UUID>&version_ids=<UUID>` requires explicit version
selection, at most20 versions and2000 graph facts. Graph returns original typed,
directed relations with exact endpoint revisions, not LightRAG's relation ports.
All endpoints use the existing authenticated session; POST also requires CSRF.

Ordinary readers see released/archived versions. Owners/contributors/admins can
query published ACTIVE facts within an authoring draft version. Unpublished draft
candidates never enter retrieval. Project queries include exact pinned product
versions, and EACH product's current grant is checked before ANY store is opened.
A revoked dependency grant refuses the entire query, rather than silently dropping
that product. Live identity, ownership and grants are reloaded in the retrieval
transaction. Public explicit version mismatches fail closed.

Generation manifests, embedding identity, partition file digests and the on-disk
seal must verify. Query embeddings use the sealed Ollama model/dimensions; byte
and overall deadline bounds, finite values, dimensions and nonzero vectors are
checked. Store corruption/provider failure returns sanitized503 and never falls
back to ungrounded generation. No approved partition means insufficient knowledge
without calling embedding or Gemini.

Fusion ranks vector/entity/relation/chunk scores, payload terms and graph
neighborhood evidence within authorized partitions. At most30 exact approved facts
and40000 claim characters reach generation. Canonical IDs and separate provenance
prevent cross-version merging. Same-name/type or canonical matches with differing
attributes/descriptions are marked unresolved; linked project/product differences
are labeled implementation overrides and both cited values are retained. These
flags are comparison aids, not automatic conflict resolution or identity merging.

Stage1 answers are deliberately extractive: Gemini selects relevant readable
approved claims. Exact citation-ID/text equality is validated, rejecting invented
citations, added text and paraphrases. This ensures unsupported output fails closed.
The answer can include deterministic conflict/override notes. Supporting source
quotes remain available in citation evidence but NEVER enter Gemini answer context:
a quote may include incidental unreviewed statements. User question and approved
claims are a JSON data envelope; instruction isolation is in systemInstruction,
with no tools or external knowledge. Free-form synthesis requires a future support
verifier and is not currently implemented.

Citations retain candidate/exact revision/checksum, actual approving reviewer and
decision, profile/kind/name, product/project version and status, model revision,
source ID/exact revision/provenance/evidence, and distinct source-vs-target version
attribution for Task9 snapshot inheritance. Release metadata will later extend this
boundary rather than making a new unscoped retrieval path.

Internal ports: `resolve_context(db, actor, profile_id, version_id)`;
`RetrievalService(db, actor, settings).retrieve(context, query)`;
`.answer(context, query)` and `.graph(context)`. Embedding, answer and sealed-reader
providers are injectable for deterministic security tests; production uses bounded
Ollama and Gemini providers.
