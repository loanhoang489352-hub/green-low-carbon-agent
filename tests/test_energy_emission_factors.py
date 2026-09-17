from agent.energy.emission_factors import electricity_factor_for, SOURCE_URL
from agent.energy.models import HouseholdProfile
from agent.energy.planner import EnergyPlanner


def test_official_factor_registry_uses_province_and_national_fallback():
    assert electricity_factor_for("北京").kg_co2_per_kwh == 0.5554
    assert electricity_factor_for("深圳").kg_co2_per_kwh == 0.4419
    assert electricity_factor_for("未知城市").kg_co2_per_kwh == 0.5306
    assert SOURCE_URL.startswith("https://www.mee.gov.cn/")


def test_plan_converts_reference_kwh_with_location_factor():
    profile = HouseholdProfile(
        user_id="factor-user", city="北京", family_size=2,
        appliances=["照明"], monthly_electricity_bill=100,
        has_incandescent=True,
    )
    plan = EnergyPlanner().generate_plan(profile)
    led = next(action for action in plan.actions if action.id == "led_replace_incandescent")
    assert led.estimated_saving_kwh == 100
    assert led.estimated_saving_co2_kg == 55.54
    assert "0.5554kgCO2/kWh" in led.source_ref
    assert "不是实测" in led.estimate_note
