"""MCP server exposing the shared procurement planning capabilities."""

from __future__ import annotations

import argparse
import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from procurement_agent.service import (
    calculate_reorder_plan as calculate_reorder_plan_service,
    compare_supplier_quotes as compare_supplier_quotes_service,
    draft_rfq as draft_rfq_service,
)

mcp = FastMCP(
    "Supply Chain Procurement Tools",
    instructions=(
        "Read-only procurement planning tools. They analyze buyer-supplied data "
        "and draft content only; they do not issue purchase orders or contact suppliers."
    ),
)


@mcp.tool()
def compare_supplier_quotes(
    quotes_json: str,
    required_quantity: int,
    budget: float | None = None,
) -> dict[str, Any]:
    """Compare supplier quotes supplied as a JSON array and rank feasible offers.

    Each quote needs supplier_name, unit_price, currency, lead_time_days,
    quality_score (0-100), and on_time_rate (0-100). Optional:
    minimum_order_quantity. All quotes must use the same currency.
    """
    try:
        quotes = json.loads(quotes_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"quotes_json must be valid JSON: {exc.msg}.") from exc
    if not isinstance(quotes, list):
        raise ValueError("quotes_json must encode a JSON array.")
    return compare_supplier_quotes_service(quotes, required_quantity, budget)


@mcp.tool()
def calculate_reorder_plan(
    on_hand_units: int,
    average_daily_demand: float,
    lead_time_days: float,
    safety_stock_days: float,
    on_order_units: int = 0,
    review_period_days: float = 7,
) -> dict[str, Any]:
    """Estimate a reorder point and top-up quantity from inventory assumptions."""
    return calculate_reorder_plan_service(
        on_hand_units=on_hand_units,
        average_daily_demand=average_daily_demand,
        lead_time_days=lead_time_days,
        safety_stock_days=safety_stock_days,
        on_order_units=on_order_units,
        review_period_days=review_period_days,
    )


@mcp.tool()
def draft_rfq(
    item_description: str,
    quantity: int,
    unit_of_measure: str,
    delivery_location: str,
    required_by_date: str | None = None,
    specifications: str | None = None,
    response_deadline: str | None = None,
) -> dict[str, Any]:
    """Create an RFQ draft for human review; this tool does not send it."""
    return draft_rfq_service(
        item_description=item_description,
        quantity=quantity,
        unit_of_measure=unit_of_measure,
        delivery_location=delivery_location,
        required_by_date=required_by_date,
        specifications=specifications,
        response_deadline=response_deadline,
    )


@mcp.resource("procurement://capabilities")
def procurement_capabilities() -> str:
    """Describe available procurement capabilities and their safety boundaries."""
    return json.dumps(
        {
            "tools": [
                "compare_supplier_quotes",
                "calculate_reorder_plan",
                "draft_rfq",
            ],
            "side_effects": False,
            "requires_human_review": True,
            "note": "The tools do not issue orders, modify inventory, or contact suppliers.",
        },
        indent=2,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the procurement MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport to serve (default: stdio).",
    )
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
