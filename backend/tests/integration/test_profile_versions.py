from sqlalchemy import select
from knowledge_ai.governance.policy import Actor
from knowledge_ai.db import User
from tests.security.test_profile_owners import setup


def test_pins_immutable_and_archive(client, db):
    ids = setup(client,db)
    product = client.post('/api/profiles',json={'kind':'product','name':'P','owner_id':ids['owner-a']}).json()['id']
    project = client.post('/api/profiles',json={'kind':'project','name':'J','owner_id':ids['owner-b']}).json()['id']
    pv = client.post(f'/api/profiles/{product}/versions',json={'label':'1'}).json()['id']
    jv = client.post(f'/api/profiles/{project}/versions',json={'label':'1'}).json()['id']
    assert client.put(f'/api/versions/{jv}/dependencies',json={'product_version_ids':[pv]}).status_code == 409
    # Task 9 supplies verified release; fixture models an already verified product release.
    from knowledge_ai.profiles.models import KnowledgeVersion
    with db.sessions() as s:
        s.get(KnowledgeVersion,pv).status = 'released'
        s.commit()
    assert client.put(f'/api/versions/{jv}/dependencies',json={'product_version_ids':[pv]}).status_code == 200
    client.post(f'/api/profiles/{product}/versions',json={'label':'2','predecessor_id':pv})
    assert client.get(f'/api/versions/{jv}').json()['product_version_ids'] == [pv]
    assert client.patch(f'/api/versions/{pv}',json={'label':'changed'}).status_code == 409
    assert client.patch(f'/api/versions/{pv}',json={'status':'archived'}).status_code == 200
    assert client.get(f'/api/versions/{jv}').json()['product_version_ids'] == [pv]
    assert client.patch(f'/api/versions/{jv}',json={'status':'released'}).status_code == 409
    assert client.post(f'/api/profiles/{project}/versions',json={'label':'1'}).status_code == 409
    assert client.post(f'/api/profiles/{project}/versions',json={'label':'2','predecessor_id':pv}).status_code == 409


def test_multiple_product_pins_and_database_immutability(client,db):
    from knowledge_ai.profiles.models import KnowledgeVersion, ProjectDependency
    from sqlalchemy import update, delete
    from sqlalchemy.exc import DBAPIError
    import pytest
    ids=setup(client,db)
    pins=[]
    for name in ['P1','P2']:
        p=client.post('/api/profiles',json={'kind':'product','name':name,'owner_id':ids['owner-a']}).json()['id']
        pins.append(client.post(f'/api/profiles/{p}/versions',json={'label':'1'}).json()['id'])
    j=client.post('/api/profiles',json={'kind':'project','name':'J','owner_id':ids['owner-b']}).json()['id']
    v=client.post(f'/api/profiles/{j}/versions',json={'label':'1'}).json()['id']
    with db.sessions() as s:
        for key in pins: s.get(KnowledgeVersion,key).status='released'
        s.commit()
    assert client.put(f'/api/versions/{v}/dependencies',json={'product_version_ids':pins}).status_code==200
    with db.sessions() as s:
        s.get(KnowledgeVersion,v).status='released'; s.commit()
    assert client.put(f'/api/versions/{v}/dependencies',json={'product_version_ids':[]}).status_code==409
    with db.sessions() as s:
        with pytest.raises(DBAPIError):
            s.execute(update(KnowledgeVersion).where(KnowledgeVersion.id==v).values(label='changed')); s.commit()
        s.rollback()
        with pytest.raises(DBAPIError):
            s.execute(delete(ProjectDependency).where(ProjectDependency.project_version_id==v)); s.commit()
        s.rollback()
        with pytest.raises(DBAPIError):
            s.execute(delete(KnowledgeVersion).where(KnowledgeVersion.id==v)); s.commit()
        s.rollback()
    successor=client.post(f'/api/profiles/{j}/versions',json={'label':'2','predecessor_id':v})
    assert successor.status_code==201
    assert successor.json()['product_version_ids']==sorted(pins)
    assert client.patch(f'/api/versions/{v}',json={'status':'archived'}).status_code==200
    assert client.get(f'/api/versions/{v}').json()['product_version_ids']==sorted(pins)
