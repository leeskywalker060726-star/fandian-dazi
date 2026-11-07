from mcp.server.fastmcp import FastMCP
from apps.api.seed import catalog, catalog_info

server = FastMCP('饭点搭子餐食目录')


@server.tool()
def search_foods(campus_id: str = '', limit: int = 500, offset: int = 0) -> dict:
    """查询当前启用的目录。采集快照不是实时商品；null 字段表示未知。支持分页，只读。"""
    foods=[f for f in catalog() if not campus_id or f['campus_id']==campus_id]
    start=max(0,offset); end=start+max(1,min(limit,500))
    return {'foods':foods[start:end],'total':len(foods),'next_offset':end if end<len(foods) else None,'catalog':catalog_info()}


@server.tool()
def get_food_details(food_id: str) -> dict:
    """按已知餐食 ID 查询详情。"""
    return next((f for f in catalog() if f['id'] == food_id), {'error':'not_found'})


if __name__ == '__main__':
    server.run(transport='stdio')
