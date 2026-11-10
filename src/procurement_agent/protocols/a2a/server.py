"""A2A JSON-RPC server for the shared procurement planning capabilities."""

from __future__ import annotations

import json
import os
from typing import Any

import uvicorn
from a2a.helpers import (
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    TaskState,
)
from starlette.applications import Starlette

from procurement_agent.service import ProcurementInputError, execute_skill

SKILLS = (
    AgentSkill(
        id="compare_supplier_quotes",
        name="Compare supplier quotes",
        description=(
            "Rank buyer-provided quotes by disclosed cost, lead-time, quality, and "
            "on-time-delivery weights. Returns a human-review recommendation."
        ),
        tags=["procurement", "sourcing", "supplier"],
        examples=['{"skill":"compare_supplier_quotes","input":{"quotes":[],"required_quantity":10}}'],
        input_modes=["text/plain"],
        output_modes=["text/plain"],
    ),
    AgentSkill(
        id="calculate_reorder_plan",
        name="Calculate a reorder plan",
        description=(
            "Estimate a reorder point and suggested top-up from current stock, demand, "
            "lead time, safety stock, and review period."
        ),
        tags=["procurement", "inventory", "replenishment"],
        examples=['{"skill":"calculate_reorder_plan","input":{"on_hand_units":20,"average_daily_demand":5,"lead_time_days":4,"safety_stock_days":2}}'],
        input_modes=["text/plain"],
        output_modes=["text/plain"],
    ),
    AgentSkill(
        id="draft_rfq",
        name="Draft a request for quotation",
        description="Prepare an RFQ draft for a buyer to review; it is not sent.",
        tags=["procurement", "sourcing", "rfq"],
        examples=['{"skill":"draft_rfq","input":{"item_description":"Packaging boxes","quantity":100,"unit_of_measure":"each","delivery_location":"Warehouse A"}}'],
        input_modes=["text/plain"],
        output_modes=["text/plain"],
    ),
)


class ProcurementAgentExecutor(AgentExecutor):
    """Execute explicit JSON skill requests without an LLM or external side effects."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.current_task:
            task = context.current_task
        else:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task.id,
            context_id=task.context_id,
        )
        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=new_text_message("Processing procurement planning request."),
        )

        result = self._handle_request(get_message_text(context.message))
        await updater.add_artifact(
            parts=[new_text_part(text=json.dumps(result, indent=2), media_type="text/plain")],
            name="procurement_result",
        )
        await updater.update_status(
            state=TaskState.TASK_STATE_COMPLETED,
            message=new_text_message("Procurement planning request completed."),
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancellation is not supported.")

    @staticmethod
    def _handle_request(message_text: str | None) -> dict[str, Any]:
        if not message_text:
            return {"error": "Send a JSON request with skill and input fields."}
        try:
            request = json.loads(message_text)
            if not isinstance(request, dict):
                raise ProcurementInputError("The A2A request must be a JSON object.")
            skill = request.get("skill")
            inputs = request.get("input")
            if not isinstance(skill, str) or not isinstance(inputs, dict):
                raise ProcurementInputError(
                    "The A2A request must include string 'skill' and object 'input' fields."
                )
            return {"ok": True, "result": execute_skill(skill, inputs)}
        except (json.JSONDecodeError, ProcurementInputError) as exc:
            message = (
                f"Invalid JSON: {exc.msg}."
                if isinstance(exc, json.JSONDecodeError)
                else str(exc)
            )
            return {
                "ok": False,
                "error": message,
                "supported_skills": [skill.id for skill in SKILLS],
            }


def create_app(host: str = "127.0.0.1", port: int = 9000) -> Starlette:
    """Create an A2A-compatible JSON-RPC app with a discoverable Agent Card."""
    agent_card = AgentCard(
        name="Supply Chain Procurement Planner",
        description=(
            "Deterministic, read-only procurement planning capabilities for "
            "supplier quote comparison, reorder planning, and RFQ drafting."
        ),
        version="0.1.0",
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                protocol_version="1.0",
                url=f"http://{host}:{port}/",
            )
        ],
        skills=list(SKILLS),
    )
    request_handler = DefaultRequestHandler(
        agent_executor=ProcurementAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )
    return Starlette(
        routes=[
            *create_agent_card_routes(agent_card),
            *create_jsonrpc_routes(request_handler, "/"),
        ]
    )


app = create_app(
    host=os.environ.get("PROCUREMENT_A2A_HOST", "127.0.0.1"),
    port=int(os.environ.get("PROCUREMENT_A2A_PORT", "9000")),
)


def main() -> None:
    host = os.environ.get("PROCUREMENT_A2A_HOST", "127.0.0.1")
    port = int(os.environ.get("PROCUREMENT_A2A_PORT", "9000"))
    uvicorn.run(create_app(host, port), host=host, port=port)


if __name__ == "__main__":
    main()
