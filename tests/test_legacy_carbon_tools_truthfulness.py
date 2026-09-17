from agent.skills.builtin import CarbonCalcTool


def test_legacy_carbon_tool_does_not_use_universal_motorized_factor():
    result = CarbonCalcTool().execute(distance_km=10, transport_mode="driving")
    assert result.success
    assert result.data["carbon_kg"] is None
    assert result.data["carbon_saved_kg"] is None
    assert result.data["carbon_status"] == "unavailable_missing_activity_data"


def test_legacy_carbon_tool_labels_active_mode_boundary():
    result = CarbonCalcTool().execute(distance_km=10, transport_mode="cycling")
    assert result.success
    assert result.data["carbon_kg"] == 0
    assert result.data["carbon_boundary"] == "direct_vehicle_operation_only"
