from uuid import UUID
from typing import Literal
from fastapi import APIRouter,Depends
from pydantic import Field,StrictInt
from knowledge_ai.db import get_db
from knowledge_ai.governance.auth import current_actor
from knowledge_ai.profiles.routes import Input
from knowledge_ai.review.service import edit_candidate,review_candidate,review_batch,candidate_json,decision_json
router=APIRouter(prefix='/api')
class ReviewInput(Input):
    expected_revision: StrictInt=Field(ge=1)
    decision: Literal['approve','reject','request_changes']
    reason: str|None=None
class ExactPair(Input):
    candidate_id: UUID
    revision: StrictInt=Field(ge=1)
class BatchInput(Input):
    candidates: list[ExactPair]=Field(min_length=1,max_length=200)
    decision: Literal['approve','reject','request_changes']
    reason: str|None=None
class EditInput(Input):
    expected_revision: StrictInt=Field(ge=1)
    payload: dict
    evidence: list[dict]|None=None
@router.patch('/candidates/{candidate_id}')
def edit(candidate_id:UUID,body:EditInput,actor=Depends(current_actor),db=Depends(get_db)):
    c=edit_candidate(db,actor,candidate_id,body.expected_revision,body.payload,evidence=body.evidence)
    db.commit();return candidate_json(db,c)
@router.post('/candidates/{candidate_id}/review')
def review(candidate_id:UUID,body:ReviewInput,actor=Depends(current_actor),db=Depends(get_db)):
    d=review_candidate(db,actor,candidate_id,body.expected_revision,body.decision,body.reason)
    db.commit();return decision_json(d)
@router.post('/review/batch')
def batch(body:BatchInput,actor=Depends(current_actor),db=Depends(get_db)):
    ds=review_batch(db,actor,[(c.candidate_id,c.revision) for c in body.candidates],body.decision,body.reason)
    db.commit();return [decision_json(d) for d in ds]
