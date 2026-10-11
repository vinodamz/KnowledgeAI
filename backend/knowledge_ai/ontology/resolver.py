"""Canonical resolution never extends definitions or grants retrieval access."""
from dataclasses import dataclass
from uuid import UUID
import unicodedata
from sqlalchemy import select
from knowledge_ai.ontology.models import CanonicalConcept, KnowledgeModelRevision, ModelLink

class AmbiguousConcept(ValueError):
    pass

@dataclass(frozen=True)
class Match:
    id: UUID
    profile_id: UUID
    name: str

def normalize_label(label):
    return ' '.join(unicodedata.normalize('NFKC',label).casefold().split())

def select_match(concepts, profile_id, label):
    matches=[]
    for c in concepts:
        if c['profile_id']==profile_id and normalize_label(label) in {normalize_label(x) for x in [c['name'],*c['aliases']]}:
            matches.append(Match(c['id'],c['profile_id'],c['name']))
    if len(matches)>1: raise AmbiguousConcept('Label matches multiple canonical concepts')
    return matches[0] if matches else None

def resolve_concept(profile_id, model_revision_id, label, *, db, authorized_profile_ids=None):
    model=db.get(KnowledgeModelRevision,model_revision_id)
    if not model or model.profile_id!=profile_id or model.status!='published': return None
    permitted={profile_id} if authorized_profile_ids is None else set(authorized_profile_ids)
    if profile_id not in permitted: return None
    revisions=[model_revision_id]
    for target in db.scalars(select(KnowledgeModelRevision).join(ModelLink,ModelLink.target_model_revision_id==KnowledgeModelRevision.id).where(ModelLink.model_revision_id==model_revision_id)):
        if target.profile_id in permitted and target.status=='published': revisions.append(target.id)
    matches=[]
    for c in db.scalars(select(CanonicalConcept).where(CanonicalConcept.model_revision_id.in_(revisions))):
        match=select_match([{'id':c.id,'profile_id':c.profile_id,'name':c.name,'aliases':c.aliases}],c.profile_id,label)
        if match: matches.append(match)
    if len(matches)>1: raise AmbiguousConcept('Label matches multiple canonical concepts')
    return matches[0] if matches else None
