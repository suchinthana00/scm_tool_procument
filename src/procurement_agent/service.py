"""Deterministic procurement planning logic shared by protocol adapters."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any


class ProcurementInputError(ValueError):
    """Raised when a procurement request is incomplete or invalid."""


SCORING_WEIGHTS = {
    "price": 0.35,
    "lead_time": 0.20,
    "quality": 0.25,
    "on_time_delivery": 0.20,
}


def compare_supplier_quotes(
    quotes: Sequence[Mapping[str, Any]],
    required_quantity: int,
    budget: float | None = None,
) -> dict[str, Any]:
    """Rank comparable quotes using disclosed weights; never award a contract."""
    quantity = _positive_integer(required_quantity, "required_quantity")
    if not quotes:
        raise ProcurementInputError("quotes must contain at least one quote.")
    if budget is not None:
        budget = _number(budget, "budget", minimum=0)

    parsed_quotes = [_parse_quote(quote, index) for index, quote in enumerate(quotes)]
    currencies = {quote["currency"] for quote in parsed_quotes}
    if len(currencies) != 1:
        raise ProcurementInputError(
            "All quotes must use the same currency; convert them before comparison."
        )

    eligible: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for quote in parsed_quotes:
        total_cost_raw = quote["unit_price"] * quantity
        if not math.isfinite(total_cost_raw):
            raise ProcurementInputError(
                f"Total cost for {quote['supplier_name']!r} is not finite."
            )
        total_cost = round(total_cost_raw, 2)
        reasons: list[str] = []
        if quote["minimum_order_quantity"] > quantity:
            reasons.append("minimum_order_quantity_exceeds_required_quantity")
        if budget is not None and total_cost > budget:
            reasons.append("total_cost_exceeds_budget")
        result = {
            **quote,
            "required_quantity": quantity,
            "total_cost": total_cost,
            "eligible": not reasons,
            "exclusion_reasons": reasons,
        }
        results.append(result)
        if not reasons:
            eligible.append(result)

    if eligible:
        prices = [quote["total_cost"] for quote in eligible]
        lead_times = [quote["lead_time_days"] for quote in eligible]
        min_price, max_price = min(prices), max(prices)
        min_lead, max_lead = min(lead_times), max(lead_times)
        for quote in eligible:
            price_score = _inverse_scale(quote["total_cost"], min_price, max_price)
            lead_score = _inverse_scale(quote["lead_time_days"], min_lead, max_lead)
            quality_score = quote["quality_score"]
            on_time_score = quote["on_time_rate"]
            score = (
                price_score * SCORING_WEIGHTS["price"]
                + lead_score * SCORING_WEIGHTS["lead_time"]
                + quality_score * SCORING_WEIGHTS["quality"]
                + on_time_score * SCORING_WEIGHTS["on_time_delivery"]
            )
            quote["score"] = round(score, 2)
            quote["score_components"] = {
                "price": round(price_score, 2),
                "lead_time": round(lead_score, 2),
                "quality": round(quality_score, 2),
                "on_time_delivery": round(on_time_score, 2),
            }

    results.sort(
        key=lambda quote: (
            not quote["eligible"],
            -quote.get("score", -1),
            quote["total_cost"],
            quote["lead_time_days"],
            quote["supplier_name"].casefold(),
        )
    )
    recommendation = next((quote["supplier_name"] for quote in results if quote["eligible"]), None)
    return {
        "required_quantity": quantity,
        "currency": next(iter(currencies)),
        "budget": budget,
        "scoring_weights": SCORING_WEIGHTS.copy(),
        "ranked_quotes": results,
        "recommended_supplier": recommendation,
        "recommendation_status": (
            "for_human_review" if recommendation else "no_eligible_quote"
        ),
        "disclaimer": (
            "Ranking is a planning aid, not an award or purchase. Verify quote terms, "
            "supplier due diligence, and approval requirements before commitment."
        ),
    }


def calculate_reorder_plan(
    on_hand_units: int,
    average_daily_demand: float,
    lead_time_days: float,
    safety_stock_days: float,
    on_order_units: int = 0,
    review_period_days: float = 7,
) -> dict[str, Any]:
    """Calculate a basic reorder point and suggested top-up quantity."""
    on_hand = _nonnegative_integer(on_hand_units, "on_hand_units")
    on_order = _nonnegative_integer(on_order_units, "on_order_units")
    daily_demand = _number(average_daily_demand, "average_daily_demand", minimum=0)
    lead_time = _number(lead_time_days, "lead_time_days", minimum=0)
    safety_days = _number(safety_stock_days, "safety_stock_days", minimum=0)
    review_days = _number(review_period_days, "review_period_days", minimum=0)
    inventory_position = on_hand + on_order

    reorder_point = _ceil_product(
        daily_demand, lead_time + safety_days, "reorder_point_units"
    )
    target_stock = _ceil_product(
        daily_demand,
        lead_time + safety_days + review_days,
        "target_stock_units",
    )
    should_reorder = daily_demand > 0 and inventory_position <= reorder_point
    suggested_quantity = max(0, target_stock - inventory_position) if should_reorder else 0

    return {
        "on_hand_units": on_hand,
        "on_order_units": on_order,
        "inventory_position_units": inventory_position,
        "average_daily_demand": daily_demand,
        "days_of_supply": (
            round(inventory_position / daily_demand, 2) if daily_demand else None
        ),
        "reorder_point_units": reorder_point,
        "target_stock_units": target_stock,
        "should_reorder": should_reorder,
        "suggested_order_quantity": suggested_quantity,
        "planning_basis": {
            "lead_time_days": lead_time,
            "safety_stock_days": safety_days,
            "review_period_days": review_days,
        },
        "disclaimer": (
            "Estimate uses constant average demand and supplied lead/safety-stock "
            "assumptions. Check seasonality, pack sizes, supplier constraints, and "
            "approval rules before ordering."
        ),
    }


def draft_rfq(
    item_description: str,
    quantity: int,
    unit_of_measure: str,
    delivery_location: str,
    required_by_date: str | None = None,
    specifications: str | None = None,
    response_deadline: str | None = None,
) -> dict[str, Any]:
    """Draft an RFQ for a buyer to review and send through approved channels."""
    description = _required_text(item_description, "item_description")
    unit = _required_text(unit_of_measure, "unit_of_measure")
    location = _required_text(delivery_location, "delivery_location")
    amount = _positive_integer(quantity, "quantity")
    required_date = _optional_iso_date(required_by_date, "required_by_date")
    deadline = _optional_iso_date(response_deadline, "response_deadline")
    spec_text = specifications.strip() if specifications and specifications.strip() else None

    lines = [
        "Request for Quotation",
        "",
        f"Item: {description}",
        f"Quantity: {amount} {unit}",
        f"Delivery location: {location}",
    ]
    if required_date:
        lines.append(f"Required delivery date: {required_date}")
    if deadline:
        lines.append(f"Please respond by: {deadline}")
    if spec_text:
        lines.extend(["", "Specifications:", spec_text])
    lines.extend(
        [
            "",
            "Please include unit price, currency, taxes and other charges, "
            "minimum order quantity, lead time, quote validity, payment terms, "
            "and any deviations from the specifications.",
        ]
    )
    return {
        "status": "draft_only",
        "subject": f"RFQ: {description} ({amount} {unit})",
        "body": "\n".join(lines),
        "supplier_response_fields": [
            "unit_price",
            "currency",
            "taxes_and_other_charges",
            "minimum_order_quantity",
            "lead_time_days",
            "quote_valid_until",
            "payment_terms",
            "specification_deviations",
        ],
        "requires_human_review": True,
        "disclaimer": "This draft is not sent to suppliers and does not create a commitment.",
    }


def execute_skill(skill: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Execute a named capability using the same API behind each protocol."""
    if not isinstance(inputs, Mapping):
        raise ProcurementInputError("input must be a JSON object.")

    if skill == "compare_supplier_quotes":
        return compare_supplier_quotes(
            quotes=_required(inputs, "quotes"),
            required_quantity=_required(inputs, "required_quantity"),
            budget=inputs.get("budget"),
        )
    if skill == "calculate_reorder_plan":
        return calculate_reorder_plan(
            on_hand_units=_required(inputs, "on_hand_units"),
            average_daily_demand=_required(inputs, "average_daily_demand"),
            lead_time_days=_required(inputs, "lead_time_days"),
            safety_stock_days=_required(inputs, "safety_stock_days"),
            on_order_units=inputs.get("on_order_units", 0),
            review_period_days=inputs.get("review_period_days", 7),
        )
    if skill == "draft_rfq":
        return draft_rfq(
            item_description=_required(inputs, "item_description"),
            quantity=_required(inputs, "quantity"),
            unit_of_measure=_required(inputs, "unit_of_measure"),
            delivery_location=_required(inputs, "delivery_location"),
            required_by_date=inputs.get("required_by_date"),
            specifications=inputs.get("specifications"),
            response_deadline=inputs.get("response_deadline"),
        )
    raise ProcurementInputError(
        f"Unknown skill {skill!r}. Supported skills: "
        "compare_supplier_quotes, calculate_reorder_plan, draft_rfq."
    )


def _parse_quote(quote: Mapping[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(quote, Mapping):
        raise ProcurementInputError(f"quotes[{index}] must be a JSON object.")
    name = _required_text(quote.get("supplier_name"), f"quotes[{index}].supplier_name")
    currency = _required_text(quote.get("currency"), f"quotes[{index}].currency").upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ProcurementInputError(
            f"quotes[{index}].currency must be a three-letter currency code."
        )
    return {
        "supplier_name": name,
        "unit_price": _number(quote.get("unit_price"), f"quotes[{index}].unit_price", 0),
        "currency": currency,
        "lead_time_days": _nonnegative_integer(
            quote.get("lead_time_days"), f"quotes[{index}].lead_time_days"
        ),
        "quality_score": _number(
            quote.get("quality_score"), f"quotes[{index}].quality_score", 0, 100
        ),
        "on_time_rate": _number(
            quote.get("on_time_rate"), f"quotes[{index}].on_time_rate", 0, 100
        ),
        "minimum_order_quantity": _positive_integer(
            quote.get("minimum_order_quantity", 1),
            f"quotes[{index}].minimum_order_quantity",
        ),
    }


def _required(inputs: Mapping[str, Any], name: str) -> Any:
    if name not in inputs:
        raise ProcurementInputError(f"Missing required field: {name}.")
    return inputs[name]


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProcurementInputError(f"{name} must be a non-empty string.")
    return value.strip()


def _number(
    value: Any,
    name: str,
    minimum: float,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProcurementInputError(f"{name} must be a number.")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ProcurementInputError(f"{name} must be a finite number.") from exc
    if not math.isfinite(number):
        raise ProcurementInputError(f"{name} must be a finite number.")
    if number < minimum:
        raise ProcurementInputError(f"{name} must be at least {minimum}.")
    if maximum is not None and number > maximum:
        raise ProcurementInputError(f"{name} must be at most {maximum}.")
    return number


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProcurementInputError(f"{name} must be a positive integer.")
    return value


def _nonnegative_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProcurementInputError(f"{name} must be a non-negative integer.")
    return value


def _optional_iso_date(value: str | None, name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ProcurementInputError(f"{name} must use YYYY-MM-DD format.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ProcurementInputError(f"{name} must use YYYY-MM-DD format.") from exc


def _inverse_scale(value: float, minimum: float, maximum: float) -> float:
    if minimum == maximum:
        return 100.0
    return ((maximum - value) / (maximum - minimum)) * 100


def _ceil_product(demand: float, days: float, name: str) -> int:
    units = demand * days
    if not math.isfinite(units):
        raise ProcurementInputError(f"{name} calculation is not finite.")
    return math.ceil(units)
