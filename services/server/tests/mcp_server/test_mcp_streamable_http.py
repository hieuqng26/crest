import asyncio, json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "http://localhost:8090/mcp"
HEADERS = {"Authorization": "Bearer dev-mcp-token-change-me"}

async def main():
    async with streamablehttp_client(URL, headers=HEADERS) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print(f"{len(tools.tools)} tools")
            res = await s.call_tool("crest_list_datasets", {"kind": "calibration"})
            print(res.content[0].text[:300])

asyncio.run(main())