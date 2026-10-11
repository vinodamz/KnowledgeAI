"""Caller-owned transactions; lock profile/version before candidate rows.

Publication readiness is a preflight contract, not proof of engine publication.
Task6 must lock the scope and freeze/checksum an exact target manifest before use.
Cross-profile instance endpoints are refused until explicit pinned instance links
and live authorization can be verified; ontology links are insufficient.
"""
import hashlib
import json
from datetime import datetime,timezone
from uuid import UUID
from sqlalchemy import select
from fastapi import HTTPException
from knowledge_ai.db import User
from knowledge_ai.profiles.models import Profile,KnowledgeVersion
from knowledge_ai.ingestion.sources import SourceRevision
from knowledge_ai.ingestion.jobs import lock_scope,model_payload
from knowledge_ai.ingestion.extraction import validate_output
from knowledge_ai.review.models import Candidate,ReviewDecision
from knowledge_ai.governance.audit import record_event


def checksum(candidate):
    value={'kind':candidate.kind,'source_revision_id':str(candidate.source_revision_id),'payload':candidate.payload,'evidence':candidate.evidence}
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def latest(db,candidate_id,*,lock=False):
    q=select(Candidate).where(Candidate.id==candidate_id).order_by(Candidate.revision.desc()).limit(1)
    if lock:q=q.with_for_update().execution_options(populate_existing=True)
    c=db.scalar(q)
    if not c:raise HTTPException(404,'Candidate not found')
    return c


def locked_candidates(db,actor,pairs,*,review=True):
    if not pairs or len(pairs)>200 or len({x[0] for x in pairs})!=len(pairs):
        raise HTTPException(422,'Select unique exact candidate/revision pairs (maximum 200)')
    sources={cid:db.get(SourceRevision,latest(db,cid).source_revision_id) for cid,_ in pairs}
    # Avoid candidate->profile inversion; multi-scope decisions are refused.
    scopes={(s.profile_id,s.knowledge_version_id,s.model_revision_id) for s in sources.values()}
    if len(scopes)!=1:raise HTTPException(422,'Batch must belong to one exact version scope')
    profile_id,version_id,model_id=next(iter(scopes))
    lock_scope(db,profile_id,version_id,model_id,actor.id)
    p=db.get(Profile,profile_id);user=db.get(User,actor.id)
    if review and (p.owner_id!=actor.id or user.role not in {'owner','admin'}):
        raise HTTPException(403,'Actual assigned owner required')
    result={}
    for cid,revision in sorted(pairs,key=lambda x:str(x[0])):
        c=latest(db,cid,lock=True)
        if c.revision!=revision:raise HTTPException(409,'Stale candidate revision; reload before reviewing')
        result[cid]=c
    return result,sources


def verified_evidence(source,evidence):
    if not isinstance(evidence,list) or not 1<=len(evidence)<=20:raise HTTPException(422,'Verified evidence required')
    chunks={x['chunk_id']:x for x in source.chunks}
    for e in evidence:
        try:
            ch=chunks[e['chunk_id']];start,end=e['start'],e['end']
            valid=type(start) is int and type(end) is int and 0<=start<end<=len(ch['text']) and e=={'source_revision_id':str(source.revision_id),'page':ch['page'],'chunk_id':ch['chunk_id'],'start':start,'end':end,'excerpt':ch['text'][start:end],'page_start':ch['page_start']+start,'page_end':ch['page_start']+end}
        except (KeyError,TypeError):valid=False
        if not valid:raise HTTPException(422,'Unverified source evidence offsets')


def endpoints(db,c,source):
    if c.kind!='relation':return []
    definition=next((r for r in model_payload(db,source.model_revision_id)['relations'] if r['id']==c.payload.get('type_id')),None)
    if not definition:raise HTTPException(422,'Unknown relation type in exact published model')
    result=[]
    for side in ('source','target'):
        try:cid=UUID(c.payload[f'{side}_candidate_id']);rev=c.payload[f'{side}_candidate_revision']
        except (KeyError,ValueError,TypeError):raise HTTPException(422,'Exact endpoint revisions required')
        if type(rev) is not int or rev<1:raise HTTPException(422,'Exact endpoint revisions required')
        endpoint=latest(db,cid)
        endpoint_source=db.get(SourceRevision,endpoint.source_revision_id)
        if (endpoint_source.profile_id,endpoint_source.knowledge_version_id)!=(source.profile_id,source.knowledge_version_id):
            raise HTTPException(422,'Cross-scope endpoint requires an explicit authorized pinned instance link; not supported')
        if endpoint.revision!=rev:raise HTTPException(409,f'{side} endpoint changed; explicitly revise relation endpoints')
        if endpoint.kind!='entity' or endpoint.payload.get('type_id')!=definition[f'{side}_type_id']:
            raise HTTPException(422,'Endpoint type incompatible with exact relation model')
        result.append(endpoint)
    return result


def validate_candidate(db,c,source):
    verified_evidence(source,c.evidence)
    if c.kind=='relation':
        if set(c.payload)-{'type_id','type_name','source_candidate_id','target_candidate_id','source_candidate_revision','target_candidate_revision','description'}:raise HTTPException(422,'Unknown relation payload fields')
        endpoints(db,c,source)
    elif c.kind=='entity' or (c.kind=='model_suggestion' and c.payload.get('suggestion_kind')=='entity'):
        try:
            fields={k:v for k,v in c.payload.items() if k not in {'description','canonical_resolution','canonical_concept_id','suggestion_kind'}}
            if c.kind=='entity' and not fields.get('type_id'):raise ValueError('Exact model type required')
            normalized,_=validate_output(source,model_payload(db,source.model_revision_id),{'entities':[dict(fields,key='edit',evidence=[{k:e[k] for k in ('chunk_id','start','end','excerpt')} for e in c.evidence])],'relations':[]})
            for key in ('canonical_resolution','canonical_concept_id'):
                if key in c.payload and c.payload[key]!=normalized[0].payload.get(key):raise ValueError('Invalid canonical binding')
        except (ValueError,TypeError,KeyError):raise HTTPException(422,'Payload does not match exact published model')
    elif c.kind=='model_suggestion':
        if c.payload.get('suggestion_kind')!='relation' or c.payload.get('type_id') is not None or set(c.payload)-{'suggestion_kind','type_id','type_name','source_candidate_id','target_candidate_id','source_candidate_revision','target_candidate_revision','description'}:
            raise HTTPException(422,'Invalid relation model suggestion')
        for side in ('source','target'):
            try:
                endpoint=latest(db,UUID(c.payload[f'{side}_candidate_id']))
                rev=c.payload[f'{side}_candidate_revision']
            except (KeyError,TypeError,ValueError):raise HTTPException(422,'Exact suggestion endpoints required')
            endpoint_source=db.get(SourceRevision,endpoint.source_revision_id)
            if (endpoint_source.profile_id,endpoint_source.knowledge_version_id)!=(source.profile_id,source.knowledge_version_id):raise HTTPException(422,'Suggestion endpoint requires authorized pinned instance link')
            if type(rev) is not int or endpoint.revision!=rev:raise HTTPException(409,'Suggestion endpoint changed; explicitly revise suggestion')
    if 'description' in c.payload and not isinstance(c.payload['description'],str):raise HTTPException(422,'Description must be text')


def edit_candidate(db,actor,candidate_id,expected_revision,payload,*,evidence=None):
    rows,sources=locked_candidates(db,actor,[(candidate_id,expected_revision)],review=False)
    old=rows[candidate_id]
    new=Candidate(id=old.id,revision=old.revision+1,source_revision_id=old.source_revision_id,kind=old.kind,payload=payload,evidence=old.evidence if evidence is None else evidence,state='pending')
    validate_candidate(db,new,sources[candidate_id])
    db.add(new);db.flush()
    record_event(db,actor.id,'candidate_edited',sources[candidate_id].profile_id,{'candidate_id':str(old.id),'previous_revision':old.revision,'revision':new.revision,'checksum':checksum(new)})
    return new


def review_batch(db,actor,pairs,decision,reason=None):
    rows,sources=locked_candidates(db,actor,pairs)
    if decision not in {'approve','reject','request_changes'}:raise HTTPException(422,'Unknown review decision')
    reason=reason.strip() if isinstance(reason,str) else None
    if decision!='approve' and not reason:raise HTTPException(422,'A rejection or change request needs a reason')
    if reason and len(reason)>4000:raise HTTPException(422,'Reason too long')
    # Validate everything before changing anything. Scope lock serializes edits,
    # including endpoint edits and review ownership changes.
    if decision=='approve':
        for c in rows.values():validate_candidate(db,c,sources[c.id])
    decisions=[]
    for c in rows.values():
        d=ReviewDecision(candidate_id=c.id,candidate_revision=c.revision,actor_id=actor.id,decision=decision,previous_state=c.state,reason=reason,checksum=checksum(c),created_at=datetime.now(timezone.utc))
        c.state={'approve':'approved','reject':'rejected','request_changes':'changes_requested'}[decision]
        db.add(d);db.flush();decisions.append(d)
        record_event(db,actor.id,'candidate_reviewed',sources[c.id].profile_id,decision_json(d))
    return decisions


def review_candidate(db,actor,candidate_id,expected_revision,decision,reason=None):
    return review_batch(db,actor,[(candidate_id,expected_revision)],decision,reason)[0]


def approval_matches(db,c):
    d=db.scalar(select(ReviewDecision).where(ReviewDecision.candidate_id==c.id,ReviewDecision.candidate_revision==c.revision).order_by(ReviewDecision.created_at.desc(),ReviewDecision.id.desc()).limit(1))
    return c.state=='approved' and d is not None and d.decision=='approve' and d.checksum==checksum(c)


def publication_readiness(db,c,*,target_manifest=None):
    """Exact pairs of approved endpoints already verified or included by Task6.

    None means no generation has been supplied. An approved entity can await
    publication; relations require both approved endpoint pairs in the manifest.
    Apply this preflight only to newly selected facts. Preserve already verified
    active-generation pairs separately without requiring they remain latest.
    Existing active snapshots stay active when a new draft revision is created.
    This function never approves, activates or publishes any record.
    """
    blockers=[]
    if not approval_matches(db,c):blockers.append('Exact revision lacks checksum-bound approval')
    if latest(db,c.id).revision!=c.revision:blockers.append('Candidate revision superseded')
    if c.kind=='model_suggestion':blockers.append('Model suggestion cannot publish as an instance')
    source=db.get(SourceRevision,c.source_revision_id)
    version=db.get(KnowledgeVersion,source.knowledge_version_id)
    profile=db.get(Profile,source.profile_id)
    if profile.archived or version.status!='draft' or version.model_revision_id!=source.model_revision_id:
        blockers.append('Candidate scope is archived, released or rebound to a different model')
    try:
        validate_candidate(db,c,source)
        for e in endpoints(db,c,source):
            if not approval_matches(db,e):blockers.append(f'Endpoint {e.id}:{e.revision} is not approved')
            if target_manifest is None or (e.id,e.revision) not in target_manifest:blockers.append(f'Endpoint {e.id}:{e.revision} absent from exact target manifest')
    except HTTPException as exc:blockers.append(str(exc.detail))
    return {'ready':not blockers,'blockers':blockers}


def decision_json(d):
    return {'id':str(d.id),'candidate_id':str(d.candidate_id),'candidate_revision':d.candidate_revision,'actor_id':str(d.actor_id),'decision':d.decision,'previous_state':d.previous_state,'reason':d.reason,'checksum':d.checksum,'created_at':d.created_at.isoformat()}


def candidate_json(db,c):
    readiness=publication_readiness(db,c) if c.state=='approved' else {'ready':False,'blockers':[]}
    history=list(db.scalars(select(ReviewDecision).where(ReviewDecision.candidate_id==c.id,ReviewDecision.candidate_revision==c.revision).order_by(ReviewDecision.created_at,ReviewDecision.id)))
    from knowledge_ai.publication.builder import active
    generation=active(db)
    published=bool(generation and any(f['candidate_id']==str(c.id) and f['revision']==c.revision and f['checksum']==checksum(c) for f in generation.scope_manifest['facts']))
    return {'published':published,'active_generation_id':str(generation.id) if published else None,'id':str(c.id),'revision':c.revision,'latest_revision':latest(db,c.id).revision,'kind':c.kind,'payload':c.payload,'evidence':c.evidence,'state':c.state,'status':'published' if published else ('approved_awaiting_publication' if readiness['ready'] else 'approved_but_blocked') if c.state=='approved' else {'pending':'draft','rejected':'rejected','changes_requested':'changes_requested'}[c.state],'source_revision_id':str(c.source_revision_id),'checksum':checksum(c),'blockers':readiness['blockers'],'reason':history[-1].reason if history else None,'decisions':[decision_json(d) for d in history]}
