from uuid import uuid4
from knowledge_ai.ontology.resolver import normalize_label, select_match, AmbiguousConcept
import pytest

def test_normalized_alias_and_scope():
    a,b=uuid4(),uuid4()
    concepts=[{'id':uuid4(),'profile_id':a,'name':'Programmable Controller','aliases':['PLC']}]
    assert select_match(concepts,a,'  plc ').name=='Programmable Controller'
    assert select_match(concepts,b,'PLC') is None
    assert normalize_label('  Full   WIDTH ')=='full width'

def test_duplicate_alias_is_ambiguous():
    p=uuid4()
    concepts=[{'id':uuid4(),'profile_id':p,'name':n,'aliases':['PLC']} for n in ['A','B']]
    with pytest.raises(AmbiguousConcept): select_match(concepts,p,'plc')
