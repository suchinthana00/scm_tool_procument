import asyncio
import json

from google.protobuf.json_format import MessageToDict
import httpx

from a2a.helpers import new_text_message
from a2a.types import Role, SendMessageRequest

from procurement_agent.protocols.a2a.server import ProcurementAgentExecutor, app


def test_a2a_card_and_jsonrpc_task_use_shared_procurement_logic():
    async def exercise_routes():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            card_response = await client.get("/.well-known/agent-card.json")
            assert card_response.status_code == 200
            assert {
                skill["id"] for skill in card_response.json()["skills"]
            } == {
                "compare_supplier_quotes",
                "calculate_reorder_plan",
                "draft_rfq",
            }

            text = json.dumps(
                {
                    "skill": "calculate_reorder_plan",
                    "input": {
                        "on_hand_units": 1,
                        "average_daily_demand": 1,
                        "lead_time_days": 2,
                        "safety_stock_days": 1,
                    },
                }
            )
            message = new_text_message(text, role=Role.ROLE_USER)
            response = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "id": "test-1",
                    "method": "SendMessage",
                    "params": MessageToDict(SendMessageRequest(message=message)),
                },
                headers={"A2A-Version": "1.0"},
            )

        assert response.status_code == 200
        result = response.json()["result"]["task"]
        assert result["status"]["state"] == "TASK_STATE_COMPLETED"
        artifact = result["artifacts"][0]["parts"][0]["text"]
        assert json.loads(artifact)["result"]["suggested_order_quantity"] == 9

    asyncio.run(exercise_routes())


def test_a2a_invalid_skill_returns_actionable_error():
    result = ProcurementAgentExecutor._handle_request(
        json.dumps({"skill": "not_a_skill", "input": {}})
    )

    assert result["ok"] is False
    assert "Unknown skill" in result["error"]
    assert "compare_supplier_quotes" in result["supported_skills"]
