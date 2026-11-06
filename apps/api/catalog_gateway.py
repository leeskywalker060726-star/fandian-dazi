import asyncio
import json
import os
import sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .db import ROOT
from .seed import catalog


async def read_catalog():
    if os.getenv('MCP_ENABLED', 'true').lower() == 'false':
        return catalog(), 'direct'
    try:
        async with asyncio.timeout(8):
            frozen=getattr(sys,'frozen',False)
            command=str(Path(sys.executable).with_name('FandianWorker.exe')) if frozen else sys.executable
            params = StdioServerParameters(command=command, args=['--food-mcp'] if frozen else ['-m', 'apps.food_mcp'], cwd=str(ROOT), env=dict(os.environ))
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    listing = await client.list_tools()
                    if 'search_foods' not in [tool.name for tool in listing.tools]:
                        raise ValueError('Missing catalog tool')
                    result = await client.call_tool('search_foods', {'campus_id':'demo-campus','limit':40})
                    if result.isError:
                        raise ValueError('Catalog unavailable')
                    payload = result.structuredContent
                    if not payload:
                        payload = json.loads(next(x.text for x in result.content if x.type == 'text'))
                    return payload['foods'], 'mcp'
    except Exception:
        # A visible direct-repository fallback keeps the demo usable.
        return catalog(), 'fallback'
