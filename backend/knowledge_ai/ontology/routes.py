from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from knowledge_ai.db import get_db
from knowledge_ai.governance.auth import current_actor
from knowledge_ai.governance.policy import authorize
from knowledge_ai.governance.audit import record_event
from knowledge_ai.profiles.routes import Input, commit, version_json
from knowledge_ai.profiles.service import require, draft_access
from knowledge_ai.ontology.models import KnowledgeModelRevision, EntityType, RelationType, CanonicalConcept, ModelLink
from knowledge_ai.ontology.service import create_model, edit_model, publish_model, bind_model, SCORE_FIELDS
from knowledge_ai.ontology.resolver import resolve_concept, AmbiguousConcept
router=APIRouter(prefix='/api')
class ModelInput(Input):
    semantic_description: str=''
class AttributeInput(Input):
    name: str=Field(min_length=1,max_length=200)
    data_type: str=Field(min_length=1,max_length=100)
    description: str=''
class EntityInput(Input):
    name: str=Field(min_length=1,max_length=200)
    attributes: list[AttributeInput]=[]
    scores: dict[str,float | str]={}
class Qualification(Input):
    qualification: str=Field(min_length=1)
class ConceptInput(Input):
    name: str=Field(min_length=1,max_length=200)
    aliases: list[str]=[]
    provenance: dict={}
class RelationInput(Input):
    name: str=Field(min_length=1,max_length=200)
    source_type_id: UUID
    target_type_id: UUID
class Links(Input):
    target_model_revision_ids: list[UUID]
class Binding(Input):
    model_revision_id: UUID

def model_json(db,m):
    return {'id':str(m.id),'profile_id':str(m.profile_id),'revision':m.revision,'status':m.status,'semantic_description':m.semantic_description,
            'entities':[{'id':str(e.id),'name':e.name,'attributes':e.attributes,'scores':e.scores,'qualification':e.qualification,'qualified_by':str(e.qualified_by) if e.qualified_by else None} for e in db.scalars(select(EntityType).where(EntityType.model_revision_id==m.id))],
            'relations':[{'id':str(r.id),'name':r.name,'source_type_id':str(r.source_type_id),'target_type_id':str(r.target_type_id)} for r in db.scalars(select(RelationType).where(RelationType.model_revision_id==m.id))],
            'concepts':[{'id':str(c.id),'name':c.name,'aliases':c.aliases,'provenance':c.provenance} for c in db.scalars(select(CanonicalConcept).where(CanonicalConcept.model_revision_id==m.id))],
            'target_model_revision_ids':[str(x) for x in db.scalars(select(ModelLink.target_model_revision_id).where(ModelLink.model_revision_id==m.id))]}
def readable(actor,m):
    authorize(actor,'read',m.profile_id)
    if m.status!='published': draft_access(actor,m.profile_id)
def save(db,actor,m,action):
    record_event(db,actor.id,action,m.profile_id,{'model_revision_id':str(m.id)})
    commit(db)
    return model_json(db,m)
@router.post('/profiles/{profile_id}/models',status_code=201)
def create(profile_id:UUID,body:ModelInput,actor=Depends(current_actor),db=Depends(get_db)):
    m=create_model(db,actor,profile_id,body.semantic_description); commit(db); return model_json(db,m)
@router.get('/profiles/{profile_id}/models')
def listing(profile_id:UUID,actor=Depends(current_actor),db=Depends(get_db)):
    authorize(actor,'read',profile_id)
    query=select(KnowledgeModelRevision).where(KnowledgeModelRevision.profile_id==profile_id).order_by(KnowledgeModelRevision.revision)
    if actor.role!='admin' and profile_id not in actor.owned_profile_ids|actor.contribute_profile_ids: query=query.where(KnowledgeModelRevision.status=='published')
    return [model_json(db,m) for m in db.scalars(query)]
@router.get('/models/{model_id}')
def get(model_id:UUID,actor=Depends(current_actor),db=Depends(get_db)):
    m=require(db,KnowledgeModelRevision,model_id); readable(actor,m); return model_json(db,m)
@router.patch('/models/{model_id}')
def patch(model_id:UUID,body:ModelInput,actor=Depends(current_actor),db=Depends(get_db)):
    _,m=edit_model(db,actor,model_id); m.semantic_description=body.semantic_description; return save(db,actor,m,'model_changed')
@router.post('/models/{model_id}/entities',status_code=201)
def entity(model_id:UUID,body:EntityInput,actor=Depends(current_actor),db=Depends(get_db)):
    _,m=edit_model(db,actor,model_id)
    if not body.name.strip() or set(body.scores)-SCORE_FIELDS: raise HTTPException(422,'Invalid name or scoring fields')
    db.add(EntityType(model_revision_id=m.id,**body.model_dump())); return save(db,actor,m,'model_entity_added')
@router.put('/models/{model_id}/entities/{entity_id}/qualification')
def qualify(model_id:UUID,entity_id:UUID,body:Qualification,actor=Depends(current_actor),db=Depends(get_db)):
    p,m=edit_model(db,actor,model_id)
    if p.owner_id!=actor.id or actor.role not in {'owner','admin'}: raise HTTPException(403,'Actual assigned owner qualification required')
    e=require(db,EntityType,entity_id)
    if e.model_revision_id!=m.id: raise HTTPException(409,'Entity belongs to different model')
    if not body.qualification.strip(): raise HTTPException(422,'Qualification required')
    e.qualification=body.qualification; e.qualified_by=actor.id; return save(db,actor,m,'model_entity_qualified')
@router.post('/models/{model_id}/concepts',status_code=201)
def concept(model_id:UUID,body:ConceptInput,actor=Depends(current_actor),db=Depends(get_db)):
    _,m=edit_model(db,actor,model_id)
    if any(not x.strip() for x in [body.name,*body.aliases]): raise HTTPException(422,'Empty canonical label or alias')
    db.add(CanonicalConcept(profile_id=m.profile_id,model_revision_id=m.id,**body.model_dump())); return save(db,actor,m,'model_concept_added')
@router.post('/models/{model_id}/relations',status_code=201)
def relation(model_id:UUID,body:RelationInput,actor=Depends(current_actor),db=Depends(get_db)):
    _,m=edit_model(db,actor,model_id)
    for key in [body.source_type_id,body.target_type_id]:
        if require(db,EntityType,key).model_revision_id!=m.id: raise HTTPException(409,'Relation endpoints must belong to model')
    db.add(RelationType(model_revision_id=m.id,**body.model_dump())); return save(db,actor,m,'model_relation_added')
@router.put('/models/{model_id}/links')
def links(model_id:UUID,body:Links,actor=Depends(current_actor),db=Depends(get_db)):
    _,m=edit_model(db,actor,model_id)
    targets=[]
    for key in sorted(set(body.target_model_revision_ids),key=str):
        target=require(db,KnowledgeModelRevision,key); authorize(actor,'read',target.profile_id)
        if target.status!='published' or target.profile_id==m.profile_id: raise HTTPException(409,'Link must target another profile published model')
        targets.append(key)
    for link in db.scalars(select(ModelLink).where(ModelLink.model_revision_id==m.id)): db.delete(link)
    db.flush()
    for key in targets: db.add(ModelLink(model_revision_id=m.id,target_model_revision_id=key))
    return save(db,actor,m,'model_links_changed')
@router.post('/models/{model_id}/publish')
def publish(model_id:UUID,actor=Depends(current_actor),db=Depends(get_db)):
    m=publish_model(db,actor,model_id); commit(db); return model_json(db,m)
@router.put('/versions/{version_id}/model')
def bind(version_id:UUID,body:Binding,actor=Depends(current_actor),db=Depends(get_db)):
    v=bind_model(db,actor,version_id,body.model_revision_id); commit(db); return version_json(db,v)
@router.get('/models/{model_id}/resolve')
def resolve(model_id:UUID,label:str,actor=Depends(current_actor),db=Depends(get_db)):
    m=require(db,KnowledgeModelRevision,model_id); readable(actor,m)
    permitted=actor.owned_profile_ids|actor.read_profile_ids|actor.contribute_profile_ids
    if actor.role=='admin':
        from knowledge_ai.profiles.models import Profile
        permitted=set(db.scalars(select(Profile.id)))
    try: result=resolve_concept(m.profile_id,m.id,label,db=db,authorized_profile_ids=permitted)
    except AmbiguousConcept as exc: raise HTTPException(409,str(exc))
    return {'match':{'id':str(result.id),'profile_id':str(result.profile_id),'name':result.name} if result else None}

# Full replacement edits keep draft authoring small and invalidate prior qualification.
@router.put('/models/{model_id}/entities/{entity_id}')
def update_entity(model_id:UUID,entity_id:UUID,body:EntityInput,actor=Depends(current_actor),db=Depends(get_db)):
    _,m=edit_model(db,actor,model_id)
    e=require(db,EntityType,entity_id)
    if e.model_revision_id!=m.id: raise HTTPException(409,'Entity belongs to different model')
    if not body.name.strip() or set(body.scores)-SCORE_FIELDS: raise HTTPException(422,'Invalid name or scoring fields')
    for key,value in body.model_dump().items(): setattr(e,key,value)
    e.qualification=None; e.qualified_by=None
    return save(db,actor,m,'model_entity_changed')

@router.put('/models/{model_id}/concepts/{concept_id}')
def update_concept(model_id:UUID,concept_id:UUID,body:ConceptInput,actor=Depends(current_actor),db=Depends(get_db)):
    _,m=edit_model(db,actor,model_id)
    c=require(db,CanonicalConcept,concept_id)
    if c.model_revision_id!=m.id: raise HTTPException(409,'Concept belongs to different model')
    if any(not x.strip() for x in [body.name,*body.aliases]): raise HTTPException(422,'Empty label or alias')
    for key,value in body.model_dump().items(): setattr(c,key,value)
    return save(db,actor,m,'model_concept_changed')

@router.put('/models/{model_id}/relations/{relation_id}')
def update_relation(model_id:UUID,relation_id:UUID,body:RelationInput,actor=Depends(current_actor),db=Depends(get_db)):
    _,m=edit_model(db,actor,model_id)
    r=require(db,RelationType,relation_id)
    if r.model_revision_id!=m.id: raise HTTPException(409,'Relation belongs to different model')
    for key in [body.source_type_id,body.target_type_id]:
        if require(db,EntityType,key).model_revision_id!=m.id: raise HTTPException(409,'Relation endpoints must belong to model')
    for key,value in body.model_dump().items(): setattr(r,key,value)
    return save(db,actor,m,'model_relation_changed')

@router.delete('/models/{model_id}/{kind}/{definition_id}')
def delete_definition(model_id:UUID,kind:str,definition_id:UUID,actor=Depends(current_actor),db=Depends(get_db)):
    _,m=edit_model(db,actor,model_id)
    table={'entities':EntityType,'concepts':CanonicalConcept,'relations':RelationType}.get(kind)
    if table is None: raise HTTPException(404,'Unknown definition kind')
    item=require(db,table,definition_id)
    if item.model_revision_id!=m.id: raise HTTPException(409,'Definition belongs to different model')
    db.delete(item)
    return save(db,actor,m,'model_definition_deleted')
