"""Live conversational checks using a disposable guest, never the browser user's account."""
import io
import json
import zipfile
from pathlib import Path
from uuid import uuid4
import httpx

transcript=[]
with httpx.Client(base_url='http://127.0.0.1:8000/api/v1',timeout=65,trust_env=False) as client:
    client.post('/auth/guest').raise_for_status()
    try:
        client.post('/onboarding',json={'budget':25,'tags':['清淡','不吃香菜']}).raise_for_status()
        conversation=client.post('/conversations').json()
        def chat(text,kind):
            global conversation
            r=client.post('/chat',json={'conversation_id':conversation['id'],'expected_version':conversation['version'],'request_id':str(uuid4()),'text':text})
            r.raise_for_status()
            conversation=r.json()
            row={'user':text,'reply':conversation['messages'][-1]['content'],'intent':conversation['response_kind'],
                 'reply_mode':conversation['reply_mode'],'catalog_mode':conversation['catalog_mode'],'cards':len(conversation['recommendations'])}
            transcript.append(row)
            print(json.dumps(row,ensure_ascii=False),flush=True)
            assert conversation['response_kind'] in kind
            assert conversation['reply_mode']=='llm', 'Live conversational generation fell back'
            if conversation['response_kind'] in {'chat','answer','remember'}:
                assert not conversation['recommendations'] and conversation['catalog_mode']=='skipped'
            return conversation
        chat('你好呀，今天有点累，只想随便聊两句',{'chat'})
        chat('最近实验很多，我经常很晚才吃饭，排长队的时候就更烦了',{'chat'})
        m=client.get('/memories').json()
        assert m['pending'] and not m['narratives']
        confirmed=client.post('/narratives/'+m['pending'][0]['id']+'/confirm',json={'expected_version':m['version']})
        confirmed.raise_for_status()
        conversation=client.post('/conversations').json()
        remembered=chat('你还记得我最近为什么吃饭不想排队吗？',{'chat','answer'})
        assert '实验' in remembered['messages'][-1]['content']
        chat('帮我记住：我平时喜欢一个人安静吃饭，吃饭的时候不想一直说话。',{'remember','chat'})
        recommended=chat('今天想吃点清淡的，帮我选一顿午饭，最多20元',{'recommend'})
        assert recommended['recommendations'] and recommended['catalog_mode']=='mcp'
        assert all(f['total_cents']<=2000 and f['spice']==0 for f in recommended['recommendations'])
        chat('为什么你把第一个放前面？',{'answer'})
        chat('谢谢，你这么说我就明白了',{'chat'})
        m=client.get('/memories').json()
        assert len(m['narratives'])>=2
        archive=zipfile.ZipFile(io.BytesIO(client.get('/memories/export').content))
        assert '一个人安静吃饭' in archive.read('meal-preferences/references/about-me.md').decode()
        Path('docs/conversation-smoke.json').write_text(json.dumps(transcript,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Live chat, cross-session paragraph recall, recommendation and export passed.',flush=True)
    finally:
        client.delete('/me/data').raise_for_status()
        print('Disposable test account removed.',flush=True)
