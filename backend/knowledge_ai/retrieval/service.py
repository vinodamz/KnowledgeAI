"""Fusion over individually authorized physical version partitions only."""
import json
import re
from uuid import UUID
import numpy as np
from fastapi import HTTPException
from sqlalchemy import select
from knowledge_ai.adapters.lightrag import SealedPartitionReader, QueryEmbeddingProvider, stable_id
from knowledge_ai.publication.reader import verified_partition
from knowledge_ai.publication.models import PublicationGeneration
from knowledge_ai.publication.builder import canonical
from knowledge_ai.profiles.models import KnowledgeVersion, Profile
from knowledge_ai.ingestion.sources import SourceRevision
from knowledge_ai.review.models import ReviewDecision
from .planner import validate_context
from .contracts import KnowledgeContext, Answer
from .answer import GeminiAnswerProvider, verify_answer

INSUFFICIENT = 'Insufficient approved knowledge to answer this question.'

def fact_id(f): return stable_id(f['target_version_id'], f['candidate_id'], f['revision'])

def claim_text(f, names=None):
    # Exact approved payload only. Supporting excerpts can contain incidental
    # unreviewed facts, so they are citations, NEVER answer-provider context.
    p = f['payload']
    if f['kind'] == 'entity':
        attributes = '; '.join(f'{key} = {value if isinstance(value, (str, int, float, bool)) else canonical(value)}' for key, value in p.get('attributes', {}).items())
        return p.get('name', '') + (': ' + attributes if attributes else '') + ('. ' + p['description'] if p.get('description') else '')
    names = names or {}
    source = stable_id(f['target_version_id'], p['source_candidate_id'], p['source_candidate_revision'])
    target = stable_id(f['target_version_id'], p['target_candidate_id'], p['target_candidate_revision'])
    return f"{names.get(source, source)} {p.get('type_name', p['type_id'])} {names.get(target, target)}" + ('. ' + p['description'] if p.get('description') else '')

class RetrievalService:
    def __init__(self, db, actor, settings, *, embedding=None, answer_provider=None, reader=None):
        self.db, self.actor, self.settings = db, actor, settings
        self.embedding = embedding or QueryEmbeddingProvider(settings)
        self.answer_provider = answer_provider or GeminiAnswerProvider(settings)
        self.reader = reader or SealedPartitionReader()
        self._names = {}

    def partitions(self, context):
        actor = validate_context(self.db, self.actor, context)
        if context.generation_id is None: return []
        # All grants/version rules were validated above before the first file access.
        partitions = [verified_partition(self.db, actor, self.settings, context.generation_id, v) for v in context.allowed_version_ids]
        partitions = [p for p in partitions if p]
        if partitions:
            g = self.db.get(PublicationGeneration, context.generation_id)
            try:
                seal = json.loads((partitions[0].directory / 'verified.json').read_text())
                if seal != g.verification: raise ValueError('Seal changed')
            except Exception: raise HTTPException(503, 'Publication seal unavailable or changed') from None
        return partitions

    def citation(self, fact):
        version = self.db.get(KnowledgeVersion, UUID(fact['target_version_id']))
        profile = self.db.get(Profile, version.profile_id)
        source = self.db.get(SourceRevision, UUID(fact['source_revision_id']))
        decision = self.db.scalar(select(ReviewDecision).where(ReviewDecision.candidate_id == UUID(fact['candidate_id']), ReviewDecision.candidate_revision == fact['revision'], ReviewDecision.decision == 'approve', ReviewDecision.checksum == fact['checksum']).order_by(ReviewDecision.created_at.desc(), ReviewDecision.id.desc()).limit(1))
        if not source or not decision: raise HTTPException(503, 'Published attribution unavailable')
        return {'id':fact_id(fact), 'candidate_id':fact['candidate_id'], 'candidate_revision':fact['revision'],
                'profile_id':str(profile.id), 'profile_kind':profile.kind, 'profile_name':profile.name,
                'version_id':str(version.id), 'version_label':version.label, 'version_status':version.status,
                'product_version_id':str(version.id) if profile.kind == 'product' else None,
                'project_version_id':str(version.id) if profile.kind == 'project' else None,
                'source_profile_id':fact['source_profile_id'], 'source_version_id':fact['source_version_id'],
                'model_revision_id':fact['model_revision_id'], 'source_id':str(source.source_id),
                'source_revision_id':fact['source_revision_id'], 'provenance':source.provenance,
                'reviewer_id':str(decision.actor_id), 'review_decision_id':str(decision.id),
                'approval_checksum':fact['checksum'], 'evidence':fact['evidence']}

    def package(self, context, facts, scores=None):
        items = []
        for f in facts:
            items.append({'id':fact_id(f), 'approved':True, 'version_id':f['target_version_id'], 'kind':f['kind'],
                          'payload':f['payload'], 'claim':claim_text(f, self._names), 'score':(scores or {}).get(fact_id(f), 0),
                          'canonical_concept_id':f['payload'].get('canonical_concept_id'),
                          'attribution':self.citation(f)})
        # Do not resolve conflicting values. Preserve both exact cited payloads,
        # while exposing product/project deviations as explicit implementation overrides.
        groups = {}
        for item in items:
            p = item['payload']; key = p.get('canonical_concept_id') or (p.get('type_name'), p.get('name'))
            if item['kind'] == 'entity': groups.setdefault(str(key), []).append(item)
        conflicts, overrides = [], []
        for group in groups.values():
            if len({canonical({'attributes':x['payload'].get('attributes', {}), 'description':x['payload'].get('description', '')}) for x in group}) > 1:
                ids = [x['id'] for x in group]; conflicts.append({'fact_ids':ids, 'status':'unresolved'})
                if {x['attribution']['profile_kind'] for x in group} == {'product','project'}:
                    overrides.append({'fact_ids':ids, 'status':'implementation_override', 'resolution':'preserve both cited values'})
        return KnowledgeContext(tuple(items), tuple(x['attribution'] for x in items), tuple(sorted({f['model_revision_id'] for f in facts})),
                                {'generation_id':str(context.generation_id) if context.generation_id else None,
                                 'profile_id':str(context.profile_id), 'knowledge_version_id':str(context.knowledge_version_id),
                                 'allowed_version_ids':list(map(str, context.allowed_version_ids)), 'approved_only':True,
                                 'conflicts':conflicts, 'implementation_overrides':overrides})

    def retrieve(self, context, query):
        if not isinstance(query, str) or not query.strip() or len(query) > 4000: raise HTTPException(422, 'Query must contain 1 to 4000 characters')
        partitions = self.partitions(context)
        if not partitions: return self.package(context, [])
        loaded = [(p, self.reader.read(p, self.settings.embedding_dimensions)) for p in partitions]
        self._names = {fact_id(f):f['payload']['name'] for p in partitions for f in p.facts if f['kind'] == 'entity'}
        q = np.asarray(self.embedding.embed(query), dtype=np.float32)
        if q.shape != (self.settings.embedding_dimensions,) or not np.isfinite(q).all() or not np.isfinite(np.linalg.norm(q)) or not np.linalg.norm(q) > 0:
            raise HTTPException(503, 'Query embedding unavailable or incompatible')
        q = q / np.linalg.norm(q)
        terms = set(re.findall(r'\w+', query.lower()))
        scores, facts = {}, {}
        for partition, (chunks, graph, vectors) in loaded:
            local = {fact_id(f):f for f in partition.facts}
            mapping = {cid:fact_id(json.loads(row['content'])) for cid, row in chunks.items()}
            for fid, f in local.items():
                facts[fid] = f
                words = set(re.findall(r'\w+', canonical(f['payload']).lower()))
                scores[fid] = len(words & terms) / max(1, len(terms))
            for namespace, (rows, matrix) in vectors.items():
                cosine = matrix @ q / np.linalg.norm(matrix, axis=1)
                for index in np.argsort(-cosine)[:30]:
                    row = rows[int(index)]
                    cid = row['__id__'] if namespace == 'chunks' else row['source_id']
                    if cid not in mapping or mapping[cid] not in local: raise HTTPException(503, 'Published vector attribution mismatch')
                    fid = mapping[cid]
                    scores[fid] += max(0, float(cosine[index])) / 3
            # Graph expansion uses approved reified neighborhoods only; public graph
            # exposes original typed/directed facts, never engine port edges.
            seeds = sorted(local, key=lambda x:scores[x], reverse=True)[:8]
            for fid in seeds:
                for node in (fid, fid + ':source', fid + ':target'):
                    if node not in graph: continue
                    for neighbor in graph.neighbors(node):
                        cid = graph.nodes[neighbor].get('source_id')
                        if cid in mapping and mapping[cid] in local: scores[mapping[cid]] += 0.1
        ranked = sorted(facts, key=lambda x:(-scores[x], x))
        # Keep comparison groups intact: ranking must not hide a lower-ranked
        # conflicting implementation/product value behind an arbitrary top-k cut.
        groups = {}
        for fid in ranked:
            f = facts[fid]; p = f['payload']
            key = ('entity', p.get('canonical_concept_id') or (p.get('type_name'), p.get('name'))) if f['kind'] == 'entity' else ('relation', fid)
            groups.setdefault(str(key), []).append(fid)
        selected, length = [], 0
        for group in groups.values():
            size = sum(len(claim_text(facts[fid], self._names)) for fid in group)
            if len(selected) + len(group) > 30 or length + size > 40000: continue
            selected.extend(facts[fid] for fid in group); length += size
        return self.package(context, selected, scores)

    def answer(self, context, query):
        knowledge = self.retrieve(context, query)
        if not knowledge.items: return Answer('insufficient_knowledge', INSUFFICIENT, (), knowledge)
        claims = [{'citation_id':i['id'], 'text':i['claim']} for i in knowledge.items]
        selected = verify_answer(self.answer_provider.answer(query, claims), claims)
        if not selected: return Answer('insufficient_knowledge', INSUFFICIENT, (), knowledge)
        # Include every conflicting counterpart when one selected claim needs a
        # comparison note; all additions are exact approved claims, not LLM facts.
        for conflict in knowledge.policy_context['conflicts']:
            if set(conflict['fact_ids']) & set(selected):
                selected.extend(c for c in conflict['fact_ids'] if c not in selected)
        by_id = {c['citation_id']:c['text'] for c in claims}
        notes = []
        for conflict in knowledge.policy_context['conflicts']:
            if set(conflict['fact_ids']) & set(selected): notes.append('Conflicting approved values remain unresolved; see their cited versions.')
        for override in knowledge.policy_context['implementation_overrides']:
            if set(override['fact_ids']) & set(selected): notes.append('Implementation override: project and product values differ; both remain separately attributed.')
        text = '\n'.join(f"{by_id[c]} [{c}]" for c in selected)
        if notes: text += '\n' + '\n'.join(dict.fromkeys(notes))
        return Answer('answered', text, tuple(c for c in knowledge.citations if c['id'] in selected), knowledge)

    def graph(self, context):
        partitions = self.partitions(context)
        facts = []
        for p in partitions:
            self.reader.read(p, self.settings.embedding_dimensions)
            facts.extend(p.facts)
        if len(facts) > 2000: raise HTTPException(422, 'Graph is too large; choose a narrower version context')
        self._names = {fact_id(f):f['payload']['name'] for f in facts if f['kind'] == 'entity'}
        knowledge = self.package(context, facts)
        nodes = [i for i in knowledge.items if i['kind'] == 'entity']
        edges = []
        for item in knowledge.items:
            if item['kind'] != 'relation': continue
            p = item['payload']; version = item['version_id']
            edges.append(dict(item, source=stable_id(version, p['source_candidate_id'], p['source_candidate_revision']),
                              target=stable_id(version, p['target_candidate_id'], p['target_candidate_revision']), type_id=p['type_id'], directed=True))
        return {'nodes':nodes, 'edges':edges, 'citations':knowledge.citations, 'policy_context':knowledge.policy_context}
