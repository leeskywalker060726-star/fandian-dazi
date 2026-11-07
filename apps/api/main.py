from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
import secrets
import zipfile
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from . import memory
from .catalog_gateway import read_catalog
from .db import AuthSession, Conversation, Meal, Memory, NarrativeMemory, ROOT, Session, SkillSnapshot, Turn, User, now, uid
from .planner import plan_turn, explicit_remember, RECOMMEND_INTENTS
from .responder import compose_reply
from .recommendation import recommend
from .schemas import AuthInput, ChatInput, ContextInput, FeedbackInput, MemoryInput, Onboarding, SelectInput, Strict, NarrativeInput, VersionInput, TurnPlan
from .seed import catalog, catalog_info, initialize

hasher = PasswordHasher()
locks: dict[str, asyncio.Lock] = {}


def lock_for(user_id):
    return locks.setdefault(user_id, asyncio.Lock())


@asynccontextmanager
async def lifespan(app):
    initialize()
    from .catalog_import import load_startup_catalog
    load_startup_catalog()
    yield


app = FastAPI(title='饭点搭子 API', version='0.3.0', lifespan=lifespan)


@app.middleware('http')
async def security(request: Request, call_next):
    desktop_token=os.getenv('FANDIAN_DESKTOP_TOKEN')
    if desktop_token:
        supplied=request.headers.get('X-Desktop-Token') or request.cookies.get('fandian_desktop','')
        if request.url.path=='/desktop/start':
            if not secrets.compare_digest(request.query_params.get('token',''),desktop_token):
                return JSONResponse({'detail':'无效的桌面会话'},status_code=403)
            response=RedirectResponse('/')
            response.set_cookie('fandian_desktop',desktop_token,httponly=True,samesite='strict')
            response.headers['Referrer-Policy']='no-referrer'
            return response
        if not secrets.compare_digest(supplied,desktop_token):
            return JSONResponse({'detail':'请从桌面应用打开'},status_code=403)
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin:
        allowed = {str(request.base_url).rstrip('/'), 'http://127.0.0.1:5173', 'http://localhost:5173'}
        if origin not in allowed:
            return JSONResponse({'detail': '请求来源不允许'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


def get_user(request: Request):
    token = request.cookies.get('fandian_session')
    if not token:
        raise HTTPException(401, '请先登录')
    with Session() as db:
        session = db.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
        if not session or session.expires_at <= now():
            raise HTTPException(401, '登录已过期，请重新登录')
        user = db.get(User, session.user_id)
        if not user:
            raise HTTPException(401, '账号不存在')
        return user.id


def describe_user(user):
    return {'id': user.id, 'username': '校园体验官' if user.guest else user.username,
            'guest': user.guest, 'onboarded': user.onboarded, 'memory_enabled': user.memory_enabled,
            'version': user.version, 'settings': user.settings}


def issue_session(db, user, response):
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id, expires_at=now()+timedelta(days=7)))
    response.set_cookie('fandian_session', token, httponly=True, secure=os.getenv('APP_MODE') == 'production', samesite='lax', max_age=604800)


def owned_conversation(db, cid, user_id):
    conversation = db.get(Conversation, cid)
    if not conversation or conversation.user_id != user_id:
        raise HTTPException(404, '找不到这次对话')
    return conversation


def conversation_json(c):
    last = next((m for m in reversed(c.messages) if m['role'] == 'assistant'), {})
    current_catalog=last.get('catalog_revision','demo')==catalog_info().get('digest','demo')
    return {'id':c.id, 'version':c.version, 'state':c.state, 'messages':c.messages,
            'recommendations':c.recommendations if current_catalog and last.get('show_recommendations',True) else [], 'closed':c.closed,
            'response_kind':last.get('response_kind','recommend'), 'reply_mode':last.get('reply_mode'),
            'model_mode':last.get('model_mode'), 'catalog_mode':last.get('catalog_mode')}


def context_of(user):
    return {'weather':'sunny', 'hour':12, 'location':user.settings.get('location','教学楼'), 'available_minutes':None,
            **user.settings.get('context', {}), 'source':'演示场景'}


@app.get('/api/v1/health')
async def health():
    from .db import engine
    return {'status':'ok', 'database':engine.dialect.name, 'desktop':os.getenv('FANDIAN_DESKTOP')=='1', 'model_configured': bool(os.getenv('LLM_API_KEY') and os.getenv('LLM_MODEL') and os.getenv('LLM_BASE_URL')), 'data_mode':catalog_info()['mode']}


@app.get('/api/v1/catalog')
async def get_catalog_info():
    return catalog_info()


class DesktopConfig(Strict):
    base_url: str
    model: str
    api_key: str | None = None
    clear_key: bool = False


@app.get('/api/v1/desktop-config')
async def get_desktop_config():
    if not os.getenv('FANDIAN_DESKTOP_TOKEN'):
        raise HTTPException(404)
    from desktop.settings import public
    return public()


@app.put('/api/v1/desktop-config')
async def set_desktop_config(data: DesktopConfig):
    if not os.getenv('FANDIAN_DESKTOP_TOKEN'):
        raise HTTPException(404)
    from desktop.settings import save,public
    try:
        save(data.base_url,data.model,data.api_key,data.clear_key)
    except ValueError as exc:
        raise HTTPException(422,str(exc))
    return public()


@app.post('/api/v1/auth/register')
async def register(data: AuthInput, response: Response):
    try:
        with Session.begin() as db:
            user = User(username=data.username, password_hash=hasher.hash(data.password), settings={})
            db.add(user)
            db.flush()
            issue_session(db, user, response)
            return describe_user(user)
    except IntegrityError:
        raise HTTPException(409, '这个用户名已经被使用')


@app.post('/api/v1/auth/login')
async def login(data: AuthInput, response: Response):
    with Session.begin() as db:
        user = db.scalar(select(User).where(User.username == data.username, User.guest == False))
        try:
            if not user or not hasher.verify(user.password_hash, data.password):
                raise HTTPException(401, '用户名或密码不正确')
        except (VerificationError, InvalidHashError):
            raise HTTPException(401, '用户名或密码不正确')
        issue_session(db, user, response)
        return describe_user(user)


@app.post('/api/v1/auth/guest')
async def guest(response: Response):
    with Session.begin() as db:
        user = User(username='guest_' + uid(), guest=True, settings={})
        db.add(user)
        db.flush()
        issue_session(db, user, response)
        return describe_user(user)


@app.post('/api/v1/auth/logout')
async def logout(request: Request, response: Response):
    token = request.cookies.get('fandian_session', '')
    with Session.begin() as db:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    response.delete_cookie('fandian_session')
    return {'ok':True}


@app.get('/api/v1/me')
async def me(user_id=Depends(get_user)):
    with Session() as db:
        return describe_user(db.get(User, user_id))


@app.post('/api/v1/onboarding')
async def onboard(data: Onboarding, user_id=Depends(get_user)):
    allowed = {'清淡','麻辣','酸辣','不吃香菜','不吃牛肉','不吃羊肉','不吃辣','不喝奶茶','吃饱','省钱','吃好点','减脂','增肌'}
    if any(tag not in allowed for tag in data.tags):
        raise HTTPException(422, '包含不支持的标签')
    tastes = [tag for tag in data.tags if tag in {'清淡','麻辣','酸辣'}]
    if len(tastes) > 1 or ('不吃辣' in data.tags and any(t in data.tags for t in ['麻辣','酸辣'])):
        raise HTTPException(422, '请只选择一种主要口味，并检查不吃辣是否冲突')
    async with lock_for(user_id):
        with Session.begin() as db:
            user = db.get(User, user_id)
            if user.onboarded:
                raise HTTPException(409, '已完成初始设置，请到饮食记忆中修改')
            memory.upsert(db,user,'budget_max',data.budget)
            for tag in data.tags:
                if tag in {'清淡','麻辣','酸辣'}:
                    memory.upsert(db,user,'taste',tag)
                elif tag in {'吃饱','省钱','吃好点','减脂','增肌'}:
                    memory.upsert(db,user,'goal',tag)
                elif tag == '不喝奶茶':
                    memory.upsert(db,user,'exclude_category','milk_tea')
                elif tag == '不吃辣':
                    memory.upsert(db,user,'taste','清淡')
                else:
                    memory.upsert(db,user,'exclude_ingredient',tag[2:])
            user.onboarded, user.version = True, user.version+1
            user.settings = {**user.settings, 'location':data.location}
            memory.compile_skill(db,user)
            return describe_user(user)


@app.get('/api/v1/context')
async def context(user_id=Depends(get_user)):
    with Session() as db:
        return context_of(db.get(User,user_id))


@app.put('/api/v1/context')
async def update_context(data: ContextInput, user_id=Depends(get_user)):
    async with lock_for(user_id):
        with Session.begin() as db:
            user = db.get(User,user_id)
            user.settings = {**user.settings, 'context':data.model_dump()}
            return context_of(user)


@app.post('/api/v1/conversations')
async def new_conversation(user_id=Depends(get_user)):
    with Session.begin() as db:
        c = Conversation(user_id=user_id, state={}, messages=[], recommendations=[])
        db.add(c)
        db.flush()
        return conversation_json(c)


@app.get('/api/v1/conversations/latest')
async def latest(user_id=Depends(get_user)):
    with Session() as db:
        c = db.scalar(select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.created_at.desc()).limit(1))
        return conversation_json(c) if c else None


async def execute_chat(data, user_id):
    async with lock_for(user_id):
        turn_id = user_id + ':' + data.request_id
        fingerprint = hashlib.sha256(json.dumps(data.model_dump(), sort_keys=True).encode()).hexdigest()
        with Session() as db:
            old = db.get(Turn, turn_id)
            if old:
                if old.request_hash != fingerprint:
                    raise HTTPException(409, '重复请求标识对应了不同内容')
                return old.result
            c = owned_conversation(db,data.conversation_id,user_id)
            if c.closed or c.version != data.expected_version:
                raise HTTPException(409, '这次对话已经更新或结束，请刷新或开启新一餐')
            user = db.get(User,user_id)
            current = memory.effective(db,user,c.state)
            profile, revision = memory.context(db,user)
            history = memory.safe_history(c.messages,revision)
            catalog_revision=catalog_info().get('digest','demo')
            last=next((m for m in reversed(c.messages) if m['role']=='assistant'),{})
            if last.get('catalog_revision','demo')!=catalog_revision:
                history=[]
            state, scene = dict(c.state), context_of(user)
            previous = c.recommendations if history else []
            enabled = user.memory_enabled
            pending_notes=[memory.serialize_narrative(n) for n in memory.narratives(db,user_id,'pending')]
            active_quotes={n.quote for n in memory.narratives(db,user_id)}
        confirm_note=None
        confirm_request=re.fullmatch(r'(?:好的?[，,]?\s*)?(?:帮我)?(?:记住|保存|记下来|存下|存)(?:刚才)?(?:这段|这件事|这个|上面那段)?(?:吧|就好)?[。！!]*',data.text.strip())
        if enabled and pending_notes and confirm_request:
            if len(pending_notes)==1:
                confirm_note=pending_notes[0]
                plan,model_mode=TurnPlan(intent='remember'),'rules'
            else:
                plan,model_mode=TurnPlan(intent='clarify',clarification='有几段近况等你确认，请到「饮食记忆」里选一下要保存哪一段。'),'rules'
        else:
            plan, model_mode = await plan_turn(data.text,current,history,profile,previous)
        state.update(plan.patch.model_dump(exclude_none=True))
        notices, proposals = [], []
        projected = list(profile['facts'])
        for p in plan.proposals:
            if p.quote not in data.text:
                continue
            try:
                p.value=memory.validate_value(p.key,p.value)
            except ValueError:
                continue
            proposals.append(p)
            if enabled:
                def matches(row):
                    return row['key']==p.key and row['scope']==p.scope and (not p.key.startswith('exclude_') and p.operation!='delete' or row['value']==p.value)
                projected=[row for row in projected if not matches(row)]
                if p.operation!='delete':
                    projected.append({'key':p.key,'value':p.value,'scope':p.scope})
                state.pop(p.key,None)
                notices.append(('已取消：' if p.operation=='delete' else '已记住：')+memory.label(p.key,p.value)+('（本周有效）' if p.scope=='temporary' else ''))
            elif p.operation!='delete':
                state[p.key]=p.value
        narrative_proposals=[n for n in plan.narratives if n.quote not in active_quotes] if enabled else []
        save_directly=explicit_remember(data.text)
        if confirm_note:
            notices.append('已保存生活背景：'+confirm_note['title']+'（'+memory.scope_label(confirm_note['scope'])+'）')
        for n in narrative_proposals:
            notices.append(('已保存生活背景：' if save_directly else '待确认的记忆建议：')+n.title+('（'+memory.scope_label(n.scope)+'）' if save_directly else '，到饮食记忆中选择保存或忽略。'))
        if not enabled and (plan.proposals or plan.narratives):
            notices.append('长期记忆已关闭，这些内容只用于当前对话。')
        if plan.intent == 'another' and previous:
            state['excluded_vendors'] = list(set(state.get('excluded_vendors',[]) + [previous[0]['vendor_id']]))
        if plan.intent == 'cheaper':
            state['sort']='price'
            if previous:
                state['budget_max']=min(state.get('budget_max',500),max(1,(previous[0]['total_cents']-1)//100))
        if plan.intent == 'faster':
            state['sort']='time'
        constraints=memory.resolve(projected,enabled,state)
        show_cards=plan.intent in RECOMMEND_INTENTS
        foods,catalog_mode=await read_catalog() if show_cards else ([], 'skipped')
        recommendations,selection_summary=recommend(foods,constraints,scene) if show_cards else ([], '')
        reply_foods=recommendations if show_cards else previous if plan.intent=='answer' else []
        reply_profile={**profile,'facts':projected,'overview':memory.summarize(projected),'current_constraints':constraints}
        # Both network calls finish before the atomic write: a failed turn cannot half-save memory.
        answer,reply_mode=await compose_reply(data.text,plan,reply_foods,reply_profile,history,notices,selection_summary)
        if any(f.get('source_kind')=='meituan_snapshot' for f in reply_foods):
            notices.append('这些是采集菜单中的待核实候选：标价按采集时规格起价计算，未含未知包装费；配送费可能有门槛。营业、库存、口味和忌口需向商户确认。时间按历史送达报价估算，不保证当前可达。')
        if catalog_info().get('digest','demo')!=catalog_revision:
            raise HTTPException(409,'餐食目录刚刚更新，请重新发送这条消息')
        if model_mode=='fallback' or reply_mode=='fallback':
            notices.append('模型暂时未能完成本轮回复，已使用简短备用回复。')
        with Session.begin() as db:
            c=owned_conversation(db,data.conversation_id,user_id)
            user=db.get(User,user_id)
            if enabled:
                for p in proposals:
                    memory.upsert(db,user,p.key,p.value,p.scope,'对话明确表达',p.quote,p.operation)
                for n in narrative_proposals:
                    memory.add_narrative(db,user,n,active=save_directly)
                if confirm_note:
                    note=owned_note(db,confirm_note['id'],user_id)
                    note.status='active'
                    note.expires_at=memory.narrative_expiry(note.scope)
                if proposals or narrative_proposals or confirm_note:
                    user.version+=1
                    memory.compile_skill(db,user)
            _,saved_revision=memory.context(db,user)
            c.state,c.version=state,c.version+1
            if show_cards:
                c.recommendations=recommendations
            elif not previous:
                c.recommendations=[]
            c.messages=c.messages+[
                {'id':uid(),'role':'user','content':data.text,'memory_revision':saved_revision},
                {'id':uid(),'role':'assistant','content':answer,'notices':notices,'model_mode':model_mode,
                 'reply_mode':reply_mode,'catalog_mode':catalog_mode,'response_kind':plan.intent,
                 'show_recommendations':show_cards,'memory_revision':saved_revision,'catalog_revision':catalog_revision}]
            result={**conversation_json(c),'constraints':constraints,'notices':notices,'memory_version':user.version}
            db.add(Turn(id=turn_id,user_id=user_id,request_hash=fingerprint,result=result))
            return result


@app.post('/api/v1/chat')
async def chat(data: ChatInput, user_id=Depends(get_user)):
    return await execute_chat(data,user_id)


@app.post('/api/v1/chat/stream')
async def chat_stream(data: ChatInput, user_id=Depends(get_user)):
    async def events():
        yield 'event: status\ndata: ' + json.dumps({'message':'在听，正在想怎么接着聊…'},ensure_ascii=False) + '\n\n'
        try:
            result = await execute_chat(data,user_id)
            yield 'event: done\ndata: ' + json.dumps(result,ensure_ascii=False) + '\n\n'
        except HTTPException as exc:
            yield 'event: error\ndata: ' + json.dumps({'message':exc.detail,'status':exc.status_code},ensure_ascii=False) + '\n\n'
        except Exception:
            yield 'event: error\ndata: ' + json.dumps({'message':'暂时未能完成回复，请重试。'},ensure_ascii=False) + '\n\n'
    return StreamingResponse(events(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})


@app.get('/api/v1/memories')
async def get_memories(user_id=Depends(get_user)):
    with Session() as db:
        user = db.get(User,user_id)
        return {'version':user.version,'enabled':user.memory_enabled,
                'facts':[memory.serialize(m) for m in memory.facts(db,user_id)],
                'overview':memory.summarize([memory.serialize(m) for m in memory.facts(db,user_id)]),
                'narratives':[memory.serialize_narrative(n) for n in memory.narratives(db,user_id)],
                'pending':[memory.serialize_narrative(n) for n in memory.narratives(db,user_id,'pending')]}


@app.post('/api/v1/memories')
async def save_memory(data: MemoryInput, user_id=Depends(get_user)):
    async with lock_for(user_id):
        with Session.begin() as db:
            user = db.get(User,user_id)
            if user.version != data.expected_version:
                raise HTTPException(409,'偏好已更新，请刷新后重试')
            try:
                memory.upsert(db,user,data.key,data.value,data.scope)
            except ValueError as exc:
                raise HTTPException(422,str(exc))
            user.version += 1
            memory.compile_skill(db,user)
    return await get_memories(user_id)


@app.delete('/api/v1/memories/{memory_id}')
async def forget(memory_id: str, expected_version: int, user_id=Depends(get_user)):
    async with lock_for(user_id):
        with Session.begin() as db:
            user = db.get(User,user_id)
            if user.version != expected_version:
                raise HTTPException(409,'偏好已更新，请刷新后重试')
            row = db.get(Memory,memory_id)
            if not row or row.user_id != user_id:
                raise HTTPException(404,'找不到这条记忆')
            db.delete(row)
            user.version += 1
            memory.compile_skill(db,user)
            # Old turn results must not replay forgotten memory notices.
            db.execute(delete(Turn).where(Turn.user_id == user_id))
    return await get_memories(user_id)


@app.patch('/api/v1/memories/{memory_id}')
async def edit_memory(memory_id: str, data: MemoryInput, user_id=Depends(get_user)):
    async with lock_for(user_id):
        with Session.begin() as db:
            user = db.get(User,user_id)
            row = db.get(Memory,memory_id)
            if not row or row.user_id != user_id:
                raise HTTPException(404,'找不到这条记忆')
            if user.version != data.expected_version:
                raise HTTPException(409,'偏好已更新，请刷新后重试')
            try:
                memory.validate_value(data.key,data.value)
            except ValueError as exc:
                raise HTTPException(422,str(exc))
            db.delete(row)
            db.flush()
            memory.upsert(db,user,data.key,data.value,data.scope)
            user.version += 1
            memory.compile_skill(db,user)
    return await get_memories(user_id)


def owned_note(db, note_id, user_id):
    note=db.get(NarrativeMemory,note_id)
    if not note or note.user_id!=user_id:
        raise HTTPException(404,'找不到这段记忆')
    return note


def check_memory_version(user, version):
    if user.version!=version:
        raise HTTPException(409,'记忆已更新，请刷新后重试')


@app.post('/api/v1/narratives')
async def create_narrative(data: NarrativeInput, user_id=Depends(get_user)):
    async with lock_for(user_id):
        with Session.begin() as db:
            user=db.get(User,user_id)
            check_memory_version(user,data.expected_version)
            db.add(NarrativeMemory(user_id=user_id,title=data.title.strip(),content=data.content.strip(),
                scope=data.scope,expires_at=memory.narrative_expiry(data.scope)))
            user.version+=1
            memory.compile_skill(db,user)
    return await get_memories(user_id)


@app.patch('/api/v1/narratives/{note_id}')
async def edit_narrative(note_id: str, data: NarrativeInput, user_id=Depends(get_user)):
    async with lock_for(user_id):
        with Session.begin() as db:
            note=owned_note(db,note_id,user_id)
            user=db.get(User,user_id)
            check_memory_version(user,data.expected_version)
            note.title,note.content,note.scope=data.title.strip(),data.content.strip(),data.scope
            note.status,note.source='active','本人修改'
            note.quote=''
            note.expires_at=memory.narrative_expiry(data.scope)
            user.version+=1
            memory.compile_skill(db,user)
            db.execute(delete(Turn).where(Turn.user_id==user_id))
    return await get_memories(user_id)


@app.post('/api/v1/narratives/{note_id}/confirm')
async def confirm_narrative(note_id: str, data: VersionInput, user_id=Depends(get_user)):
    async with lock_for(user_id):
        with Session.begin() as db:
            note=owned_note(db,note_id,user_id)
            user=db.get(User,user_id)
            check_memory_version(user,data.expected_version)
            if note.expires_at and note.expires_at<=now():
                raise HTTPException(409,'这条建议已经过期，可以重新补充近况')
            note.status='active'
            note.expires_at=memory.narrative_expiry(note.scope)
            user.version+=1
            memory.compile_skill(db,user)
    return await get_memories(user_id)


@app.delete('/api/v1/narratives/{note_id}')
async def forget_narrative(note_id: str, expected_version: int, user_id=Depends(get_user)):
    async with lock_for(user_id):
        with Session.begin() as db:
            note=owned_note(db,note_id,user_id)
            user=db.get(User,user_id)
            check_memory_version(user,expected_version)
            db.delete(note)
            user.version+=1
            memory.compile_skill(db,user)
            db.execute(delete(Turn).where(Turn.user_id==user_id))
    return await get_memories(user_id)


class MemorySettings(Strict):
    enabled: bool
    expected_version: int


@app.patch('/api/v1/me/memory-settings')
async def memory_settings(data: MemorySettings, user_id=Depends(get_user)):
    async with lock_for(user_id):
        with Session.begin() as db:
            user = db.get(User,user_id)
            if user.version != data.expected_version:
                raise HTTPException(409,'偏好已更新，请刷新后重试')
            user.memory_enabled, user.version = data.enabled, user.version+1
            memory.compile_skill(db,user)
    return await get_memories(user_id)


@app.get('/api/v1/memories/export')
async def export_memory(user_id=Depends(get_user)):
    async with lock_for(user_id):
        with Session.begin() as db:
            snapshot = memory.compile_skill(db,db.get(User,user_id))
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
                for path, content in snapshot.bundle.items():
                    archive.writestr('meal-preferences/' + path,content)
            return Response(buffer.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="meal-preferences.zip"'})


@app.post('/api/v1/conversations/{cid}/select')
async def select_meal(cid: str, data: SelectInput, user_id=Depends(get_user)):
    async with lock_for(user_id):
        with Session.begin() as db:
            c = owned_conversation(db,cid,user_id)
            existing = db.scalar(select(Meal).where(Meal.conversation_id == cid))
            if existing:
                if existing.food['id'] != data.food_id:
                    raise HTTPException(409,'这一餐已经选择了其他方案')
                return {'id':existing.id,'food':existing.food}
            if c.version != data.expected_version:
                raise HTTPException(409,'推荐已更新，请刷新后选择')
            last=next((m for m in reversed(c.messages) if m['role']=='assistant'),{})
            if last.get('catalog_revision','demo')!=catalog_info().get('digest','demo'):
                raise HTTPException(409,'餐食目录已更新，请重新推荐后选择')
            food = next((x for x in c.recommendations if x['id'] == data.food_id),None)
            if not food:
                raise HTTPException(422,'请选择本轮推荐中的餐食')
            user = db.get(User,user_id)
            valid, _ = recommend([x for x in catalog() if x['id'] == data.food_id],memory.effective(db,user,c.state),context_of(user))
            if not valid or valid[0]['total_cents'] != food['total_cents']:
                raise HTTPException(409,'餐食或条件发生变化，请重新推荐')
            meal = Meal(user_id=user_id,conversation_id=cid,food=valid[0])
            db.add(meal)
            db.flush()
            c.closed = True
            return {'id':meal.id,'food':meal.food}


@app.get('/api/v1/meals')
async def meals(user_id=Depends(get_user)):
    with Session() as db:
        rows = db.scalars(select(Meal).where(Meal.user_id == user_id).order_by(Meal.created_at.desc())).all()
        return [{'id':m.id,'food':m.food,'eaten':m.eaten,'actual_cents':m.actual_cents,'feedback':m.feedback,'created_at':m.created_at.isoformat()+'Z'} for m in rows]


@app.patch('/api/v1/meals/{meal_id}')
async def feedback(meal_id: str, data: FeedbackInput, user_id=Depends(get_user)):
    with Session.begin() as db:
        meal = db.get(Meal,meal_id)
        if not meal or meal.user_id != user_id:
            raise HTTPException(404,'找不到这条记录')
        if data.actual_cents is not None and not data.eaten:
            raise HTTPException(422,'请先确认已经吃过，再记录实际支出')
        meal.eaten, meal.actual_cents, meal.feedback = data.eaten,data.actual_cents,data.feedback
        return {'ok':True}


@app.delete('/api/v1/me/data')
async def delete_data(response: Response, user_id=Depends(get_user)):
    async with lock_for(user_id):
        with Session.begin() as db:
            for cls in [AuthSession,Turn,Meal,Conversation,Memory,NarrativeMemory,SkillSnapshot]:
                db.execute(delete(cls).where(cls.user_id == user_id))
            db.execute(delete(User).where(User.id == user_id))
    response.delete_cookie('fandian_session')
    return {'ok':True}


dist = ROOT / 'dist'
if (dist / 'assets').exists():
    app.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')


@app.get('/')
async def index():
    if (dist/'index.html').exists():
        return FileResponse(dist/'index.html')
    return {'message':'前端尚未构建，请先运行前端构建，或使用开发服务器。','docs':'/docs'}
