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
        if taste == '清淡' and food['spice'] > 0:
            counts['excluded'] += 1
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
        answer = f'找到 {len(chosen)} 个符合当前条件的方案。'
    else:
        blockers = []
        if counts['closed']:
            blockers.append('部分档口已结束营业')
        if counts['time']:
            blockers.append('完整用餐时间超出限制')
        if counts['budget']:
            blockers.append('部分方案超出预算')
        answer = '暂时没有同时符合条件的方案。' + '；'.join(blockers) + '。你可以调整时间、预算或品类，我会保留你的忌口。'
    return chosen, answer
