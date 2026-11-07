import type { Food } from './types'

export const money=(cents:number|null)=>cents===null?'未提供':`¥${(cents/100).toFixed(cents%100?2:0)}`

export function FoodDetails({food}:{food:Food}){
  const snapshot=food.source_kind==='meituan_snapshot'
  return <>
    <p className="muted">{food.vendor} · {food.source}</p>
    {snapshot&&<p className="catalog-note">采集参考区域：{food.region}。这是历史菜单，当前营业与库存需向商户确认。</p>}
    <h4>{snapshot?'采集时费用构成':'费用构成'}</h4>
    <div className="breakdown">
      <span>菜品 {money(food.price_cents)}{snapshot?' 起':''}</span>
      <span>配送 {money(food.delivery_cents)}</span>
      <span>包装 {money(food.packaging_cents)}</span>
      <strong>{snapshot?'已知费用':'人均'} {money(food.total_cents)}{snapshot?' 起':''}</strong>
    </div>
    {snapshot&&<p className="muted">按采集时规格起价计算，未包含未知费用；实际下单可能超出预算。原配送标注：{food.shipping_text}。</p>}
    <h4>{snapshot?'按历史报价估算完整用餐':'完整用餐时间'} · {food.total_min===null?'时长未知':`${food.total_min} 分钟`}</h4>
    <div className="breakdown">{Object.entries(food.time_parts).map(([key,value])=><span key={key}>{key} {value} 分钟</span>)}</div>
    {snapshot&&<p className="muted">上述用餐、取餐、返回和缓冲时间为演示假设，不是实时路线或送达承诺。营业时间未提供。</p>}
    <h4>{snapshot?'菜名中的食材线索（非完整配料）':'演示原料信息'}</h4>
    <p>{food.ingredients.join('、')||'未提供配料信息'}</p>
    <div className="subtle-note">{snapshot?'未出现在菜名中不代表不含该食材；辣度与忌口需确认。':''}过敏原及交叉接触信息未核验，请向商户确认，不能据此判断过敏安全。</div>
  </>
}
