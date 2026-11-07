"""Offline menu adapter. Observations, guesses and unknowns remain distinct."""
import hashlib
import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MEAL = re.compile(r'饭盒|便当|盖饭|盖浇|拌面|汤面|炒面|拉面|拉条|刀削|小面|米粉|羊肉粉|牛肉粉|臊子|凉皮|米皮|面皮|馄饨|云吞|水饺|蒸饺|饺子|炒饭|鸡腿饭|鸡肉饭|牛肉饭|肉夹馍|粥|米饭|套餐|全家福|(?:饭|面|粉)(?:[（(【+]|$)')
ADDON = re.compile(r'收藏|収藏|福利|商品券|加料|小料|加购|单点不送|仅限|限一份|加碗里|加粉里|放粉里|放碗里|炒粉里|默认炒入|默认加|再加|加米粉|加一份|餐盒|打包费|配送费|^加.*(?:粉|饭)|^例汤|^米饭$')


def cents(value):
    if value is None or isinstance(value,bool): return None
    try:
        number=Decimal(str(value))
        if not number.is_finite() or number<=0 or number>2000: return None
        return int((number*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    except (InvalidOperation,ValueError):
        return None


def shipping(text):
    text=str(text or '')
    if re.search(r'满|约|起',text): return None
    if text=='免配送费': return 0
    match=re.fullmatch(r'配送\s*[¥￥]\s*(\d+(?:\.\d+)?)',text)
    return (0 if Decimal(match.group(1))==0 else cents(match.group(1))) if match else None


def ingredient_hints(name):
    # Do not infer pork from “肉”, buns from “包”, or chicken from “鸡蛋”.
    patterns={'牛肉':r'牛肉|牛腩|牛杂|牛肚','猪肉':r'猪肉|猪肝|猪蹄|五花肉|培根|火腿',
              '羊肉':r'羊肉','鸡肉':r'鸡肉|鸡腿|鸡胸|鸡杂|鸡丁','鸡蛋':r'鸡蛋|荷包蛋|煎蛋|卤蛋',
              '牛奶':r'牛奶|乳|芝士|奶油|酸奶','鱼':r'鱼','花生':r'花生',
              '香菜':r'香菜','辣椒':r'辣椒|泡椒|双椒'}
    return [key for key,pattern in patterns.items() if re.search(pattern,name)]


def build(menus,shops):
    if not isinstance(menus.get('shops'),list) or not isinstance(shops.get('shops'),list):
        raise ValueError('需要包含 shops 数组的菜单和商户文件')
    meta={s['id']:s for s in shops['shops']}
    stats=Counter();rows=[];seen=set()
    captured=str(menus.get('captured_at',''))
    region=str(menus.get('address','未提供采集区域'))
    for shop in menus['shops']:
        info=meta.get(shop['id'],{})
        category=(info.get('categories') or ['未知'])[0]
        for item in shop.get('items',[]):
            stats['raw_items']+=1
            identity=(str(shop['id']),str(item['id']))
            if identity in seen:
                stats['duplicates']+=1;continue
            seen.add(identity)
            name=' '.join(str(item.get('name','')).split())
            price=cents(item.get('min_price'))
            if price is None:
                stats['invalid_price']+=1;continue
            if category=='奶茶':
                stats['drinks']+=1;continue
            if price<800 or ADDON.search(name) or not MEAL.search(name):
                stats['side_addon_or_uncertain_meal']+=1;continue
            skus=item.get('skus') or []
            stock_values=[s.get('stock') for s in skus]
            # Zero stock is a snapshot observation, never a statement about today.
            zero=bool(skus) and all(isinstance(n,(int,float)) and n==0 for n in stock_values)
            if zero: stats['zero_stock_at_capture']+=1
            positive=[s for s in skus if isinstance(s.get('stock'),(int,float)) and s['stock']>0 and cents(s.get('price'))]
            if positive: price=min(cents(s['price']) for s in positive)
            delivery=info.get('deliveryMinutes')
            if not isinstance(delivery,int) or not 1<=delivery<=240: delivery=None
            cat='noodle' if re.search(r'面|粉|凉皮|米皮|面皮',name) else 'bun' if re.search(r'饺|馄饨|包子|肉夹馍',name) else 'rice'
            spicy=bool(re.search(r'辣|麻椒|藤椒|椒麻|花椒|双椒|泡椒',name))
            fid='mt_'+hashlib.sha256('/'.join(identity).encode()).hexdigest()[:20]
            rows.append({'id':fid,'name':name,'vendor_id':'mt_'+hashlib.sha256(identity[0].encode()).hexdigest()[:16],
                'vendor':str(shop['name']),'channel':'delivery','price_cents':price,
                'delivery_cents':shipping(info.get('shippingFee')),'packaging_cents':None,
                'category':cat,'spice':2 if spicy else None,'tags':['名称含辣味提示'] if spicy else ['口味待确认'],
                'ingredients':ingredient_hints(name),'allergens':[],'cross_contact_known':False,
                'delivery_min':delivery,'walk_min':None,'queue_min':None,'prep_min':None,'covered':False,
                'open_hour':None,'close_hour':None,'available':not zero,'art':{'noodle':'noodle','bun':'bun','rice':'bento'}[cat],
                'source_kind':'meituan_snapshot','source':'美团菜单采集快照 · '+captured[:10],
                'captured_at':captured,'delivery_captured_at':shops.get('captured_at'),
                'region':region,'campus_id':'fudan-beiyuan','version':2,'meal_kind':'main',
                'shipping_text':info.get('shippingFee','未提供'),'availability_status':'zero_stock_at_capture' if zero else 'not_live',
                'field_status':{'price':'observed_sku_starting_price','packaging':'unknown','hours':'unknown',
                    'ingredients':'name_hints_only','spice':'name_hint' if spicy else 'unknown','delivery':'historical_quote'},
                'rating':info.get('rating'),'distance':info.get('distance'),'shop_category':category})
    report={**stats,'menu_shops':len(menus['shops']),'shops_in_source':len(shops['shops']),
            'catalog_items':len(rows),'candidate_items':sum(r['available'] for r in rows),
            'vendors':len({r['vendor_id'] for r in rows}),'captured_at':captured,'region':region}
    return {'schema_version':2,'source':'meituan_snapshot','metadata':report,'foods':rows}


def validate(document):
    if not isinstance(document,dict) or document.get('schema_version')!=2 or document.get('source')!='meituan_snapshot':
        raise ValueError('不是受支持的目录快照格式，请先用导入脚本转换')
    rows=document.get('foods')
    if not isinstance(rows,list) or not rows or len(rows)>10000: raise ValueError('目录数量无效')
    seen=set()
    for row in rows:
        if not isinstance(row,dict): raise ValueError('餐食条目格式无效')
        for key in ('id','name','vendor_id','vendor','category','art','source','captured_at','region','shipping_text','campus_id'):
            if not isinstance(row.get(key),str) or not row[key] or len(row[key])>1000: raise ValueError('餐食文本字段无效：'+key)
        if not re.fullmatch(r'mt_[a-f0-9]{20}',row['id']) or row['id'] in seen: raise ValueError('餐食 ID 无效或重复')
        seen.add(row['id'])
        if row.get('source_kind')!='meituan_snapshot' or type(row.get('price_cents')) is not int or not 0<row['price_cents']<=200000:
            raise ValueError('目录价格或来源无效')
        if row.get('packaging_cents') is not None or row.get('open_hour') is not None or row.get('close_hour') is not None:
            raise ValueError('此适配器不允许将缺失的包装费或营业时间补成事实')
        if row.get('channel')!='delivery' or type(row.get('available')) is not bool or row.get('spice') not in (None,2):
            raise ValueError('渠道、库存或口味字段无效')
        for key,maximum in (('delivery_cents',200000),('delivery_min',240)):
            value=row.get(key)
            if value is not None and (type(value) is not int or not 0<=value<=maximum): raise ValueError('配送字段无效')
        for key in ('tags','ingredients','allergens'):
            if not isinstance(row.get(key),list) or any(not isinstance(v,str) or len(v)>100 for v in row[key]): raise ValueError('标签或原料字段无效')
    metadata=document.get('metadata')
    if not isinstance(metadata,dict) or not isinstance(metadata.get('captured_at'),str) or not isinstance(metadata.get('region'),str):
        raise ValueError('缺少采集时间与参考区域')
    return rows


def activate(document):
    from sqlalchemy import select
    from .db import CatalogState,Food,Session
    rows=validate(document)
    digest=hashlib.sha256(json.dumps(document,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    with Session.begin() as db:
        state=db.get(CatalogState,'active')
        if state and state.data.get('digest')==digest: return state.data
        old=db.scalars(select(Food)).all()
        wanted={r['id'] for r in rows}
        for item in old:
            if item.data.get('source_kind')=='meituan_snapshot' and item.id not in wanted: db.delete(item)
        for row in rows:
            item=db.get(Food,row['id'])
            if item: item.data=row
            else: db.add(Food(id=row['id'],data=row))
        metadata={k:v for k,v in document['metadata'].items() if k in {'raw_items','duplicates','invalid_price','drinks','side_addon_or_uncertain_meal','zero_stock_at_capture','menu_shops','shops_in_source','captured_at','region'}}
        data={**metadata,'mode':'meituan_snapshot','digest':digest,'catalog_items':len(rows),
              'candidate_items':sum(r['available'] for r in rows),'vendors':len({r['vendor_id'] for r in rows})}
        if state: state.data=data
        else: db.add(CatalogState(id='active',data=data))
        return data


def use_demo():
    from .db import CatalogState,Session
    with Session.begin() as db:
        state=db.get(CatalogState,'active')
        data={'mode':'demo','digest':'demo','catalog_items':24,'candidate_items':24}
        if state: state.data=data
        else: db.add(CatalogState(id='active',data=data))


def load_startup_catalog():
    """A fresh install uses the published snapshot; explicit choices persist."""
    import os
    from pathlib import Path
    from .db import ROOT,CatalogState,Session
    configured=os.getenv('FANDIAN_CATALOG','')
    if configured=='demo':
        use_demo();return
    if configured:
        activate(json.loads(Path(configured).read_text(encoding='utf-8')));return
    with Session() as db:
        chosen=db.get(CatalogState,'active') is not None
    default=ROOT/'data'/'catalog_meituan.json'
    if not chosen and default.is_file():
        activate(json.loads(default.read_text(encoding='utf-8')))
