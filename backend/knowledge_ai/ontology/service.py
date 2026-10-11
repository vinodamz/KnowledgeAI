from fastapi import HTTPException
from sqlalchemy import select, func
from knowledge_ai.profiles.models import Profile, ProfileGrant, KnowledgeVersion
from knowledge_ai.profiles.service import require, configure
from knowledge_ai.governance.audit import record_event
from knowledge_ai.ontology.models import KnowledgeModelRevision, EntityType

SCORE_FIELDS={'identity','lifecycle','relationships','own_attributes','reuse','retrieval_rationale'}

def edit_profile(db,actor,profile_id):
    p=require(db,Profile,profile_id,True)
    grant=db.get(ProfileGrant,(profile_id,actor.id),populate_existing=True)
    if not (actor.role=='admin' or (actor.role=='owner' and p.owner_id==actor.id) or (actor.role in {'owner','contributor'} and grant and grant.contribute)):
        raise HTTPException(403,'Model draft requires live ownership or contribution grant')
    if p.archived: raise HTTPException(409,'Archived profile')
    return p

def edit_model(db,actor,model_id):
    m=require(db,KnowledgeModelRevision,model_id)
    p=edit_profile(db,actor,m.profile_id)
    m=require(db,KnowledgeModelRevision,model_id,True)
    if m.status!='draft': raise HTTPException(409,'Published model is immutable')
    return p,m

def create_model(db,actor,profile_id,description):
    edit_profile(db,actor,profile_id)
    revision=(db.scalar(select(func.max(KnowledgeModelRevision.revision)).where(KnowledgeModelRevision.profile_id==profile_id)) or 0)+1
    m=KnowledgeModelRevision(profile_id=profile_id,revision=revision,semantic_description=description)
    db.add(m); db.flush()
    record_event(db,actor.id,'model_created',profile_id,{'model_revision_id':str(m.id)})
    return m

def publish_model(db,actor,model_id):
    m=require(db,KnowledgeModelRevision,model_id)
    p=configure(actor,m.profile_id,db=db)
    if p.owner_id!=actor.id or actor.role not in {'owner','admin'}: raise HTTPException(403,'Only actual assigned owner may publish')
    m=require(db,KnowledgeModelRevision,model_id,True)
    if p.archived or m.status!='draft': raise HTTPException(409,'Model cannot publish')
    for entity in db.scalars(select(EntityType).where(EntityType.model_revision_id==m.id)):
        if not entity.qualification or not entity.qualified_by: raise HTTPException(409,'Owner qualification required for every entity definition')
    m.status='published'
    record_event(db,actor.id,'model_published',m.profile_id,{'model_revision_id':str(m.id)})
    return m

def bind_model(db,actor,version_id,model_id):
    v=require(db,KnowledgeVersion,version_id)
    p=configure(actor,v.profile_id,db=db)
    v=require(db,KnowledgeVersion,version_id,True)
    m=require(db,KnowledgeModelRevision,model_id)
    if p.archived or v.status!='draft' or m.profile_id!=v.profile_id or m.status!='published': raise HTTPException(409,'Draft version requires published model from same profile')
    v.model_revision_id=m.id
    record_event(db,actor.id,'version_model_bound',v.profile_id,{'version_id':str(v.id),'model_revision_id':str(m.id)})
    return v
