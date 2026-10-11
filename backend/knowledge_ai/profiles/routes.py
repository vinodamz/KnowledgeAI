from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from knowledge_ai.db import get_db, User
from knowledge_ai.governance.auth import current_actor, passwords
from knowledge_ai.governance.policy import authorize
from knowledge_ai.governance.audit import record_event
from knowledge_ai.profiles.models import Profile, KnowledgeVersion, ProjectDependency, ProfileGrant
from knowledge_ai.profiles.service import require, configure, draft_access, create_version, set_dependencies, validate_label

router = APIRouter(prefix='/api')
class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')
class ProfileInput(Input):
    kind: Literal['product','project']
    name: str = Field(min_length=1,max_length=200)
    owner_id: UUID
class ProfilePatch(Input):
    name: str | None = Field(default=None,min_length=1,max_length=200)
    owner_id: UUID | None = None
    archived: bool | None = None
class VersionInput(Input):
    label: str = Field(min_length=1,max_length=200)
    predecessor_id: UUID | None = None
class VersionPatch(Input):
    label: str | None = Field(default=None,min_length=1,max_length=200)
    status: Literal['draft','released','archived'] | None = None
class Pins(Input):
    product_version_ids: list[UUID]
class Grant(Input):
    read: bool = False
    contribute: bool = False
class UserInput(Input):
    username: str = Field(min_length=1,max_length=200)
    password: str = Field(min_length=12,max_length=1024)
    role: Literal['admin','owner','contributor','reader']
class UserPatch(Input):
    active: bool

def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'Conflicting registry record')

def admin(actor):
    if actor.role!='admin':
        raise HTTPException(403,'Administrator required')

def owner(db,key):
    user = require(db,User,key)
    if not user.active or user.role not in {'owner','admin'}:
        raise HTTPException(422,'Assign an active owner or administrator')

def profile_json(p):
    return {'id':str(p.id),'kind':p.kind,'name':p.name,'owner_id':str(p.owner_id),'archived':p.archived}
def version_json(db,v):
    return {'id':str(v.id),'profile_id':str(v.profile_id),'label':v.label,'predecessor_id':str(v.predecessor_id) if v.predecessor_id else None,'status':v.status,'product_version_ids':sorted(str(x) for x in db.scalars(select(ProjectDependency.product_version_id).where(ProjectDependency.project_version_id==v.id)))}
def user_json(u):
    return {'id':str(u.id),'username':u.username,'role':u.role,'active':u.active}

@router.get('/profiles')
def profiles(actor=Depends(current_actor),db=Depends(get_db)):
    query=select(Profile).order_by(Profile.name,Profile.id)
    if actor.role!='admin':
        query=query.where(Profile.id.in_(actor.owned_profile_ids|actor.read_profile_ids|actor.contribute_profile_ids))
    return [profile_json(p) for p in db.scalars(query)]

@router.post('/profiles',status_code=201)
def add_profile(body:ProfileInput,actor=Depends(current_actor),db=Depends(get_db)):
    authorize(actor,'create_profile',None)
    owner(db,body.owner_id)
    p=Profile(**body.model_dump())
    db.add(p); db.flush()
    record_event(db,actor.id,'profile_created',p.id,{'owner_id':str(p.owner_id)})
    commit(db)
    return profile_json(p)

@router.get('/profiles/{profile_id}')
def get_profile(profile_id:UUID,actor=Depends(current_actor),db=Depends(get_db)):
    authorize(actor,'read',profile_id)
    return profile_json(require(db,Profile,profile_id))

@router.patch('/profiles/{profile_id}')
def patch_profile(profile_id:UUID,body:ProfilePatch,actor=Depends(current_actor),db=Depends(get_db)):
    p=configure(actor,profile_id,db=db)
    values=body.model_dump(exclude_unset=True)
    if any(v is None for v in values.values()): raise HTTPException(422,'Null values refused')
    if 'owner_id' in values:
        authorize(actor,'assign_owner',profile_id); owner(db,body.owner_id)
    for k,v in values.items(): setattr(p,k,v)
    record_event(db,actor.id,'profile_changed',profile_id,{k:str(v) for k,v in values.items()})
    commit(db)
    return profile_json(p)

@router.post('/profiles/{profile_id}/versions',status_code=201)
def add_version(profile_id:UUID,body:VersionInput,actor=Depends(current_actor),db=Depends(get_db)):
    v=create_version(actor,profile_id,body.label,body.predecessor_id,db=db)
    commit(db)
    return version_json(db,v)

@router.get('/profiles/{profile_id}/versions')
def versions(profile_id:UUID,actor=Depends(current_actor),db=Depends(get_db)):
    authorize(actor,'read',profile_id)
    require(db,Profile,profile_id)
    query=select(KnowledgeVersion).where(KnowledgeVersion.profile_id==profile_id).order_by(KnowledgeVersion.label)
    if actor.role!='admin' and profile_id not in actor.owned_profile_ids|actor.contribute_profile_ids:
        query=query.where(KnowledgeVersion.status=='released')
    return [version_json(db,v) for v in db.scalars(query)]

@router.get('/versions/{version_id}')
def get_version(version_id:UUID,actor=Depends(current_actor),db=Depends(get_db)):
    v=require(db,KnowledgeVersion,version_id)
    authorize(actor,'read',v.profile_id)
    if v.status!='released': draft_access(actor,v.profile_id)
    return version_json(db,v)

@router.patch('/versions/{version_id}')
def patch_version(version_id:UUID,body:VersionPatch,actor=Depends(current_actor),db=Depends(get_db)):
    v=require(db,KnowledgeVersion,version_id)
    configure(actor,v.profile_id,db=db)
    v=require(db,KnowledgeVersion,version_id,True)
    values=body.model_dump(exclude_unset=True)
    if any(x is None for x in values.values()): raise HTTPException(422,'Null values refused')
    if 'label' in values: validate_label(body.label)
    if body.status=='released': raise HTTPException(409,'Release requires a verified publication snapshot; use the release workflow')
    if v.status!='draft' and values and values!={'status':'archived'}:
        raise HTTPException(409,'Released or archived version is immutable')
    for k,value in values.items(): setattr(v,k,value)
    record_event(db,actor.id,'version_changed',v.profile_id,{'version_id':str(v.id),**values})
    commit(db)
    return version_json(db,v)

@router.put('/versions/{version_id}/dependencies')
def dependencies(version_id:UUID,body:Pins,actor=Depends(current_actor),db=Depends(get_db)):
    v=set_dependencies(db,actor,version_id,body.product_version_ids)
    commit(db)
    return version_json(db,v)

@router.put('/profiles/{profile_id}/grants/{user_id}')
def grant(profile_id:UUID,user_id:UUID,body:Grant,actor=Depends(current_actor),db=Depends(get_db)):
    admin(actor); require(db,Profile,profile_id); user=require(db,User,user_id)
    if not user.active: raise HTTPException(422,'Inactive user')
    if body.contribute and user.role not in {'contributor','owner','admin'}: raise HTTPException(422,'Reader cannot receive contribution authority')
    g=db.get(ProfileGrant,(profile_id,user_id))
    if not g:
        g=ProfileGrant(profile_id=profile_id,user_id=user_id); db.add(g)
    g.read,g.contribute=body.read,body.contribute
    record_event(db,actor.id,'grant_changed',profile_id,{'user_id':str(user_id),**body.model_dump()})
    commit(db)
    return {'user_id':str(user_id),'profile_id':str(profile_id),**body.model_dump()}

@router.get('/profiles/{profile_id}/grants')
def grants(profile_id:UUID,actor=Depends(current_actor),db=Depends(get_db)):
    admin(actor); require(db,Profile,profile_id)
    return [{'user_id':str(g.user_id),'read':g.read,'contribute':g.contribute} for g in db.scalars(select(ProfileGrant).where(ProfileGrant.profile_id==profile_id))]

@router.get('/users')
def users(actor=Depends(current_actor),db=Depends(get_db)):
    admin(actor)
    return [user_json(u) for u in db.scalars(select(User).order_by(User.username))]

@router.post('/users',status_code=201)
def add_user(body:UserInput,actor=Depends(current_actor),db=Depends(get_db)):
    admin(actor)
    u=User(username=body.username,password_hash=passwords.hash(body.password),role=body.role)
    db.add(u)
    try: db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,'Username already exists')
    record_event(db,actor.id,'user_created',details={'user_id':str(u.id),'role':u.role})
    commit(db)
    return user_json(u)

@router.patch('/users/{user_id}')
def patch_user(user_id:UUID,body:UserPatch,actor=Depends(current_actor),db=Depends(get_db)):
    admin(actor)
    if user_id==actor.id and not body.active: raise HTTPException(409,'Cannot disable your own administrator session')
    u=require(db,User,user_id,True); u.active=body.active
    record_event(db,actor.id,'user_changed',details={'user_id':str(u.id),'active':u.active})
    commit(db)
    return user_json(u)
