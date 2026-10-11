from tests.security.test_profile_owners import setup, authenticate

def test_model_publication_and_exact_binding(client,db):
    ids=setup(client,db)
    p=client.post('/api/profiles',json={'kind':'product','name':'P','owner_id':ids['owner-a']}).json()['id']
    v=client.post(f'/api/profiles/{p}/versions',json={'label':'product-1'}).json()['id']
    r=client.post(f'/api/profiles/{p}/models',json={'semantic_description':'Controls'} )
    assert r.status_code==201
    m=r.json()['id']
    assert m!=v
    assert client.post(f'/api/models/{m}/publish').status_code==403
    authenticate(client,'owner-a')
    assert client.post(f'/api/models/{m}/publish').status_code==200
    assert client.put(f'/api/versions/{v}/model',json={'model_revision_id':m}).status_code==200
    assert client.patch(f'/api/models/{m}',json={'semantic_description':'changed'}).status_code==409


def test_definitions_qualification_and_database_immutability(client,db):
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    ids=setup(client,db)
    p=client.post('/api/profiles',json={'kind':'product','name':'P','owner_id':ids['owner-a']}).json()['id']
    authenticate(client,'owner-a')
    m=client.post(f'/api/profiles/{p}/models',json={}).json()['id']
    result=client.post(f'/api/models/{m}/entities',json={'name':'Controller','attributes':[{'name':'voltage','data_type':'number'}],'scores':{'identity':0.8,'retrieval_rationale':'independent lookup'}})
    assert result.status_code==201, result.text
    e=result.json()['entities'][0]['id']
    assert client.post(f'/api/models/{m}/publish').status_code==409
    assert client.post(f'/api/models/{m}/concepts',json={'name':'Controller','aliases':['PLC']}).status_code==201
    assert client.post(f'/api/models/{m}/relations',json={'name':'connects','source_type_id':e,'target_type_id':e}).status_code==201
    assert client.put(f'/api/models/{m}/entities/{e}/qualification',json={'qualification':'Independent lifecycle'}).status_code==200
    assert client.post(f'/api/models/{m}/publish').status_code==200
    assert client.get(f'/api/models/{m}/resolve',params={'label':' plc '}).json()['match']['name']=='Controller'
    with db.sessions() as s:
        for sql in ["UPDATE knowledge_model_revisions SET semantic_description='bad' WHERE id=:m", "UPDATE entity_types SET name='bad' WHERE model_revision_id=:m", "DELETE FROM canonical_concepts WHERE model_revision_id=:m", "DELETE FROM relation_types WHERE model_revision_id=:m", "INSERT INTO canonical_concepts (id,profile_id,model_revision_id,name,aliases,provenance) VALUES(gen_random_uuid(),:p,:m,'bad','[]','{}')"]:
            with pytest.raises(DBAPIError): s.execute(text(sql),{'m':m,'p':p}); s.commit()
            s.rollback()


def test_reader_contributor_and_stale_owner(client,db):
    from uuid import UUID
    from fastapi import HTTPException
    import pytest
    from knowledge_ai.governance.policy import Actor
    from knowledge_ai.profiles.models import Profile
    from knowledge_ai.ontology.service import publish_model
    ids=setup(client,db)
    p=client.post('/api/profiles',json={'kind':'product','name':'P','owner_id':ids['owner-a']}).json()['id']
    for name,grant in [('reader',{'read':True}),('contributor',{'contribute':True})]:
        assert client.put(f'/api/profiles/{p}/grants/{ids[name]}',json=grant).status_code==200
    authenticate(client,'contributor')
    m=client.post(f'/api/profiles/{p}/models',json={}).json()['id']
    assert client.post(f'/api/models/{m}/publish').status_code==403
    authenticate(client,'reader')
    assert client.get(f'/api/profiles/{p}/models').json()==[]
    assert client.get(f'/api/models/{m}').status_code==403
    assert client.post(f'/api/profiles/{p}/models',json={}).status_code==403
    authenticate(client,'owner-a')
    assert client.post(f'/api/models/{m}/publish').status_code==200
    authenticate(client,'reader')
    assert client.get(f'/api/models/{m}').status_code==200
    authenticate(client,'admin')
    m2=client.post(f'/api/profiles/{p}/models',json={}).json()['id']
    actor=Actor(UUID(ids['owner-a']),'owner',frozenset({UUID(p)}))
    assert client.patch(f'/api/profiles/{p}',json={'owner_id':ids['owner-b']}).status_code==200
    with db.sessions() as s:
        with pytest.raises(HTTPException) as error: publish_model(s,actor,UUID(m2))
        assert error.value.status_code==403
        s.rollback()
    assert client.post(f'/api/models/{m2}/publish').status_code==403


def test_cross_profile_links_require_runtime_authorization_and_alias_ambiguity(client,db):
    ids=setup(client,db)
    scopes=[]
    for name in ['A','B']:
        p=client.post('/api/profiles',json={'kind':'product','name':name,'owner_id':ids['owner-a']}).json()['id']
        scopes.append(p)
    authenticate(client,'owner-a')
    a,b=scopes
    bm=client.post(f'/api/profiles/{b}/models',json={}).json()['id']
    client.post(f'/api/models/{bm}/concepts',json={'name':'B Controller','aliases':['PLC']})
    client.post(f'/api/models/{bm}/publish')
    am=client.post(f'/api/profiles/{a}/models',json={}).json()['id']
    assert client.put(f'/api/models/{am}/links',json={'target_model_revision_ids':[bm]}).status_code==200
    assert client.post(f'/api/models/{am}/publish').status_code==200
    assert client.get(f'/api/models/{am}/resolve',params={'label':'PLC'}).json()['match']['profile_id']==b
    authenticate(client,'admin')
    client.put(f'/api/profiles/{a}/grants/{ids["reader"]}',json={'read':True})
    authenticate(client,'reader')
    assert client.get(f'/api/models/{am}/resolve',params={'label':'PLC'}).json()['match'] is None
    assert client.get(f'/api/models/{bm}').status_code==403
    authenticate(client,'owner-a')
    cm=client.post(f'/api/profiles/{a}/models',json={}).json()['id']
    for name in ['X','Y']: client.post(f'/api/models/{cm}/concepts',json={'name':name,'aliases':['plc']})
    client.post(f'/api/models/{cm}/publish')
    assert client.get(f'/api/models/{cm}/resolve',params={'label':'PLC'}).status_code==409


def test_definition_edit_invalidates_qualification_and_endpoint_scope(client,db):
    ids=setup(client,db)
    p=client.post('/api/profiles',json={'kind':'product','name':'P','owner_id':ids['owner-a']}).json()['id']
    authenticate(client,'owner-a')
    m=client.post(f'/api/profiles/{p}/models',json={}).json()['id']
    e=client.post(f'/api/models/{m}/entities',json={'name':'Motor'}).json()['entities'][0]['id']
    client.put(f'/api/models/{m}/entities/{e}/qualification',json={'qualification':'Entity'})
    assert client.put(f'/api/models/{m}/entities/{e}',json={'name':'Drive'}).status_code==200
    assert client.post(f'/api/models/{m}/publish').status_code==409
    m2=client.post(f'/api/profiles/{p}/models',json={}).json()['id']
    e2=client.post(f'/api/models/{m2}/entities',json={'name':'Other'}).json()['entities'][0]['id']
    assert client.post(f'/api/models/{m}/relations',json={'name':'links','source_type_id':e,'target_type_id':e2}).status_code==409
    c=client.post(f'/api/models/{m}/concepts',json={'name':'Motor','aliases':['M']}).json()['concepts'][0]['id']
    assert client.put(f'/api/models/{m}/concepts/{c}',json={'name':'Drive','aliases':['D']}).status_code==200
    assert client.delete(f'/api/models/{m}/concepts/{c}').status_code==200
    assert client.delete(f'/api/models/{m}/entities/{e}').status_code==200
    assert client.post(f'/api/models/{m}/publish').status_code==200
    assert client.post(f'/api/models/{m}/entities',json={'name':'Forbidden'}).status_code==409


def test_binding_scope_draft_and_released_guards(client,db):
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    ids=setup(client,db)
    profiles=[client.post('/api/profiles',json={'kind':'product','name':name,'owner_id':ids['owner-a']}).json()['id'] for name in ['P','Q']]
    p,q=profiles
    v=client.post(f'/api/profiles/{p}/versions',json={'label':'release'}).json()['id']
    authenticate(client,'owner-a')
    models=[client.post(f'/api/profiles/{key}/models',json={}).json()['id'] for key in profiles]
    m,other=models
    assert client.put(f'/api/versions/{v}/model',json={'model_revision_id':m}).status_code==409
    for key in models: assert client.post(f'/api/models/{key}/publish').status_code==200
    assert client.put(f'/api/versions/{v}/model',json={'model_revision_id':other}).status_code==409
    assert client.put(f'/api/versions/{v}/model',json={'model_revision_id':m}).json()['model_revision_id']==m
    with db.sessions() as s:
        with pytest.raises(DBAPIError): s.execute(text('UPDATE knowledge_versions SET model_revision_id=:m WHERE id=:v'),{'m':other,'v':v}); s.commit()
        s.rollback()
        s.execute(text("UPDATE knowledge_versions SET status='released' WHERE id=:v"),{'v':v}); s.commit()
        with pytest.raises(DBAPIError): s.execute(text('UPDATE knowledge_versions SET model_revision_id=NULL WHERE id=:v'),{'v':v}); s.commit()
        s.rollback()
    assert client.put(f'/api/versions/{v}/model',json={'model_revision_id':m}).status_code==409
