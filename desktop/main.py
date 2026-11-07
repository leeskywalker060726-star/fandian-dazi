"""Entry point shared by the desktop window and its hidden MCP worker."""
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time

def configure():
    os.environ['FANDIAN_DESKTOP']='1'
    directory=Path(os.environ.get('FANDIAN_DATA_DIR',str(Path(os.environ.get('LOCALAPPDATA',Path.home()))/'FandianDazi')))
    directory.mkdir(parents=True,exist_ok=True)
    os.environ['FANDIAN_DATA_DIR']=str(directory)
    # Distributed desktop never loads the developer's .env or MySQL credentials.
    os.environ['USE_MYSQL']='false'
    os.environ['DATABASE_URL']='sqlite:///'+(directory/'fandian.db').as_posix()
    os.environ['APP_MODE']='demo'
    os.environ['MCP_ENABLED']='true'
    # Optional offline catalog stays outside the public executable bundle.
    portable=Path(sys.executable).parent/'catalog.json' if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent/'data/local/catalog_meituan.json'
    local=directory/'catalog.json'
    if not os.getenv('FANDIAN_CATALOG'):
        if local.is_file(): os.environ['FANDIAN_CATALOG']=str(local)
        elif portable.is_file(): os.environ['FANDIAN_CATALOG']=str(portable)
    from desktop.settings import load
    load()
    return directory

def main():
    directory=configure()
    if '--food-mcp' in sys.argv:
        from apps.food_mcp import server
        server.run(transport='stdio')
        return
    # Windowed binaries have no stdout; logging must not depend on a console.
    log=open(directory/'desktop.log','a',encoding='utf-8',buffering=1)
    if sys.stdout is None: sys.stdout=log
    if sys.stderr is None: sys.stderr=log
    import uvicorn
    from apps.api.main import app
    secret=secrets.token_urlsafe(32)
    os.environ['FANDIAN_DESKTOP_TOKEN']=secret
    sock=socket.socket()
    sock.bind(('127.0.0.1',0))
    port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_config=None,access_log=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
    thread.start()
    for _ in range(300):
        if server.started: break
        if not thread.is_alive(): raise RuntimeError('Local backend failed to start')
        time.sleep(.1)
    else: raise RuntimeError('Local backend startup timed out')
    if '--smoke-test' in sys.argv:
        import httpx,json
        from uuid import uuid4
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',headers={'X-Desktop-Token':secret},trust_env=False,timeout=35) as c:
            assert httpx.get(f'http://127.0.0.1:{port}/api/v1/health',trust_env=False).status_code==403
            c.post('/api/v1/auth/guest').raise_for_status()
            c.post('/api/v1/onboarding',json={'budget':25,'tags':['清淡']}).raise_for_status()
            conv=c.post('/api/v1/conversations').json()
            result=c.post('/api/v1/chat',json={'conversation_id':conv['id'],'expected_version':0,'request_id':str(uuid4()),'text':'吃什么'}).json()
            assert result['recommendations'] and result['catalog_mode']=='mcp',result.get('catalog_mode')
            health=c.get('/api/v1/health').json()
            if os.getenv('FANDIAN_EXPECT_UNCONFIGURED')=='1':
                assert health['model_configured'] is False
                assert result['model_mode']=='rules' and result['reply_mode']=='rules'
            info=c.get('/api/v1/catalog').json()
            if os.getenv('FANDIAN_EXPECT_CATALOG'):
                assert info['mode']==os.environ['FANDIAN_EXPECT_CATALOG']
            assert c.get('/').status_code==200
            c.delete('/api/v1/me/data').raise_for_status()
            (directory/'smoke-result.json').write_text(json.dumps({'passed':True,'catalog_mode':result['catalog_mode'],'data_mode':info['mode'],'model_configured':health['model_configured'],'database':'sqlite'}),encoding='utf-8')
    else:
        import webview
        webview.create_window('饭点搭子',f'http://127.0.0.1:{port}/desktop/start?token={secret}',width=1280,height=850,min_size=(780,600),background_color='#f7f8f2')
        try:
            webview.settings['ALLOW_DOWNLOADS']=True
            webview.start(gui='edgechromium',private_mode=False,storage_path=str(directory/'webview'))
        finally:
            server.should_exit=True
            thread.join(timeout=8)
    server.should_exit=True
    thread.join(timeout=8)
    sock.close()

if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    try:
        main()
    except Exception:
        import traceback
        directory=Path(os.environ.get('FANDIAN_DATA_DIR','.'))
        (directory/'startup-error.log').write_text(traceback.format_exc(),encoding='utf-8')
        if '--smoke-test' not in sys.argv and '--food-mcp' not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,'启动失败。请确认已安装 Microsoft Edge WebView2 Runtime。详细信息保存在应用数据目录的 startup-error.log。','饭点搭子',16)
        raise
