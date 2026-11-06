import { useState } from 'react'
import { BookOpen, Check, Plus, Trash2, X } from 'lucide-react'
import { api } from './api'
import type { Memories, NarrativeMemory } from './types'

const scopeName=(scope:string)=>({persistent:'长期记住',temporary:'本周有效',recent:'保留七天'}[scope]||scope)

export function MemoryStories({memories,onChange,onError}:{memories:Memories;onChange:(m:Memories)=>void;onError:(e:unknown)=>void}) {
  const [draft,setDraft]=useState<{id:string;title:string;content:string;scope:string}|null>(null)
  const [saving,setSaving]=useState(false)
  async function change(path:string,method:string,body?:unknown){
    setSaving(true)
    try{onChange(await api<Memories>(path,{method,...(body?{body:JSON.stringify(body)}:{})}));return true}
    catch(e){onError(e);const latest=await api<Memories>('/memories').catch(()=>null);if(latest)onChange(latest);return false}
    finally{setSaving(false)}
  }
  async function save(){
    if(!draft)return
    if(await change(draft.id==='new'?'/narratives':'/narratives/'+draft.id,draft.id==='new'?'POST':'PATCH',{
      title:draft.title.trim(),content:draft.content.trim(),scope:draft.scope,expected_version:memories.version}))setDraft(null)
  }
  function card(n:NarrativeMemory,pending=false){return <article className={'story-memory '+(pending?'pending':'')} key={n.id}>
    <div className="story-memory-heading"><h3>{n.title}</h3><span>{pending?'等你确认':scopeName(n.scope)}</span></div>
    <p>{n.content}</p><div className="story-memory-meta">{pending?'来自这次聊天，还没有加入长期记忆':`来自${n.source}`}{n.expires_at&&!pending?' · '+new Date(n.expires_at).toLocaleDateString('zh-CN')+' 到期':''}</div>
    <div className="story-memory-actions">{pending?<>
      <button className="secondary" disabled={saving} onClick={()=>void change('/narratives/'+n.id+'/confirm','POST',{expected_version:memories.version})}><Check size={14}/>保存这段记忆</button>
      <button className="text-button" disabled={saving} onClick={()=>void change(`/narratives/${n.id}?expected_version=${memories.version}`,'DELETE')}>暂不记住</button>
    </>:<><button className="text-button" disabled={saving} onClick={()=>setDraft(n)}>编辑段落</button><button className="text-button" disabled={saving} onClick={()=>void change(`/narratives/${n.id}?expected_version=${memories.version}`,'DELETE')}><Trash2 size={14}/>忘记这段</button></>}</div>
  </article>}
  return <section className="memory-stories">
    <div className="memory-overview"><span className="little-label">现在，我这样了解你</span><p>{memories.overview}</p>{!memories.enabled&&<small>记忆已暂停，下面保存的资料暂不用于聊天。</small>}</div>
    {!!memories.pending.length&&<><div className="section-row"><h3>这段话，要帮你记住吗？<span>{memories.pending.length} 条待确认</span></h3></div><div className="story-memory-list">{memories.pending.map(n=>card(n,true))}</div></>}
    <div className="section-row"><h3><BookOpen size={17}/> 关于我，不止是标签</h3><button className="text-button" onClick={()=>setDraft({id:'new',title:'',content:'',scope:'persistent'})}><Plus size={15}/>补充一段</button></div>
    <p className="section-description">生活节奏、习惯背后的原因，或者最近的一个小计划。用你自己的话说就好。</p>
    {memories.narratives.length?<div className="story-memory-list">{memories.narratives.map(n=>card(n))}</div>:<div className="story-memory-empty">例如：我晚上经常在实验室待到很晚，吃饭希望少排队，能一个人安静吃完就好。</div>}
    {draft&&<div className="modal-backdrop" onClick={()=>!saving&&setDraft(null)}><section className="modal" role="dialog" aria-modal="true" aria-label="写一段关于我的记忆" onClick={e=>e.stopPropagation()}>
      <div className="modal-heading"><h2>写一段关于我的记忆</h2><button className="icon-button" aria-label="关闭段落编辑" disabled={saving} onClick={()=>setDraft(null)}><X size={20}/></button></div>
      <form onSubmit={e=>{e.preventDefault();void save()}}>
        <label>给这段记忆起个名字<input required maxLength={40} value={draft.title} onChange={e=>setDraft({...draft,title:e.target.value})} placeholder="比如：最近的实验室生活"/></label>
        <label>用自己的话写下来<textarea required minLength={8} maxLength={2000} rows={6} value={draft.content} onChange={e=>setDraft({...draft,content:e.target.value})} placeholder="我最近……这会影响我吃饭的时间，因为……"/></label>
        <label>这段背景保留多久<select value={draft.scope} onChange={e=>setDraft({...draft,scope:e.target.value})}><option value="persistent">长期记住</option><option value="recent">从现在起保留七天</option><option value="temporary">仅本周</option></select></label>
        <button className="primary wide" disabled={saving||draft.content.trim().length<8||!draft.title.trim()}>{saving?'正在保存…':'保存这段记忆'}<Check size={16}/></button>
      </form>
    </section></div>}
  </section>
}
