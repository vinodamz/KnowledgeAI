from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from knowledge_ai.review.models import Candidate
from knowledge_ai.ontology.resolver import select_match,AmbiguousConcept

class Span(BaseModel):
    model_config=ConfigDict(extra='forbid')
    chunk_id: str
    start: StrictInt
    end: StrictInt
    excerpt: str=Field(min_length=1,max_length=4000)
class Entity(BaseModel):
    model_config=ConfigDict(extra='forbid')
    key: str=Field(min_length=1,max_length=200)
    type_id: str | None
    type_name: str=Field(min_length=1,max_length=200)
    name: str=Field(min_length=1,max_length=500)
    attributes: dict=Field(default_factory=dict)
    evidence: list[Span]=Field(min_length=1,max_length=20)
class Relation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    type_id: str | None
    type_name: str=Field(min_length=1,max_length=200)
    source: str
    target: str
    evidence: list[Span]=Field(min_length=1,max_length=20)
class Output(BaseModel):
    model_config=ConfigDict(extra='forbid')
    entities: list[Entity]=Field(max_length=200)
    relations: list[Relation]=Field(max_length=400)

def validate_output(source,model,output):
    parsed=Output.model_validate(output)
    chunks={c['chunk_id']:c for c in source.chunks}
    def evidence(spans):
        result=[]
        for span in spans:
            chunk=chunks.get(span.chunk_id)
            if not chunk or not (0<=span.start<span.end<=len(chunk['text'])) or chunk['text'][span.start:span.end]!=span.excerpt:
                raise ValueError('Unverified evidence span')
            result.append({'source_revision_id':str(source.revision_id),'page':chunk['page'],'chunk_id':span.chunk_id,'start':span.start,'end':span.end,'excerpt':span.excerpt,'page_start':chunk['page_start']+span.start,'page_end':chunk['page_start']+span.end})
        return result
    types={t['id']:t for t in model['entities']}
    relations={t['id']:t for t in model['relations']}
    ids={}
    candidates=[]
    for entity in parsed.entities:
        if entity.key in ids: raise ValueError('Duplicate entity key')
        cid=uuid4(); ids[entity.key]=(cid,entity.type_id)
        definition=types.get(entity.type_id)
        if entity.type_id and not definition: raise ValueError('Invalid model type ID')
        if definition:
            allowed={a['name']:a['data_type'] for a in definition['attributes']}
            if set(entity.attributes)-set(allowed): raise ValueError('Unknown model attribute')
            for key,value in entity.attributes.items():
                expected=allowed[key]
                checks={'string':lambda x:isinstance(x,str),'text':lambda x:isinstance(x,str),'number':lambda x:type(x) in (int,float),'integer':lambda x:type(x) is int,'boolean':lambda x:type(x) is bool,'date':lambda x:isinstance(x,str),'array':lambda x:isinstance(x,list),'object':lambda x:isinstance(x,dict)}
                if expected in checks and not checks[expected](value): raise ValueError('Attribute data type mismatch')
        candidates.append(Candidate(id=cid,revision=1,source_revision_id=source.revision_id,kind='entity' if definition else 'model_suggestion',payload=entity.model_dump(exclude={'evidence','key'}) | {'suggestion_kind':'entity'} if not definition else entity.model_dump(exclude={'evidence','key'}),evidence=evidence(entity.evidence),state='pending'))
    for candidate in candidates:
        try:
            match=select_match(model.get('concepts',[]),model.get('profile_id'),candidate.payload['name'])
            candidate.payload['canonical_resolution']='matched' if match else 'unmatched'
            if match: candidate.payload['canonical_concept_id']=str(match.id)
        except AmbiguousConcept:
            candidate.payload['canonical_resolution']='ambiguous'
    for relation in parsed.relations:
        if relation.source not in ids or relation.target not in ids: raise ValueError('Unknown relation endpoint')
        definition=relations.get(relation.type_id)
        if relation.type_id and not definition: raise ValueError('Invalid relation type ID')
        src,src_type=ids[relation.source]; dst,dst_type=ids[relation.target]
        if definition and (src_type!=definition['source_type_id'] or dst_type!=definition['target_type_id']): raise ValueError('Relation endpoint type mismatch')
        payload={'type_id':relation.type_id,'type_name':relation.type_name,'source_candidate_id':str(src),'target_candidate_id':str(dst),'source_candidate_revision':1,'target_candidate_revision':1}
        if not definition: payload['suggestion_kind']='relation'
        candidates.append(Candidate(id=uuid4(),revision=1,source_revision_id=source.revision_id,kind='relation' if definition else 'model_suggestion',payload=payload,evidence=evidence(relation.evidence),state='pending'))
    return candidates,parsed.model_dump()

def extract(source_revision,model_revision,*,provider):
    """SourceAdapter/provider port; persistence and leases belong to jobs.run_one."""
    candidates,_=validate_output(source_revision,model_revision,provider.extract(source_revision.chunks,model_revision))
    return candidates
