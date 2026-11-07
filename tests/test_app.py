import io
import json
import os
import zipfile
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

TEST_DB = Path(__file__).resolve().parents[1] / '.runtime' / f'test_{uuid4().hex}.db'
os.environ['DATABASE_URL'] = 'sqlite:///' + TEST_DB.as_posix()
os.environ['USE_MYSQL'] = 'false'
os.environ['MCP_ENABLED'] = 'false'
os.environ['LLM_API_KEY'] = ''
os.environ['APP_MODE'] = 'demo'
os.environ['FANDIAN_CATALOG'] = 'demo'

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from apps.api.main import app
from apps.api.db import Memory, NarrativeMemory, User, Conversation, Session, engine, now
from apps.api.planner import rule_plan
from apps.api.recommendation import recommend
from apps.api.seed import catalog


def capture_fixture(count=1):
    """Entirely synthetic menu, safe to publish as a regression fixture."""
    from apps.api.catalog_import import build
    items=[{'id':str(i),'name':'番茄鸡蛋面','min_price':18.8,'skus':[{'stock':3,'price':18.8}]} for i in range(count)]
    menus={'captured_at':'2026-01-01T12:00:00','address':'测试校区','shops':[{'id':'test-shop','name':'测试面馆','items':items}]}
    shops={'captured_at':'2026-01-01T12:05:00','shops':[{'id':'test-shop','categories':['面馆'],'deliveryMinutes':20,'shippingFee':'免配送费'}]}
    return build(menus,shops)


@pytest.fixture
def snapshot_catalog(client):
    from apps.api.catalog_import import activate,use_demo
    from apps.api.db import Food
    from sqlalchemy import delete
    activate(capture_fixture())
    yield client
    use_demo()
    with Session.begin() as db:
        db.execute(delete(Food).where(Food.id.like('mt_%')))


def test_capture_filters_and_preserves_unknowns():
    from apps.api.catalog_import import build,ingredient_hints,shipping
    items=[
        {'id':'1','name':'牛肉拌面+例汤套餐','min_price':9,'skus':[{'stock':0,'price':9},{'stock':10,'price':19}]},
        {'id':'1','name':'重复牛肉拌面','min_price':9},
        {'id':'2','name':'凉拌黄瓜','min_price':11.8},
        {'id':'3','name':'加一份米粉','min_price':12},
        {'id':'4','name':'猪肉水饺','min_price':18,'skus':[{'stock':0,'price':18}]},
    ]
    doc=build({'captured_at':'2026-01-01','address':'测试','shops':[{'id':'s','name':'测试商户','items':items}]},
              {'shops':[{'id':'s','categories':['面馆'],'shippingFee':'满30配送约¥0'}]})
    assert len(doc['foods'])==2 and doc['metadata']['duplicates']==1
    first=doc['foods'][0]
    assert first['price_cents']==1900 and first['available'] is True
    assert all(first[k] is None for k in ['delivery_cents','packaging_cents','open_hour','spice','delivery_min'])
    assert doc['foods'][1]['available'] is False
    assert ingredient_hints('鲜肉包子与鸡蛋')==['鸡蛋']
    assert shipping('配送 ¥0')==0 and shipping('配送 ¥2.5')==250
    assert shipping('满22配送约¥0.8') is None


def test_capture_candidates_are_not_cost_or_diet_guarantees(snapshot_catalog):
    from apps.api.responder import food_references
    result,_=turn(snapshot_catalog,'想点外卖，预算25元')
    food=result['recommendations'][0]
    assert food['total_cents']==1880 and food['price_complete'] is False
    assert food['spice'] is None and food['needs_confirmation'] is True
    assert food['total_min']==48 and food['packaging_cents'] is None
    assert any('待核实' in n for n in result['notices'])
    assert '预算内' not in ''.join(food['reasons'])
    refs=food_references([food])[food['id']]
    assert '未知' in refs['spice'] and '未知包装费' in refs['price'] and '非实时' in refs['duration']
    assert not recommend(catalog(),{'budget_max':10},{})[0]
    assert not recommend(catalog(),{'budget_max':25,'available_minutes':40},{})[0]
    assert not recommend(catalog(),{'budget_max':25,'excluded_ingredients':['鸡蛋']},{})[0]


def test_import_is_idempotent_and_preserves_personal_data(client):
    from apps.api.catalog_import import activate,use_demo
    from apps.api.seed import catalog_info
    from apps.api.db import Food
    from sqlalchemy import delete,func
    old,_=turn(client,'吃什么')
    tables=(User,Memory,NarrativeMemory,Conversation)
    def counts():
        with Session() as db: return [db.scalar(select(func.count()).select_from(t)) for t in tables]
    before=counts()
    try:
        a=activate(capture_fixture());b=activate(capture_fixture())
        assert a==b and counts()==before and len(catalog())==1
        assert catalog_info()['mode']=='meituan_snapshot'
        assert client.get('/api/v1/conversations/latest').json()['recommendations']==[]
        assert client.post('/api/v1/conversations/'+old['id']+'/select',json={'food_id':old['recommendations'][0]['id'],'expected_version':old['version']}).status_code==409
        invalid=deepcopy(capture_fixture());invalid['foods'][0]['price_cents']=-1
        with pytest.raises(ValueError): activate(invalid)
        assert catalog_info()==a and counts()==before
        use_demo();assert len(catalog())==24 and counts()==before
    finally:
        use_demo()
        with Session.begin() as db: db.execute(delete(Food).where(Food.id.like('mt_%')))


def test_mcp_reads_full_active_catalog(snapshot_catalog,monkeypatch):
    import asyncio
    from apps.api.catalog_import import activate
    from apps.api.catalog_gateway import read_catalog
    from apps.food_mcp import search_foods
    activate(capture_fixture(521))
    page=search_foods(limit=20)
    assert len(page['foods'])==20 and page['total']==521 and page['next_offset']==20
    assert search_foods(campus_id='demo-campus')['foods']==[]
    monkeypatch.setenv('MCP_ENABLED','true')
    foods,mode=asyncio.run(read_catalog())
    assert mode=='mcp' and len(foods)==521


def test_updated_capture_invalidates_previous_choices(snapshot_catalog):
    from apps.api.catalog_import import activate
    result,_=turn(snapshot_catalog,'吃什么')
    updated=capture_fixture();updated['metadata']['captured_at']='2026-01-02T12:00:00'
    activate(updated)
    response=snapshot_catalog.post('/api/v1/conversations/'+result['id']+'/select',json={'food_id':result['recommendations'][0]['id'],'expected_version':result['version']})
    assert response.status_code==409
    reply,_=turn(snapshot_catalog,'刚才那个为什么推荐',result)
    assert not reply['recommendations']


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


def test_desktop_ignores_inherited_model_credentials(monkeypatch,tmp_path):
    from desktop.main import configure
    from desktop.settings import public
    for key in ('FANDIAN_DESKTOP','USE_MYSQL','DATABASE_URL','APP_MODE','MCP_ENABLED','FANDIAN_CATALOG'):
        monkeypatch.setenv(key,os.environ.get(key,''))
    monkeypatch.setenv('FANDIAN_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('LLM_API_KEY','INHERITED_TEST_KEY_NOT_REAL')
    monkeypatch.setenv('LLM_BASE_URL','https://example.invalid')
    monkeypatch.setenv('LLM_MODEL','inherited-model')
    configure()
    assert public()=={'base_url':'','model':'','key_configured':False}
    assert os.environ['LLM_API_KEY']=='' and os.environ['USE_MYSQL']=='false'
    assert not (tmp_path/'settings.json').exists()


def test_published_catalog_startup_and_persistent_demo(client,monkeypatch):
    from apps.api.catalog_import import load_startup_catalog,use_demo
    from apps.api.db import CatalogState,Food
    from apps.api.seed import catalog_info
    from sqlalchemy import delete
    monkeypatch.delenv('FANDIAN_CATALOG')
    with Session.begin() as db: db.execute(delete(CatalogState))
    try:
        load_startup_catalog()
        assert catalog_info()['mode']=='meituan_snapshot'
        assert len(catalog())==132 and sum(f['available'] for f in catalog())==42
        use_demo();load_startup_catalog()
        assert catalog_info()['mode']=='demo' and len(catalog())==24
    finally:
        use_demo()
        with Session.begin() as db: db.execute(delete(Food).where(Food.id.like('mt_%')))
