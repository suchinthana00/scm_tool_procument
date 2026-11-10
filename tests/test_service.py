import pytest

from procurement_agent.service import (
    ProcurementInputError,
    calculate_reorder_plan,
    compare_supplier_quotes,
    draft_rfq,
    execute_skill,
)


def test_compare_supplier_quotes_ranks_eligible_quotes_with_disclosed_weights():
    result = compare_supplier_quotes(
        [
            {
                "supplier_name": "FastCo",
                "unit_price": 12,
                "currency": "USD",
                "lead_time_days": 2,
                "quality_score": 80,
                "on_time_rate": 90,
            },
            {
                "supplier_name": "ValueCo",
                "unit_price": 10,
                "currency": "USD",
                "lead_time_days": 5,
                "quality_score": 95,
                "on_time_rate": 98,
            },
        ],
        required_quantity=10,
    )

    assert result["recommended_supplier"] == "ValueCo"
    assert result["ranked_quotes"][0]["score"] > result["ranked_quotes"][1]["score"]
    assert result["scoring_weights"] == {
        "price": 0.35,
        "lead_time": 0.20,
        "quality": 0.25,
        "on_time_delivery": 0.20,
    }
    assert result["recommendation_status"] == "for_human_review"


def test_compare_supplier_quotes_excludes_budget_and_moq_violations():
    result = compare_supplier_quotes(
        [
            {
                "supplier_name": "Over MOQ",
                "unit_price": 1,
                "currency": "USD",
                "lead_time_days": 1,
                "quality_score": 90,
                "on_time_rate": 90,
                "minimum_order_quantity": 20,
            },
            {
                "supplier_name": "Over budget",
                "unit_price": 11,
                "currency": "USD",
                "lead_time_days": 1,
                "quality_score": 90,
                "on_time_rate": 90,
            },
        ],
        required_quantity=10,
        budget=100,
    )

    assert result["recommended_supplier"] is None
    assert result["recommendation_status"] == "no_eligible_quote"
    assert result["ranked_quotes"][0]["exclusion_reasons"] == [
        "minimum_order_quantity_exceeds_required_quantity"
    ]
    assert result["ranked_quotes"][1]["exclusion_reasons"] == [
        "total_cost_exceeds_budget"
    ]


def test_compare_supplier_quotes_rejects_mixed_currency():
    quotes = [
        {
            "supplier_name": "One",
            "unit_price": 1,
            "currency": "USD",
            "lead_time_days": 1,
            "quality_score": 90,
            "on_time_rate": 90,
        },
        {
            "supplier_name": "Two",
            "unit_price": 1,
            "currency": "EUR",
            "lead_time_days": 1,
            "quality_score": 90,
            "on_time_rate": 90,
        },
    ]
    with pytest.raises(ProcurementInputError, match="same currency"):
        compare_supplier_quotes(quotes, required_quantity=1)


def test_compare_supplier_quotes_rejects_unrepresentably_large_values():
    quote = {
        "supplier_name": "Supplier",
        "unit_price": 10**10000,
        "currency": "USD",
        "lead_time_days": 1,
        "quality_score": 90,
        "on_time_rate": 90,
    }

    with pytest.raises(ProcurementInputError, match="finite number"):
        compare_supplier_quotes([quote], required_quantity=1)


def test_calculate_reorder_plan_accounts_for_open_orders_and_review_period():
    result = calculate_reorder_plan(
        on_hand_units=20,
        on_order_units=10,
        average_daily_demand=5,
        lead_time_days=4,
        safety_stock_days=2,
        review_period_days=7,
    )

    assert result["inventory_position_units"] == 30
    assert result["reorder_point_units"] == 30
    assert result["target_stock_units"] == 65
    assert result["should_reorder"] is True
    assert result["suggested_order_quantity"] == 35


def test_calculate_reorder_plan_does_not_reorder_without_forecast_demand():
    result = calculate_reorder_plan(0, 0, 5, 2)

    assert result["should_reorder"] is False
    assert result["suggested_order_quantity"] == 0
    assert result["days_of_supply"] is None


def test_draft_rfq_validates_dates_and_does_not_send():
    result = draft_rfq(
        item_description="Packaging boxes",
        quantity=100,
        unit_of_measure="each",
        delivery_location="Warehouse A",
        required_by_date="2026-12-01",
        specifications="Double-wall cardboard",
    )

    assert result["status"] == "draft_only"
    assert result["requires_human_review"] is True
    assert "Required delivery date: 2026-12-01" in result["body"]

    with pytest.raises(ProcurementInputError, match="YYYY-MM-DD"):
        draft_rfq("Boxes", 10, "each", "Warehouse A", required_by_date="12/01/2026")


def test_execute_skill_routes_a2a_payload_to_shared_logic():
    result = execute_skill(
        "calculate_reorder_plan",
        {
            "on_hand_units": 1,
            "average_daily_demand": 1,
            "lead_time_days": 2,
            "safety_stock_days": 1,
        },
    )

    assert result["should_reorder"] is True
    assert result["suggested_order_quantity"] == 9


@pytest.mark.parametrize(
    ("quantity", "error"),
    [(True, "positive integer"), (0, "positive integer"), (-1, "positive integer")],
)
def test_quote_quantity_must_be_a_positive_integer(quantity, error):
    with pytest.raises(ProcurementInputError, match=error):
        compare_supplier_quotes(
            [
                {
                    "supplier_name": "Supplier",
                    "unit_price": 1,
                    "currency": "USD",
                    "lead_time_days": 1,
                    "quality_score": 90,
                    "on_time_rate": 90,
                }
            ],
            required_quantity=quantity,
        )
