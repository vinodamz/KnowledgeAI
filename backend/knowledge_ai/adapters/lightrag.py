"""Pinned internal LightRAG SDK. Every generation/version gets a fresh workspace.

The undirected engine represents a relation as source--source-port--target-port--target.
Distinct ports preserve type, direction, parallel relations and self loops. Only
exact approved fact payloads and evidence excerpts enter the engine, never source chunks.
"""
import asyncio
import base64
import os
import hashlib
import importlib.metadata
import json
import logging
from pathlib import Path
from uuid import UUID
import httpx
import numpy as np
from knowledge_ai.publication.builder import canonical, digest, validate_closure


def stable_id(version_id, candidate_id, revision):
    return f'ka:{version_id}:{candidate_id}:{revision}'


def representation(facts):
    entities, relations, chunks = [], [], []
    for fact in facts:
        fid = stable_id(fact['target_version_id'], fact['candidate_id'], fact['revision'])
        # Attribution in content prevents collision of equal excerpts from different facts.
        content = canonical(fact)
        chunks.append({'source_id': fid, 'content': content, 'file_path': f"approved_{fact['source_revision_id']}_{fact['candidate_id']}_{fact['revision']}.json"})
        common = {'description': content, 'source_id': fid, 'file_path': chunks[-1]['file_path']}
        if fact['kind'] == 'entity':
            entities.append(dict(common, entity_name=fid, entity_type=fact['payload']['type_id']))
        else:
            ports = [fid + ':source', fid + ':target']
            for side, port in zip(('source', 'target'), ports):
                entities.append(dict(common, entity_name=port, entity_type=f"relation_{side}:{fact['payload']['type_id']}"))
            source = stable_id(fact['target_version_id'], fact['payload']['source_candidate_id'], fact['payload']['source_candidate_revision'])
            target = stable_id(fact['target_version_id'], fact['payload']['target_candidate_id'], fact['payload']['target_candidate_revision'])
            for a, b, role in ((source, ports[0], 'source'), (ports[0], ports[1], 'typed_relation'), (ports[1], target, 'target')):
                relations.append(dict(common, src_id=a, tgt_id=b, keywords=role, weight=1.0))
    return {'entities': entities, 'relationships': relations, 'chunks': chunks}


def files_digest(directory):
    entries = {}
    for path in sorted(Path(directory).rglob('*')):
        if path.is_file() and path.name != 'verified.json':
            entries[str(path.relative_to(directory))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest(entries)


def embedding_identity(settings):
    """Public vector compatibility identity; endpoint URLs/credentials are excluded."""
    model = settings.embedding_model
    if not isinstance(model, str) or not model.strip() or model != model.strip():
        raise ValueError('Invalid embedding model identity')
    return {'provider': 'ollama', 'model': model, 'dimensions': settings.embedding_dimensions}


class LightRAGAdapter:
    def __init__(self, settings, *, embedding=None, fault=None):
        if importlib.metadata.version('lightrag-hku') != '1.5.4':
            raise RuntimeError('Only verified LightRAG SDK 1.5.4 is supported')
        # SDK errors can interpolate evidence/provider responses. The worker emits
        # sanitized durable failure status instead of forwarding those raw logs.
        logging.getLogger('lightrag').disabled = True
        logging.getLogger('nano-vectordb').disabled = True
        self.settings = settings
        embedding_identity(settings)
        self.root = Path(settings.publication_directory)
        self.embedding = embedding or self._ollama
        self.fault = fault or (lambda boundary: None)

    async def _ollama(self, texts):
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(self.settings.embedding_base_url.rstrip('/') + '/api/embed', json={'model': self.settings.embedding_model, 'input': texts})
            response.raise_for_status()
            values = np.asarray(response.json()['embeddings'], dtype=np.float32)
            if values.shape != (len(texts), self.settings.embedding_dimensions) or not np.isfinite(values).all():
                raise ValueError('Embedding dimension or finite-value verification failed')
            return values

    def build_generation(self, generation_id, manifest):
        validate_closure(manifest)
        return asyncio.run(self._build(generation_id, manifest))

    def build(self, generation_id, approved_entities, approved_relations, approved_evidence):
        # Port compatibility: each entity/relation is a full registry manifest fact.
        facts = list(approved_entities) + list(approved_relations)
        if approved_evidence != [f['evidence'] for f in facts]:
            raise ValueError('Evidence differs from exact registry facts')
        report = self.build_generation(generation_id, {'schema': 1, 'representation': 'typed-directed-relation-ports-v1', 'facts': facts})
        from knowledge_ai.adapters.index import IndexReport
        return IndexReport(generation_id, len(approved_entities), len(approved_relations), len(facts), True, report)

    async def _build(self, generation_id, manifest):
        from lightrag import LightRAG
        from lightrag.utils import EmbeddingFunc
        directory = self.root / str(UUID(str(generation_id)))
        # Retries always allocate another generation. Partial workspaces cannot be resumed.
        directory.mkdir(parents=True, exist_ok=False)
        partitions = {}
        versions = sorted({f['target_version_id'] for f in manifest['facts']})
        for version in versions:
            facts = [f for f in manifest['facts'] if f['target_version_id'] == version]
            workspace = f'g{generation_id}_v{version}'
            rag = LightRAG(working_dir=str(directory), workspace=workspace,
                           embedding_func=EmbeddingFunc(embedding_dim=self.settings.embedding_dimensions, max_token_size=8192, func=self.embedding),
                           llm_model_func=self._no_llm, auto_manage_storages_states=False)
            await rag.initialize_storages()
            kg = representation(facts)
            # Hook actual SDK write/persistence boundaries; fault tests never substitute the engine.
            self._instrument(rag)
            try:
                self.fault('before_insert')
                await rag.ainsert_custom_kg(kg)
                self.fault('after_insert')
                counts = await self._verify(rag, kg)
                self.fault('after_verify')
            finally:
                await rag.finalize_storages()
            partition_dir = directory / workspace
            partitions[version] = {'workspace': workspace, 'profile_id': facts[0]['target_profile_id'],
                                   'counts': counts, 'digest': files_digest(partition_dir)}
        report = {'manifest_digest': digest(manifest), 'partitions': partitions, 'verified': True,
                  'embedding': embedding_identity(self.settings)}
        self.fault('before_seal')
        # Persist all completed files and the seal before the registry can activate.
        for path in directory.rglob('*'):
            if path.is_file():
                with path.open('rb') as handle: os.fsync(handle.fileno())
        with (directory / 'verified.json').open('w') as handle:
            handle.write(canonical(report)); handle.flush(); os.fsync(handle.fileno())
        for path in [p for p in directory.rglob('*') if p.is_dir()] + [directory, self.root]:
            fd = os.open(path, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        self.fault('after_seal')
        return report

    @staticmethod
    async def _no_llm(*args, **kwargs):
        raise RuntimeError('Publication cannot invoke extraction or generation')

    def _instrument(self, rag):
        for label, store, methods in (
            ('chunks', rag.text_chunks, ('upsert', 'index_done_callback')),
            ('chunk_vectors', rag.chunks_vdb, ('upsert', 'index_done_callback')),
            ('nodes', rag.chunk_entity_relation_graph, ('upsert_nodes_batch',)),
            ('edges', rag.chunk_entity_relation_graph, ('upsert_edges_batch', 'index_done_callback')),
            ('entity_vectors', rag.entities_vdb, ('upsert', 'index_done_callback')),
            ('relation_vectors', rag.relationships_vdb, ('upsert', 'index_done_callback')),
        ):
            for method in methods:
                original = getattr(store, method)
                async def wrapped(*args, _original=original, _label=label, _method=method, **kwargs):
                    self.fault(f'before_{_label}_{_method}')
                    result = await _original(*args, **kwargs)
                    self.fault(f'after_{_label}_{_method}')
                    return result
                setattr(store, method, wrapped)

    async def _verify(self, rag, kg):
        from lightrag.utils import compute_mdhash_id
        ch = {compute_mdhash_id(c['content'], prefix='chunk-'): c for c in kg['chunks']}
        mapping = {c['source_id']: cid for cid, c in ch.items()}
        nodes = {n['id']: n for n in await rag.chunk_entity_relation_graph.get_all_nodes()}
        edges = {tuple(sorted((e['source'], e['target']))): e for e in await rag.chunk_entity_relation_graph.get_all_edges()}
        expected_nodes = {n['entity_name']: n for n in kg['entities']}
        expected_edges = {tuple(sorted((e['src_id'], e['tgt_id']))): e for e in kg['relationships']}
        if set(nodes) != set(expected_nodes) or set(edges) != set(expected_edges):
            raise ValueError('Graph count or endpoint mismatch')
        for key, expected in expected_nodes.items():
            for field in ('description', 'entity_type', 'file_path'):
                if nodes[key].get(field) != expected[field]: raise ValueError('Graph node payload mismatch')
            if nodes[key]['source_id'] != mapping[expected['source_id']]: raise ValueError('Graph evidence mismatch')
        for key, expected in expected_edges.items():
            for field in ('description', 'keywords', 'file_path', 'weight'):
                if edges[key].get(field) != expected[field]: raise ValueError('Graph relation payload mismatch')
            if edges[key]['source_id'] != mapping[expected['source_id']]: raise ValueError('Graph relation evidence mismatch')
        import networkx as nx
        persisted_graph = nx.read_graphml(rag.chunk_entity_relation_graph._graphml_xml_file)
        if set(persisted_graph.nodes) != set(nodes) or {tuple(sorted(x)) for x in persisted_graph.edges} != set(edges):
            raise ValueError('Persisted graph inventory mismatch')
        for key, value in nodes.items():
            if dict(persisted_graph.nodes[key]) != {k:v for k,v in value.items() if k != 'id'}:
                raise ValueError('Persisted graph payload mismatch')
        for key, value in edges.items():
            if dict(persisted_graph.edges[key]) != {k:v for k,v in value.items() if k not in {'source','target'}}:
                raise ValueError('Persisted graph edge mismatch')
        self.fault('verified_graph')
        # Verify persisted KV inventory as well as public SDK reads (extra chunks must fail).
        chunk_file = Path(rag.text_chunks._file_name)
        persisted = json.loads(chunk_file.read_text())
        if set(persisted) != set(ch): raise ValueError('Approved chunk inventory mismatch')
        for cid, expected in ch.items():
            actual = persisted[cid]
            if not isinstance(actual, dict) or any(actual.get(k) != expected[k] for k in ('content', 'file_path', 'source_id')):
                raise ValueError('Persisted approved evidence payload mismatch')
        actual_chunks = await rag.text_chunks.get_by_ids(list(ch))
        for (cid, expected), actual in zip(ch.items(), actual_chunks):
            if not actual or any(actual.get(k) != expected[k] for k in ('content', 'file_path', 'source_id')):
                raise ValueError('Approved evidence payload mismatch')
        self.fault('verified_chunks')
        expected_vectors = (
            (rag.entities_vdb, {compute_mdhash_id(k, prefix='ent-'): {'entity_name': k, 'content': k+'\n'+v['description'], 'source_id': mapping[v['source_id']], 'file_path': v['file_path']} for k,v in expected_nodes.items()}),
            (rag.relationships_vdb, {compute_mdhash_id(a+b, prefix='rel-'): {'src_id': a, 'tgt_id': b, 'source_id': mapping[v['source_id']], 'content': f"{v['keywords']}\t{a}\n{b}\n{v['description']}", 'file_path':v['file_path']} for (a,b),v in expected_edges.items()}),
            (rag.chunks_vdb, {cid: {'content': v['content'], 'full_doc_id':v['source_id'], 'file_path': v['file_path']} for cid,v in ch.items()}),
        )
        for store, expected in expected_vectors:
            storage = await store.client_storage
            actual = {row['__id__']: row for row in storage['data']}
            if set(actual) != set(expected): raise ValueError('Vector inventory mismatch')
            for key, value in expected.items():
                if any(actual[key].get(k) != v for k,v in value.items()): raise ValueError('Vector payload mismatch')
            disk = json.loads(Path(store._client_file_name).read_text())
            disk_records = {row['__id__']: row for row in disk['data']}
            if disk_records != actual or disk['embedding_dim'] != self.settings.embedding_dimensions:
                raise ValueError('Persisted vector records mismatch')
            matrix = np.asarray(storage['matrix'])
            disk_matrix = np.frombuffer(base64.b64decode(disk['matrix']), dtype=np.float32).reshape(-1, disk['embedding_dim'])
            if not np.array_equal(disk_matrix, matrix): raise ValueError('Persisted vector matrix mismatch')
            if expected and (matrix.shape != (len(expected), self.settings.embedding_dimensions) or not np.isfinite(matrix).all() or not (np.linalg.norm(matrix, axis=1) > 0).all()):
                raise ValueError('Invalid embedding vectors')
        self.fault('verified_vectors')
        return {'nodes': len(nodes), 'edges': len(edges), 'entity_vectors': len(expected_nodes), 'relation_vectors': len(expected_edges), 'chunks': len(ch), 'chunk_vectors': len(ch)}

    def verify_seal(self, generation_id, report):
        if report.get('embedding') != embedding_identity(self.settings):
            raise ValueError('Embedding configuration differs from sealed generation')
        directory = self.root / str(UUID(str(generation_id)))
        if json.loads((directory / 'verified.json').read_text()) != report: raise ValueError('Index seal mismatch')
        for partition in report['partitions'].values():
            if files_digest(directory / partition['workspace']) != partition['digest']: raise ValueError('Verified partition changed')

class SealedPartitionReader:
    """Read official SDK persistence directly. Never initialize or flush LightRAG."""
    def read(self, partition, dimensions):
        import networkx as nx
        from fastapi import HTTPException
        try:
            root = partition.directory / partition.workspace
            chunks = json.loads((root / 'kv_store_text_chunks.json').read_text())
            graph = nx.read_graphml(root / 'graph_chunk_entity_relation.graphml')
            vectors = {}
            for namespace in ('entities', 'relationships', 'chunks'):
                data = json.loads((root / f'vdb_{namespace}.json').read_text())
                matrix = np.frombuffer(base64.b64decode(data['matrix'], validate=True), dtype=np.float32).reshape(len(data['data']), dimensions)
                if data['embedding_dim'] != dimensions or not np.isfinite(matrix).all() or (len(matrix) and (not np.isfinite(np.linalg.norm(matrix, axis=1)).all() or not (np.linalg.norm(matrix, axis=1) > 0).all())):
                    raise ValueError('Invalid vector matrix')
                vectors[namespace] = (data['data'], matrix)
            return chunks, graph, vectors
        except Exception:
            raise HTTPException(503, 'Published index cannot be read') from None

class QueryEmbeddingProvider:
    """Bound both embedding response bytes and overall call duration."""
    def __init__(self, settings, *, transport=None, deadline=60):
        self.settings, self.transport, self.deadline = settings, transport, deadline

    async def _request(self, query):
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10), transport=self.transport, follow_redirects=False) as client:
            async with client.stream('POST', self.settings.embedding_base_url.rstrip('/') + '/api/embed', json={'model': self.settings.embedding_model, 'input': [query]}, headers={'accept-encoding': 'identity'}) as response:
                if response.status_code != 200 or response.headers.get('content-encoding', 'identity') != 'identity': raise ValueError('Embedding request failed')
                content = bytearray()
                async for chunk in response.aiter_raw(chunk_size=8192):
                    if len(content) + len(chunk) > 500_000: raise ValueError('Embedding response exceeds limit')
                    content.extend(chunk)
                return json.loads(content)['embeddings']

    def embed(self, query):
        from fastapi import HTTPException
        async def bounded(): return await asyncio.wait_for(self._request(query), self.deadline)
        try:
            values = np.asarray(asyncio.run(bounded()), dtype=np.float32)
            if values.shape != (1, self.settings.embedding_dimensions) or not np.isfinite(values).all() or not np.isfinite(np.linalg.norm(values[0])) or not np.linalg.norm(values[0]) > 0: raise ValueError('Invalid query embedding')
            return values[0]
        except Exception:
            raise HTTPException(503, 'Query embedding unavailable or incompatible') from None
