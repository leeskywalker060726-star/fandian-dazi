"""Verify the running app using a disposable account, then remove only that account."""
from uuid import uuid4
import httpx

with httpx.Client(base_url='http://127.0.0.1:8000/api/v1',timeout=65,trust_env=False) as client:
    health=client.get('/health').json()
    print('Backend database:',health['database'])
    created=False
    try:
        client.post('/auth/guest').raise_for_status()
        created=True
        client.post('/onboarding',json={'budget':25,'tags':['清淡','不吃香菜'],'location':'教学楼'}).raise_for_status()
        conversation=client.post('/conversations').json()
        r=client.post('/chat',json={'conversation_id':conversation['id'],'expected_version':0,'request_id':str(uuid4()),'text':'这周每顿最多15，以后别推奶茶，顺便推荐午饭'})
        r.raise_for_status()
        turn=r.json()
        assert turn['recommendations']
        assert turn['constraints']['budget_max']==15
        assert all(f['total_cents']<=1500 for f in turn['recommendations'])
        print('Catalog transport:',turn['catalog_mode'])
        assert turn['catalog_mode']=='mcp', 'The live MCP path did not succeed.'
        print('Model mode:',turn['model_mode'])
        if health['model_configured']:
            assert turn['model_mode']=='llm', 'Configured model did not complete the tool call.'
        facts=client.get('/memories').json()['facts']
        assert next(f for f in facts if f['key']=='exclude_category')['scope']=='persistent'
        assert next(f for f in facts if f['key']=='budget_max' and f['scope']=='temporary')['value']==15
        selected=client.post('/conversations/'+conversation['id']+'/select',json={'expected_version':turn['version'],'food_id':turn['recommendations'][0]['id']})
        selected.raise_for_status()
        client.patch('/meals/'+selected.json()['id'],json={'eaten':True,'actual_cents':1200,'feedback':'喜欢'}).raise_for_status()
        assert client.get('/meals').json()[0]['actual_cents']==1200
        assert client.get('/memories/export').headers['content-type']=='application/zip'
        print('Live MySQL, MCP, memory, selection, feedback and export checks passed.')
    finally:
        if created:
            cleanup=client.delete('/me/data')
            cleanup.raise_for_status()
            print('Disposable test account removed.')
