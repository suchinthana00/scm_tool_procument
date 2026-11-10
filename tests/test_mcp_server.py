import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_mcp_server_exposes_and_executes_procurement_tools():
    async def exercise_server():
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "procurement_agent.protocols.mcp.server"],
        )
        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as client:
                await client.initialize()
                tools = await client.list_tools()
                names = {tool.name for tool in tools.tools}
                result = await client.call_tool(
                    "calculate_reorder_plan",
                    {
                        "on_hand_units": 1,
                        "average_daily_demand": 1,
                        "lead_time_days": 2,
                        "safety_stock_days": 1,
                    },
                )

        assert names == {
            "compare_supplier_quotes",
            "calculate_reorder_plan",
            "draft_rfq",
        }
        assert result.structuredContent["suggested_order_quantity"] == 9

    asyncio.run(exercise_server())
