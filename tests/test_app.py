import io
import json
import os
import zipfile
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

TEST_DB = Path(__file__).resolve().parents[1] / '.runtime' / f'test_{uuid4().hex}.db'
os.environ['DATABASE_URL'] = 'sqlite:///' + TEST_DB.as_posix()
os.environ['USE_MYSQL'] = 'false'
os.environ['MCP_ENABLED'] = 'false'
os.environ['LLM_API_KEY'] = ''
os.environ['APP_MODE'] = 'demo'

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from apps.api.main import app
from apps.api.db import Memory, NarrativeMemory, User, Conversation, Session, engine, now
from apps.api.planner import rule_plan
from apps.api.recommendation import recommend
from apps.api.seed import catalog


@pytest.fixture
def client():
    with TestClient(app) as c:
        assert c.post('/api/v1/auth/guest').status_code == 200
        assert c.post('/api/v1/onboarding',json={'budget':25,'tags':['清淡','不吃香菜'],'location':'教学楼'}).status_code == 200
        yield c


@pytest.fixture(scope='session',autouse=True)
def cleanup():
    yield
    engine.dispose()
    if TEST_DB.parent.resolve() == (Path(__file__).resolve().parents[1] / '.runtime').resolve():
        TEST_DB.unlink(missing_ok=True)


def turn(c,text,conversation=None,request_id=None):
    conv = conversation or c.post('/api/v1/conversations').json()
    payload = {'conversation_id':conv['id'],'expected_version':conv['version'],'request_id':request_id or str(uuid4()),'text':text}
    r = c.post('/api/v1/chat',json=payload)
    assert r.status_code == 200, r.text
    return r.json(), payload


def test_recommendation_and_continuous_constraints(client):
    first,_=turn(client,'这顿最多20元，清淡点')
    assert first['recommendations']
    assert all(f['total_cents'] <= 2000 and '香菜' not in f['ingredients'] and f['spice']==0 for f in first['recommendations'])
    second,_=turn(client,'换一家',first)
    assert second['recommendations']
    assert all(f['vendor_id'] != first['recommendations'][0]['vendor_id'] for f in second['recommendations'])
    assert second['constraints']['budget_max']==20
    cheap,_=turn(client,'便宜点',second)
    assert all(f['total_cents']<second['recommendations'][0]['total_cents'] for f in cheap['recommendations'])


def test_memory_cross_session_and_expiry(client):
    result,_=turn(client,'这周每顿最多15，以后别推奶茶')
    assert result['constraints']['budget_max']==15
    assert 'milk_tea' in result['constraints']['excluded_categories']
    saved = client.get('/api/v1/memories').json()['facts']
    assert next(m for m in saved if m['key']=='exclude_category')['scope']=='persistent'
    another,_=turn(client,'吃什么')
    assert another['constraints']['budget_max']==15
    with Session.begin() as db:
        user_id=client.get('/api/v1/me').json()['id']
        row=db.scalar(select(Memory).where(Memory.user_id==user_id,Memory.scope=='temporary'))
        row.expires_at=now()-timedelta(seconds=1)
    after,_=turn(client,'吃什么')
    assert after['constraints']['budget_max']==25
    assert 'milk_tea' in after['constraints']['excluded_categories']


def test_forget_not_rehydrated_from_chat(client):
    turn(client,'以后别推奶茶')
    memories=client.get('/api/v1/memories').json()
    record=next(m for m in memories['facts'] if m['key']=='exclude_category')
    response=client.delete(f'/api/v1/memories/{record["id"]}?expected_version={memories["version"]}')
    assert response.status_code==200
    fresh,_=turn(client,'吃什么')
    assert fresh['constraints']['excluded_categories']==[]
    archive=zipfile.ZipFile(io.BytesIO(client.get('/api/v1/memories/export').content))
    profile=json.loads(archive.read('meal-preferences/references/profile.json'))
    assert not any(m['key']=='exclude_category' for m in profile['facts'])


def test_identity_isolation(client):
    conv=client.post('/api/v1/conversations').json()
    mem=client.get('/api/v1/memories').json()
    with TestClient(app) as other:
        other.post('/api/v1/auth/guest')
        r=other.post('/api/v1/chat',json={'conversation_id':conv['id'],'expected_version':0,'request_id':str(uuid4()),'text':'吃什么'})
        assert r.status_code==404
        r=other.delete(f'/api/v1/memories/{mem["facts"][0]["id"]}?expected_version=0')
        assert r.status_code==404


def test_request_deduplication_and_version(client):
    first,payload=turn(client,'不吃牛肉')
    before=client.get('/api/v1/memories').json()
    second=client.post('/api/v1/chat',json=payload).json()
    assert first==second
    assert client.get('/api/v1/memories').json()['version']==before['version']
    payload['text']='今天吃面'
    assert client.post('/api/v1/chat',json=payload).status_code==409
    payload['request_id']=str(uuid4())
    assert client.post('/api/v1/chat',json=payload).status_code==409


def test_selection_and_actual_spending(client):
    result,_=turn(client,'吃什么')
    food=result['recommendations'][0]
    path=f'/api/v1/conversations/{result["id"]}/select'
    data={'food_id':food['id'],'expected_version':result['version']}
    selected=client.post(path,json=data).json()
    assert client.post(path,json=data).json()['id']==selected['id']
    meals=client.get('/api/v1/meals').json()
    assert len(meals)==1 and not meals[0]['eaten'] and meals[0]['actual_cents'] is None
    assert client.patch('/api/v1/meals/'+selected['id'],json={'eaten':True,'actual_cents':1400,'feedback':'喜欢'}).status_code==200
    assert client.get('/api/v1/meals').json()[0]['actual_cents']==1400


def test_memory_edit_replaces_ingredient(client):
    data=client.get('/api/v1/memories').json()
    old=next(m for m in data['facts'] if m['value']=='香菜')
    result=client.patch('/api/v1/memories/'+old['id'],json={'key':'exclude_ingredient','value':'牛肉','scope':'persistent','expected_version':data['version']})
    assert result.status_code==200
    assert '香菜' not in [m['value'] for m in result.json()['facts']]
    assert '牛肉' in [m['value'] for m in result.json()['facts']]


def test_cancel_only_matching_goal(client):
    memories=client.get('/api/v1/memories').json()
    client.post('/api/v1/memories',json={'key':'goal','value':'增肌','expected_version':memories['version']})
    turn(client,'我不减脂了')
    assert any(m['key']=='goal' and m['value']=='增肌' for m in client.get('/api/v1/memories').json()['facts'])


def test_scope_per_clause():
    plan=rule_plan('今天最多20元，以后别推奶茶')
    assert plan.patch.budget_max==20
    assert plan.proposals[0].scope=='persistent'
    assert plan.patch.exclude_category is None


def test_negation_does_not_spread_to_other_foods():
    plan=rule_plan('不吃香菜，今天想喝奶茶')
    assert plan.patch.exclude_category is None
    assert not any(p.key=='exclude_category' for p in plan.proposals)


def test_turn_scope_does_not_change_profile(client):
    first,_=turn(client,'今天想吃麻辣，三个人吃')
    assert first['constraints']['party_size']==3
    assert first['constraints']['taste']=='麻辣'
    after,_=turn(client,'吃什么')
    assert after['constraints']['taste']=='清淡'
    assert 'party_size' not in after['constraints']


def test_memory_off(client):
    m=client.get('/api/v1/memories').json()
    assert client.patch('/api/v1/me/memory-settings',json={'enabled':False,'expected_version':m['version']}).status_code==200
    turn(client,'以后别推奶茶')
    assert not any(m['key']=='exclude_category' for m in client.get('/api/v1/memories').json()['facts'])
    later,_=turn(client,'吃什么')
    assert later['constraints']['excluded_categories']==[]


def test_authentication_and_csrf():
    with TestClient(app) as c:
        assert c.get('/api/v1/memories').status_code==401
        assert c.post('/api/v1/auth/guest',headers={'Origin':'https://untrusted.example'}).status_code==403
        username='test_'+uuid4().hex[:12]
        assert c.post('/api/v1/auth/register',json={'username':username,'password':'test-only-password'}).status_code==200
        c.post('/api/v1/auth/logout')
        assert c.get('/api/v1/me').status_code==401
        assert c.post('/api/v1/auth/login',json={'username':username,'password':'wrong-password'}).status_code==401
        assert c.post('/api/v1/auth/login',json={'username':username,'password':'test-only-password'}).status_code==200


@pytest.mark.parametrize('text',['我对花生过敏','他说不吃香菜','如果我不吃牛肉呢','想要400大卡的饭'])
def test_ambiguous_or_unverified_constraints(text):
    plan=rule_plan(text)
    assert plan.intent=='clarify'
    assert plan.proposals==[]


def test_time_budget_and_closed_catalog(client):
    rows=catalog()
    result,_=recommend(rows,{'budget_max':5},{'hour':12})
    assert result==[]
    result,_=recommend(rows,{'budget_max':25,'available_minutes':15},{'hour':12})
    assert result==[]
    result,_=recommend(rows,{'budget_max':25},{'hour':23})
    assert result and all(f['vendor_id']=='v5' for f in result)
    result,_=recommend(rows,{'budget_max':25},{'hour':2})
    assert result==[]


def test_sse_and_account_removal(client):
    conv=client.post('/api/v1/conversations').json()
    r=client.post('/api/v1/chat/stream',json={'conversation_id':conv['id'],'expected_version':0,'request_id':str(uuid4()),'text':'吃什么'})
    assert r.status_code==200 and 'event: status' in r.text and 'event: done' in r.text
    assert client.delete('/api/v1/me/data').status_code==200
    assert client.get('/api/v1/memories').status_code==401


def test_greeting_and_personal_context_do_not_force_food_cards(client,monkeypatch):
    import apps.api.main as main
    async def unexpected_catalog():
        raise AssertionError('Casual chat must not fetch the catalog')
    monkeypatch.setattr(main,'read_catalog',unexpected_catalog)
    hello,_=turn(client,'你好呀')
    assert hello['response_kind']=='chat' and not hello['recommendations']
    assert hello['catalog_mode']=='skipped'
    assert '麻婆豆腐' not in hello['messages'][-1]['content']
    context,_=turn(client,'最近实验有点多，经常很晚才吃饭',hello)
    assert context['response_kind']=='chat' and not context['recommendations']
    mem=client.get('/api/v1/memories').json()
    assert len(mem['pending'])==1 and mem['narratives']==[]


def test_explicit_paragraph_memory_and_export(client):
    paragraph='我最近实验很多，晚上经常很晚才吃饭，不喜欢在食堂长时间排队。'
    result,_=turn(client,'帮我记住：'+paragraph)
    mem=client.get('/api/v1/memories').json()
    assert not result['recommendations']
    assert mem['narratives'][0]['content']==paragraph
    assert mem['narratives'][0]['scope']=='recent'
    assert mem['pending']==[]
    archive=zipfile.ZipFile(io.BytesIO(client.get('/api/v1/memories/export').content))
    assert paragraph in archive.read('meal-preferences/references/about-me.md').decode()
    assert '平时' in mem['overview']
    assert client.post('/api/v1/chat',json={'conversation_id':result['id'],'request_id':str(uuid4()),'expected_version':result['version'],'text':'吃什么'}).status_code==200


def test_pending_confirmation_edit_delete_and_isolation(client):
    from apps.api import memory
    result,_=turn(client,'最近实验很多，经常很晚才吃饭')
    m=client.get('/api/v1/memories').json()
    note=m['pending'][0]
    user_id=client.get('/api/v1/me').json()['id']
    with Session() as db:
        assert memory.context(db,db.get(User,user_id))[0]['narratives']==[]
    with TestClient(app) as other:
        other.post('/api/v1/auth/guest')
        assert other.post('/api/v1/narratives/'+note['id']+'/confirm',json={'expected_version':0}).status_code==404
        assert other.delete('/api/v1/narratives/'+note['id']+'?expected_version=0').status_code==404
    saved=client.post('/api/v1/narratives/'+note['id']+'/confirm',json={'expected_version':m['version']})
    assert saved.status_code==200 and len(saved.json()['narratives'])==1 and saved.json()['pending']==[]
    edited=client.patch('/api/v1/narratives/'+note['id'],json={'title':'作息恢复了','content':'这周实验结束了，我的作息已经恢复正常。','scope':'temporary','expected_version':saved.json()['version']})
    assert edited.status_code==200 and edited.json()['narratives'][0]['source']=='本人修改'
    assert client.delete('/api/v1/narratives/'+note['id']+'?expected_version='+str(m['version'])).status_code==409
    deleted=client.delete('/api/v1/narratives/'+note['id']+'?expected_version='+str(edited.json()['version']))
    assert deleted.status_code==200 and deleted.json()['narratives']==[]
    with Session() as db:
        profile,revision=memory.context(db,db.get(User,user_id))
        assert profile['narratives']==[]
        assert memory.safe_history(db.get(Conversation,result['id']).messages,revision)==[]


def test_narrative_expiry_and_memory_off(client):
    from apps.api import memory
    result,_=turn(client,'帮我记住：最近实验很多，晚上经常很晚才吃饭')
    user_id=client.get('/api/v1/me').json()['id']
    with Session.begin() as db:
        note=db.scalar(select(NarrativeMemory).where(NarrativeMemory.user_id==user_id))
        note.expires_at=now()-timedelta(seconds=1)
    with Session() as db:
        profile,revision=memory.context(db,db.get(User,user_id))
        assert profile['narratives']==[]
        assert memory.safe_history(db.get(Conversation,result['id']).messages,revision)==[]
    m=client.get('/api/v1/memories').json()
    client.patch('/api/v1/me/memory-settings',json={'enabled':False,'expected_version':m['version']})
    turn(client,'帮我记住：平时晚饭喜欢一个人安静地慢慢吃')
    assert client.get('/api/v1/memories').json()['narratives']==[]


def test_follow_up_uses_previous_foods_and_chat_keeps_context(client,monkeypatch):
    import apps.api.main as main
    from apps.api.schemas import TurnPlan
    first,_=turn(client,'吃什么')
    observed={}
    async def plan(text,state,history,profile,previous):
        observed.update(history=history,profile=profile,previous=previous)
        return TurnPlan(intent='answer'),'llm'
    async def reply(text,plan,foods,profile,history,notices,summary):
        assert foods[0]['id']==first['recommendations'][0]['id']
        assert history[-1]['role']=='assistant'
        return '因为它符合你想吃清淡一点的偏好。','llm'
    monkeypatch.setattr(main,'plan_turn',plan)
    monkeypatch.setattr(main,'compose_reply',reply)
    after,_=turn(client,'为什么推荐第一个',first)
    assert after['catalog_mode']=='skipped' and not after['recommendations']
    assert observed['history'][0]['content']=='吃什么'
    assert observed['previous'] and observed['profile']['facts']
    assert after['messages'][-1]['content']=='因为它符合你想吃清淡一点的偏好。'


def test_catalog_references_cannot_invent_prices():
    from apps.api.responder import ground_text
    assert ground_text('试试 {{food_1.name}}，人均 {{food_1.price}}。',{'food_1':{'name':'番茄鸡蛋面','price':'12 元'}})=='试试 番茄鸡蛋面，人均 12 元。'
    with pytest.raises(ValueError):
        ground_text('这家只要 2 元。',{})
    with pytest.raises(ValueError):
        ground_text('推荐 {{invented_food.name}}。',{})


def test_travel_minutes_are_not_meal_deadline():
    assert rule_plan('我平时走路要15分钟到实验室').patch.available_minutes is None
    assert rule_plan('只有40分钟吃饭').patch.available_minutes==40
    assert rule_plan('最近实验很多，我的晚饭经常拖到很晚').intent=='chat'
    assert rule_plan('帮我记住：最近实验很多，晚饭经常很晚才吃').intent=='remember'


def test_blank_narrative_rejected(client):
    m=client.get('/api/v1/memories').json()
    assert client.post('/api/v1/narratives',json={'title':' ','content':' '*12,'expected_version':m['version']}).status_code==422


def test_confirm_pending_paragraph_in_chat(client):
    first,_=turn(client,'最近实验很多，经常很晚才吃饭')
    confirmed,_=turn(client,'帮我记住刚才这段吧',first)
    m=client.get('/api/v1/memories').json()
    assert not m['pending'] and len(m['narratives'])==1
    assert m['narratives'][0]['content']=='最近实验很多，经常很晚才吃饭'
    assert confirmed['response_kind']=='remember' and not confirmed['recommendations']


def test_desktop_gate_and_model_config(client,monkeypatch,tmp_path):
    monkeypatch.setenv('FANDIAN_DESKTOP_TOKEN','desktop-test-token')
    monkeypatch.setenv('FANDIAN_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('LLM_API_KEY','')
    monkeypatch.setenv('LLM_BASE_URL','')
    monkeypatch.setenv('LLM_MODEL','')
    assert client.get('/api/v1/health').status_code==403
    assert client.get('/desktop/start?token=wrong').status_code==403
    assert client.get('/desktop/start?token=desktop-test-token').status_code==200
    assert client.get('/api/v1/health').status_code==200
    invalid=client.put('/api/v1/desktop-config',json={'base_url':'http://external.example/v1','model':'test'})
    assert invalid.status_code==422
    if os.name=='nt':
        saved=client.put('/api/v1/desktop-config',json={'base_url':'https://example.com/v1','model':'test','api_key':'TEST_KEY_NOT_REAL'})
        assert saved.status_code==200 and saved.json()['key_configured']
        assert 'TEST_KEY_NOT_REAL' not in saved.text
        assert 'TEST_KEY_NOT_REAL' not in (tmp_path/'settings.json').read_text()
        from desktop.settings import load
        load()
        assert os.environ['LLM_API_KEY']=='TEST_KEY_NOT_REAL'
        cleared=client.put('/api/v1/desktop-config',json={'base_url':'','model':'','clear_key':True})
        assert cleared.status_code==200 and not cleared.json()['key_configured']
