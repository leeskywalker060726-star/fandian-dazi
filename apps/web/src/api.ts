export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch('/api/v1' + path, {credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...options.headers}})
  const data = await response.json()
  if(!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '输入格式不正确，请检查后再试')
  return data
}
export const post = <T = any>(path: string, data: unknown = {}) => api<T>(path,{method:'POST',body:JSON.stringify(data)})

export async function streamChat(data: unknown, onStatus: (s: string) => void) {
  const response = await fetch('/api/v1/chat/stream',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
  if(!response.ok || !response.body) throw new Error('连接失败，请刷新页面重试')
  const reader=response.body.getReader(), decoder=new TextDecoder()
  let buffer='', result: any
  while(true){
    const {done,value}=await reader.read()
    if(done) break
    buffer+=decoder.decode(value,{stream:true})
    let boundary: number
    while((boundary=buffer.indexOf('\n\n'))>=0){
      const block=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2)
      const event=block.split('\n').find(s=>s.startsWith('event:'))?.slice(6).trim()
      const payload=JSON.parse(block.split('\n').find(s=>s.startsWith('data:'))?.slice(5).trim() || '{}')
      if(event==='status') onStatus(payload.message)
      if(event==='error') throw new Error(payload.message)
      if(event==='done') result=payload
    }
  }
  if(!result) throw new Error('连接中断，请刷新查看本次结果后重试')
  return result
}
