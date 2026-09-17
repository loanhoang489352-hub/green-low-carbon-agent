from agent.tools.extended import TravelPlanningTool
from agent.travel.carbon import assess_route_carbon


def test_active_modes_are_zero_only_inside_direct_operation_boundary():
    result = assess_route_carbon("骑行")
    assert result["carbon_kg"] == 0
    assert result["carbon_status"] == "available_boundary_limited"
    assert result["carbon_boundary"] == "direct_vehicle_operation_only"
    assert "不代表全生命周期" in result["carbon_note"]


def test_motorized_modes_stay_unknown_without_activity_data():
    for mode in ("自驾", "公交", "地铁", "公交+地铁"):
        result = assess_route_carbon(mode)
        assert result["carbon_kg"] is None
        assert result["carbon_status"] == "unavailable_missing_activity_data"
        assert result["carbon_note"]


def test_unknown_carbon_is_excluded_instead_of_scored_as_zero():
    routes = [
        {"type": "自驾", "carbon_kg": None, "cost_yuan": 10, "duration_min": 10},
        {"type": "骑行", "carbon_kg": 0, "cost_yuan": 0, "duration_min": 20},
    ]
    TravelPlanningTool()._recommend_route(routes)
    assert routes[0]["score_breakdown"]["carbon"] is None
    assert routes[0]["effective_weights"]["carbon"] == 0
    assert routes[1]["score_breakdown"]["carbon"] == 1
    assert routes[1]["effective_weights"]["carbon"] > 0
    assert "未知值未按零处理" in routes[0]["score_note"]
