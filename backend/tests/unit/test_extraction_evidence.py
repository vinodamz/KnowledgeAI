from uuid import uuid4
from types import SimpleNamespace
import pytest
from knowledge_ai.ingestion.extraction import validate_output
from knowledge_ai.ingestion.parser import parse,InvalidSource
from knowledge_ai.adapters.object_store import ObjectStore

def fixture():
    a,b,r=map(str,[uuid4(),uuid4(),uuid4()])
    source=SimpleNamespace(revision_id=uuid4(),chunks=[{'chunk_id':'p1-0','page':1,'page_start':0,'text':'Controller A operates equipment B.'}])
    model={'entities':[{'id':a,'attributes':[]},{'id':b,'attributes':[]}],'relations':[{'id':r,'source_type_id':a,'target_type_id':b}]}
    span={'chunk_id':'p1-0','start':0,'end':10,'excerpt':'Controller'}
    output={'entities':[{'key':'a','type_id':a,'type_name':'Controller','name':'A','evidence':[span]},{'key':'b','type_id':b,'type_name':'Equipment','name':'B','evidence':[span]}],'relations':[{'type_id':r,'type_name':'operates','source':'a','target':'b','evidence':[span]}]}
    return source,model,output

def test_relation_endpoints_are_stable_revision_ids():
    source,model,output=fixture();candidates,raw=validate_output(source,model,output)
    relation=candidates[2]
    assert relation.kind=='relation'
    assert relation.payload['source_candidate_id']==str(candidates[0].id)
    assert relation.payload['target_candidate_id']==str(candidates[1].id)
    assert relation.payload['source_candidate_revision']==1

@pytest.mark.parametrize('change',['span','chunk','type','endpoint','mismatch','attribute','duplicate','malformed'])
def test_malformed_or_unverified_output_rejected(change):
    source,model,output=fixture()
    if change=='span': output['entities'][0]['evidence'][0]['end']=11
    if change=='chunk': output['entities'][0]['evidence'][0]['chunk_id']='not-found'
    if change=='type': output['entities'][0]['type_id']=str(uuid4())
    if change=='endpoint': output['relations'][0]['target']='missing'
    if change=='mismatch': output['relations'][0]['target']='a'
    if change=='attribute': output['entities'][0]['attributes']={'unknown':'value'}
    if change=='duplicate': output['entities'][1]['key']='a'
    if change=='malformed': output['extra']='bad'
    with pytest.raises(ValueError): validate_output(source,model,output)

def test_object_integrity_and_safe_filename(tmp_path):
    store=ObjectStore(tmp_path);key=store.put(b'private content')
    assert store.put(b'private content')==key and store.get(key)==b'private content'
    name,chunks=parse(b'Valid text','../../unsafe\\safe.md')
    assert name=='safe.md'
    with pytest.raises(ValueError):store.get('../private')
    (tmp_path/key).write_bytes(b'corrupted')
    with pytest.raises(ValueError):store.get(key)

def test_text_pdf_pages_and_image_only_rejection():
    from io import BytesIO
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject,NameObject,DictionaryObject
    writer=PdfWriter();page=writer.add_blank_page(200,200)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 10 100 Td (Controller) Tj ET');page[NameObject('/Contents')]=writer._add_object(stream)
    out=BytesIO();writer.write(out)
    name,chunks=parse(out.getvalue(),'manual.pdf');assert chunks[0]['page']==1 and 'Controller' in chunks[0]['text']
    writer=PdfWriter();writer.add_blank_page(200,200);out=BytesIO();writer.write(out)
    with pytest.raises(InvalidSource,match='OCR'):parse(out.getvalue(),'scan.pdf')

def test_canonical_aliases_remain_scoped_and_ambiguity_visible():
    source,model,output=fixture()
    profile=str(uuid4());concept=str(uuid4());model['profile_id']=profile
    model['concepts']=[{'id':concept,'profile_id':profile,'name':'Device A','aliases':['A']},{'id':str(uuid4()),'profile_id':str(uuid4()),'name':'Other profile','aliases':['A']}]
    candidates,_=validate_output(source,model,output)
    assert candidates[0].payload['canonical_concept_id']==concept
    model['concepts'].append({'id':str(uuid4()),'profile_id':profile,'name':'Conflicting A','aliases':['A']})
    candidates,_=validate_output(source,model,output)
    assert candidates[0].payload['canonical_resolution']=='ambiguous'
    assert 'canonical_concept_id' not in candidates[0].payload
