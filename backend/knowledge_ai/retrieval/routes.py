from dataclasses import asdict
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from knowledge_ai.db import get_db
from knowledge_ai.governance.auth import current_actor
from knowledge_ai.profiles.models import KnowledgeVersion, Profile
from knowledge_ai.publication.reader import pin_generation
from .planner import resolve_context, live_actor, check_version
from .service import RetrievalService
from .contracts import AnswerResponse, GraphResponse, AvailableContextResponse

router = APIRouter(prefix='/api')
class AskInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile_id: UUID
    version_id: UUID
    query: str = Field(min_length=1, max_length=4000)

def service(request, db, actor):
    factory = getattr(request.app.state, 'retrieval_service_factory', RetrievalService)
    return factory(db, actor, request.app.state.settings)

@router.get('/available-contexts', response_model=list[AvailableContextResponse])
def contexts(actor=Depends(current_actor), db=Depends(get_db)):
    actor = live_actor(db, actor)
    result = []
    for version in db.scalars(select(KnowledgeVersion).order_by(KnowledgeVersion.id)):
        try: check_version(db, actor, version.id)
        except HTTPException as e:
            if e.status_code == 403: continue
            raise
        profile = db.get(Profile, version.profile_id)
        result.append({'profile_id':str(profile.id), 'profile_name':profile.name, 'profile_kind':profile.kind,
                       'version_id':str(version.id), 'version_label':version.label, 'version_status':version.status})
    return result

@router.post('/ask', response_model=AnswerResponse)
def ask(body: AskInput, request: Request, actor=Depends(current_actor), db=Depends(get_db)):
    context = resolve_context(db, actor, body.profile_id, body.version_id)
    return asdict(service(request, db, actor).answer(context, body.query))

@router.get('/graph', response_model=GraphResponse)
def graph(request: Request, version_ids: list[UUID] = Query(min_length=1, max_length=20), actor=Depends(current_actor), db=Depends(get_db)):
    if set(request.query_params) != {'version_ids'}: raise HTTPException(422, 'Only explicit version_ids are accepted')
    # Authorize EVERY selected context and dependency before first store access.
    contexts = []
    generation = pin_generation(db)
    actor = live_actor(db, actor)
    for version_id in dict.fromkeys(version_ids):
        version = check_version(db, actor, version_id)
        contexts.append(resolve_context(db, actor, version.profile_id, version.id, pinned_generation=generation))
    retrieval = service(request, db, actor)
    merged = {'nodes':{}, 'edges':{}, 'citations':{}, 'contexts':[]}
    for context in contexts:
        result = retrieval.graph(context)
        for key in ('nodes','edges','citations'):
            for row in result[key]: merged[key][row['id']] = row
        merged['contexts'].append(result['policy_context'])
    if len(merged['nodes']) + len(merged['edges']) > 2000: raise HTTPException(422, 'Graph is too large; select fewer versions')
    return {key:list(value.values()) if isinstance(value, dict) else value for key, value in merged.items()}
