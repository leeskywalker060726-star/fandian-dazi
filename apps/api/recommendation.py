def snapshot_candidate(food, constraints, context, budget, minute_limit):
    """Historical observations produce candidates requiring confirmation, never guarantees."""
    total=food['price_cents']+(food['delivery_cents'] or 0)
    if total>budget: return None,'budget'
    delivery=food['delivery_min']
    parts={'采集时送达报价':delivery,'取餐（假设）':3,'用餐（假设）':15,'返回（假设）':5,'缓冲（假设）':5} if delivery else {}
    duration=sum(parts.values()) if parts else None
    if minute_limit and (duration is None or duration>minute_limit): return None,'time'
    reasons=[f'采集时已知费用 ¥{total/100:g} 起，包装费未提供']
    if food['delivery_cents'] is None: reasons.append('配送费用或优惠门槛需确认')
    if constraints.get('taste') or constraints.get('excluded_ingredients'):
        reasons.append('口味与忌口待商户确认，名称线索不等于完整配料')
    else: reasons.append('采集菜单中的正餐候选，当前营业与库存待确认')
    duration_score=duration if duration is not None else 120
    score=.55*(1-total/max(budget,1))+.45*max(0,1-duration_score/120)
    if constraints.get('sort')=='price': score=-total
    if constraints.get('sort')=='time': score=-duration_score
    return {**food,'total_cents':total,'total_min':duration,'time_parts':parts,
            'price_complete':False,'needs_confirmation':True,'party_size':constraints.get('party_size',1),
            'reasons':reasons,'score':score},None


def recommend(foods, constraints, context):
    candidates, counts = [], {'budget': 0, 'time': 0, 'closed': 0, 'excluded': 0}
    budget = constraints.get('budget_max', 25) * 100
    minute_limit = constraints.get('available_minutes') or context.get('available_minutes')
    hour = context.get('hour', 12)
    for food in foods:
        if not food['available'] or food['vendor_id'] in constraints.get('excluded_vendors', []):
            counts['excluded'] += 1
            continue
        if food['category'] in constraints.get('excluded_categories', []):
            counts['excluded'] += 1
            continue
        if any(x in food['ingredients'] for x in constraints.get('excluded_ingredients', [])):
            counts['excluded'] += 1
            continue
        if constraints.get('channel', 'all') not in ('all', food['channel']):
            continue
        if constraints.get('category') and food['category'] != constraints['category']:
            continue
        taste = constraints.get('taste', '')
        if (taste == '清淡' or '辣椒' in constraints.get('excluded_ingredients',[])) and (food['spice'] or 0) > 0:
            counts['excluded'] += 1
            continue
        if food.get('source_kind')=='meituan_snapshot':
            candidate,blocked=snapshot_candidate(food,constraints,context,budget,minute_limit)
            if candidate: candidates.append(candidate)
            elif blocked: counts[blocked]+=1
            continue
        total = food['price_cents'] + food['delivery_cents'] + food['packaging_cents']
        if total > budget:
            counts['budget'] += 1
            continue
        walk = max(2, food['walk_min'] + {'教学楼': 0, '图书馆': 2, '宿舍区': -2}.get(context.get('location'), 0))
        if food['channel'] == 'canteen':
            parts = {'步行': walk, '排队': food['queue_min'], '出餐': food['prep_min'], '用餐': 15, '返回': walk, '缓冲': 5}
            service = walk + food['queue_min'] + food['prep_min']
        else:
            parts = {'送达': food['delivery_min'], '取餐': 3, '用餐': 15, '返回': 5, '缓冲': 5}
            service = food['delivery_min']
        duration = sum(parts.values())
        current = hour * 60
        opening, closing = food['open_hour'] * 60, food['close_hour'] * 60
        if closing > 1440 and current < closing - 1440:
            current += 1440
        if current < opening or current + service >= closing or (food['channel'] == 'canteen' and current + service + 15 > closing):
            counts['closed'] += 1
            continue
        if minute_limit and duration > minute_limit:
            counts['time'] += 1
            continue
        reasons = [f'人均 ¥{total / 100:g}，在你的预算内']
        taste_score = 1 if taste and taste in food['tags'] else .5
        if taste and taste in food['tags']:
            reasons.append(f'符合你的{taste}偏好')
        if context.get('weather') == 'rainy' and food['covered']:
            reasons.append('演示路线有连廊，下雨少淋一段')
        if minute_limit:
            reasons.append(f'预计完整用餐 {duration} 分钟，预留 {minute_limit-duration} 分钟')
        score = .35*taste_score + .25*max(0, 1-duration/90) + .20*(1-total/max(budget,1)) + .1*(1 if food['covered'] and context.get('weather') == 'rainy' else .5) + .1
        if constraints.get('sort') == 'price':
            score = -total
        elif constraints.get('sort') == 'time':
            score = -duration
        candidates.append({**food, 'total_cents': total, 'total_min': duration, 'time_parts': parts,
                           'party_size': constraints.get('party_size', 1), 'reasons': reasons[:3], 'score': score})
    candidates.sort(key=lambda f: (-f['score'], f['id']))
    chosen, seen = [], set()
    for candidate in candidates:
        if candidate['vendor_id'] not in seen:
            chosen.append(candidate)
            seen.add(candidate['vendor_id'])
            if len(chosen) == 3:
                break
    for candidate in candidates:
        if len(chosen) == 3:
            break
        if candidate['id'] not in [x['id'] for x in chosen]:
            chosen.append(candidate)
    if chosen:
        answer = f'找到 {len(chosen)} 个待核实的采集菜单候选，实际费用、口味和营业状态需确认。' if chosen[0].get('needs_confirmation') else f'找到 {len(chosen)} 个符合当前条件的方案。'
    else:
        blockers = []
        if counts['closed']:
            blockers.append('部分档口已结束营业')
        if counts['time']:
            blockers.append('完整用餐时间超出限制')
        if counts['budget']:
            blockers.append('部分方案超出预算')
        if foods and all(f.get('source_kind')=='meituan_snapshot' for f in foods):
            answer='这批采集菜单里暂时没找到可列出的候选。这里只收录了外卖正餐，库存为零的采集记录不会列出；可以调整预算、时间或品类再看看。'
        else:
            answer = '暂时没有同时符合条件的方案。' + '；'.join(blockers) + '。你可以调整时间、预算或品类，我会保留你的忌口。'
    return chosen, answer
