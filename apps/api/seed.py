from sqlalchemy import select
from .db import Base, CatalogState, Food, Session, engine

# All vendors, prices, ingredients and timings below are fictional demo fixtures.
VENDORS = [
    ('v1', '第一食堂 · 家常小灶', 'canteen', 5, 6, True, 7, 21),
    ('v2', '第二食堂 · 好好吃饭', 'canteen', 8, 4, True, 10, 21),
    ('v3', '南门 · 青禾轻食', 'delivery', 7, 5, False, 10, 22),
    ('v4', '第一食堂 · 面面俱到', 'canteen', 5, 5, True, 7, 22),
    ('v5', '宿舍区 · 深夜食堂', 'canteen', 3, 2, False, 17, 25),
    ('v6', '东门 · 小碗好味', 'delivery', 10, 8, False, 10, 23),
]
ITEMS = [
    ('番茄鸡蛋饭', 14, 'rice', 0, ['清淡','素食'], ['鸡蛋','番茄'], ['鸡蛋'], 'tomato'),
    ('香菇滑鸡饭', 16, 'rice', 0, ['清淡','高蛋白'], ['鸡肉','香菇'], ['大豆'], 'chicken'),
    ('土豆牛肉饭', 19, 'rice', 1, ['饱腹'], ['牛肉','土豆'], ['大豆'], 'beef'),
    ('两素一荤套餐', 12, 'rice', 0, ['清淡','饱腹'], ['猪肉','青菜','豆腐'], ['大豆'], 'bento'),
    ('清蒸鱼配米饭', 18, 'rice', 0, ['清淡','高蛋白'], ['鱼','米饭'], ['鱼'], 'fish'),
    ('西兰花鸡肉饭', 17, 'rice', 0, ['清淡','高蛋白'], ['鸡肉','西兰花'], ['大豆'], 'chicken'),
    ('麻婆豆腐饭', 13, 'rice', 2, ['麻辣'], ['豆腐','猪肉'], ['大豆'], 'tofu'),
    ('时蔬双拼饭', 11, 'rice', 0, ['清淡','素食'], ['青菜','香菇'], ['大豆'], 'green'),
    ('烤鸡轻食碗', 23, 'salad', 0, ['清淡','高蛋白'], ['鸡肉','玉米','生菜'], ['鸡蛋'], 'salad'),
    ('南瓜藜麦碗', 21, 'salad', 0, ['清淡','素食'], ['南瓜','藜麦'], [], 'salad'),
    ('金枪鱼谷物碗', 26, 'salad', 0, ['清淡','高蛋白'], ['金枪鱼','米饭'], ['鱼'], 'fish'),
    ('牛油果鸡蛋碗', 24, 'salad', 0, ['清淡','素食'], ['牛油果','鸡蛋'], ['鸡蛋'], 'green'),
    ('番茄鸡蛋面', 12, 'noodle', 0, ['清淡','素食'], ['鸡蛋','小麦','番茄'], ['鸡蛋','小麦'], 'noodle'),
    ('红烧牛肉面', 18, 'noodle', 1, ['饱腹'], ['牛肉','小麦','香菜'], ['小麦'], 'noodle'),
    ('酸辣粉', 10, 'noodle', 2, ['酸辣'], ['红薯粉','花生'], ['花生'], 'noodle'),
    ('菌菇汤面', 13, 'noodle', 0, ['清淡','素食'], ['香菇','小麦'], ['小麦'], 'noodle'),
    ('热汤小馄饨', 12, 'soup', 0, ['清淡'], ['猪肉','小麦'], ['小麦'], 'soup'),
    ('关东煮组合', 10, 'soup', 0, ['清淡'], ['萝卜','鱼丸'], ['鱼','大豆'], 'soup'),
    ('鲜肉小笼包', 9, 'bun', 0, ['饱腹'], ['猪肉','小麦'], ['小麦'], 'bun'),
    ('热豆浆与包子', 8, 'bun', 0, ['清淡','素食'], ['豆浆','小麦','青菜'], ['大豆','小麦'], 'bun'),
    ('照烧鸡腿饭', 20, 'rice', 0, ['饱腹','高蛋白'], ['鸡肉','米饭'], ['大豆'], 'chicken'),
    ('香辣鸡丁饭', 18, 'rice', 2, ['麻辣'], ['鸡肉','辣椒'], ['大豆'], 'chicken'),
    ('番茄炖牛腩饭', 24, 'rice', 0, ['饱腹'], ['牛肉','番茄'], ['大豆'], 'beef'),
    ('茉莉奶茶', 12, 'milk_tea', 0, ['甜口'], ['牛奶','茶'], ['牛奶'], 'tea'),
]


def initialize():
    Base.metadata.create_all(engine)
    with Session.begin() as db:
        if db.scalar(select(Food.id).limit(1)):
            return
        for index, item in enumerate(ITEMS):
            vendor = VENDORS[index // 4]
            name, price, category, spice, tags, ingredients, allergens, art = item
            vid, vname, channel, walk, queue, covered, opening, closing = vendor
            fid = f'food_{index + 1:02d}'
            db.add(Food(id=fid, data={
                'id': fid, 'name': name, 'vendor_id': vid, 'vendor': vname,
                'channel': channel, 'price_cents': price * 100,
                'delivery_cents': 300 if channel == 'delivery' else 0,
                'packaging_cents': 100 if channel == 'delivery' else 0,
                'category': category, 'spice': spice, 'tags': tags,
                'ingredients': ingredients, 'allergens': allergens,
                'cross_contact_known': False, 'walk_min': walk,
                'queue_min': queue, 'prep_min': 3, 'delivery_min': 32 + index % 3 * 4,
                'covered': covered, 'open_hour': opening, 'close_hour': closing,
                'available': True, 'art': art, 'source': '虚构校园演示目录',
                'campus_id': 'demo-campus', 'version': 1,
            }))


def catalog():
    with Session() as db:
        state=db.get(CatalogState,'active')
        real=bool(state and state.data.get('mode')=='meituan_snapshot')
        return [row.data for row in db.scalars(select(Food).order_by(Food.id))
                if (row.data.get('source_kind')=='meituan_snapshot')==real]


def catalog_info():
    with Session() as db:
        state=db.get(CatalogState,'active')
        return dict(state.data) if state else {'mode':'demo','digest':'demo','catalog_items':24,'candidate_items':24}
