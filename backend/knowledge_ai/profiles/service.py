from fastapi import HTTPException
from sqlalchemy import select
from knowledge_ai.governance.policy import authorize
from knowledge_ai.governance.audit import record_event
from knowledge_ai.profiles.models import Profile, KnowledgeVersion, ProjectDependency

def require(db, model, key, lock=False):
    item = db.get(model,key,with_for_update=lock)
    if item is None:
        raise HTTPException(404,'Record not found')
    return item

def configure(actor, profile_id):
    if actor.role != 'admin' and profile_id not in actor.owned_profile_ids:
        raise HTTPException(403,'Only the assigned owner or administrator may configure this profile')

def draft_access(actor, profile_id):
    authorize(actor,'read',profile_id)
    if actor.role != 'admin' and profile_id not in (actor.owned_profile_ids | actor.contribute_profile_ids):
        raise HTTPException(403,'Draft access requires ownership or contribution grant')

def create_version(actor, profile_id, label, predecessor_id=None, *, db):
    configure(actor,profile_id)
    profile = require(db,Profile,profile_id,True)
    if profile.archived:
        raise HTTPException(409,'Archived profile')
    if not label.strip() or len(label)>200:
        raise HTTPException(422,'Invalid version label')
    if db.scalar(select(KnowledgeVersion).where(KnowledgeVersion.profile_id==profile_id,KnowledgeVersion.label==label)):
        raise HTTPException(409,'Version label already exists')
    predecessor = None
    if predecessor_id:
        predecessor = require(db,KnowledgeVersion,predecessor_id)
        if predecessor.profile_id != profile_id or predecessor.status not in {'released','archived'}:
            raise HTTPException(409,'Predecessor must be released in the same profile')
    version = KnowledgeVersion(profile_id=profile_id,label=label,predecessor_id=predecessor_id)
    db.add(version)
    db.flush()
    # Exact pins carry forward, including archived products retained in prior snapshots.
    if predecessor and profile.kind=='project':
        for pin in db.scalars(select(ProjectDependency).where(ProjectDependency.project_version_id==predecessor.id)):
            # Archived pins cannot be newly inserted; explicit repinning required for a successor.
            product = require(db,KnowledgeVersion,pin.product_version_id)
            if product.status != 'released':
                raise HTTPException(409,'Predecessor has archived product pins; explicitly create and repin a version')
            db.add(ProjectDependency(project_version_id=version.id,product_version_id=pin.product_version_id))
    record_event(db,actor.id,'version_created',profile_id,{'version_id':str(version.id)})
    return version

def set_dependencies(db,actor,version_id,product_version_ids):
    version = require(db,KnowledgeVersion,version_id,True)
    configure(actor,version.profile_id)
    profile = require(db,Profile,version.profile_id)
    if version.status != 'draft' or profile.kind != 'project' or profile.archived:
        raise HTTPException(409,'Only draft project versions accept dependencies')
    products = []
    scopes = set()
    for key in set(product_version_ids):
        product = require(db,KnowledgeVersion,key,True)
        authorize(actor,'read',product.profile_id)
        if product.status != 'released' or require(db,Profile,product.profile_id).kind != 'product' or product.profile_id in scopes:
            raise HTTPException(409,'Pin one released version per product profile')
        scopes.add(product.profile_id)
        products.append(product)
    for old in db.scalars(select(ProjectDependency).where(ProjectDependency.project_version_id==version.id)):
        db.delete(old)
    db.flush()
    for product in products:
        db.add(ProjectDependency(project_version_id=version.id,product_version_id=product.id))
    record_event(db,actor.id,'dependencies_changed',version.profile_id,{'version_id':str(version.id),'product_version_ids':[str(p.id) for p in products]})
    db.flush()
    return version
