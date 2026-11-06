"""Windows desktop configuration; model key is protected with per-user DPAPI."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
from urllib.parse import urlparse

class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_byte))]

def protect(value, decrypt=False):
    raw=base64.b64decode(value) if decrypt else value.encode()
    buffer=ctypes.create_string_buffer(raw)
    source=Blob(len(raw),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_byte)))
    output=Blob()
    fn=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(output)):
        raise OSError('Windows credential protection failed')
    try:
        result=ctypes.string_at(output.data,output.size)
        return result.decode() if decrypt else base64.b64encode(result).decode()
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(output.data,ctypes.c_void_p))

def path():
    return Path(os.environ['FANDIAN_DATA_DIR'])/'settings.json'

def read():
    return json.loads(path().read_text(encoding='utf-8')) if path().exists() else {}

def load():
    data=read()
    for key in ('LLM_BASE_URL','LLM_MODEL'):
        os.environ[key]=data.get(key,'')
    os.environ['LLM_API_KEY']=protect(data['protected_key'],True) if data.get('protected_key') else ''

def save(base_url,model,api_key=None,clear_key=False):
    base_url=base_url.strip().rstrip('/')
    parsed=urlparse(base_url)
    if base_url and (parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or (parsed.scheme=='http' and parsed.hostname not in ('localhost','127.0.0.1','::1'))):
        raise ValueError('请填写 HTTPS 模型接口地址；本机服务可使用 HTTP。')
    data=read()
    data.update(LLM_BASE_URL=base_url,LLM_MODEL=model.strip())
    if clear_key:
        data.pop('protected_key',None)
    elif api_key:
        data['protected_key']=protect(api_key.strip())
    temporary=path().with_suffix('.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    temporary.replace(path())
    load()

def public():
    return {'base_url':os.getenv('LLM_BASE_URL',''),'model':os.getenv('LLM_MODEL',''),'key_configured':bool(os.getenv('LLM_API_KEY'))}
