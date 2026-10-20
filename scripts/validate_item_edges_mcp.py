"""Exercise the isolated port-8766 host through MCP stdio; never target the live bridge."""
import asyncio
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

OUT = Path('.local/edges-validation')


async def main():
    request = json.loads((OUT / 'request.json').read_text())
    evidence = {}
    params = StdioServerParameters(command='uv', args=['run', 'python', str(OUT / 'mcp_server.py')], cwd=str(Path.cwd()))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            evidence['registered'] = any(t.name == 'set_item_edges' for t in tools.tools)
            result = await session.call_tool('set_item_edges', {**request, 'start_seconds': 4.5, 'end_seconds': 9})
            evidence['success_response'] = result.model_dump(mode='json', by_alias=True)
            assert not result.is_error
            failed = await session.call_tool('set_item_edges', {**request, 'start_seconds': 0})
            evidence['error_response'] = failed.model_dump(mode='json', by_alias=True)
            assert failed.is_error
            restored = await session.call_tool('set_item_edges', request)
            assert not restored.is_error
            evidence['success'] = evidence['registered']
    (OUT / 'mcp-validation.json').write_text(json.dumps(evidence, indent=2))
    assert evidence['success']
    print('MCP registry, successful mutation, isError=true failure and restoration passed')


if __name__ == '__main__':
    asyncio.run(main())
