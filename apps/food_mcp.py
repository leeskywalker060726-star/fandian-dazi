from mcp.server.fastmcp import FastMCP
from apps.api.seed import catalog

server = FastMCP('饭点搭子餐食目录')


@server.tool()
def search_foods(campus_id: str = 'demo-campus', limit: int = 40) -> dict:
    """查询演示校园餐食目录，返回菜品、原料、价格及时间字段。只读工具。"""
    return {'foods': [f for f in catalog() if f['campus_id'] == campus_id][:max(1,min(limit,40))], 'source': 'demo'}


@server.tool()
def get_food_details(food_id: str) -> dict:
    """按已知餐食 ID 查询详情。"""
    return next((f for f in catalog() if f['id'] == food_id), {'error':'not_found'})


if __name__ == '__main__':
    server.run(transport='stdio')
