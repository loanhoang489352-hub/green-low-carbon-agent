"""出行碳排证据边界。

路线服务只提供距离、时长和路段，并不提供车辆能源类型、能耗、载客量等
活动数据。缺少这些数据时，不能用一个全国通用常数制造精确碳排结果。
"""

from typing import Any, Dict


DIRECT_OPERATION_BOUNDARY = "direct_vehicle_operation_only"


def assess_route_carbon(route_type: str) -> Dict[str, Any]:
    """Return an evidence-aware carbon assessment for a route mode.

    Walking and conventional cycling have no vehicle energy consumption during
    the trip, so zero is valid only for the direct operation boundary. Lifecycle
    emissions (food, bicycle manufacture and infrastructure) are excluded.

    Transit and driving need activity data that Amap directions does not return.
    Their value therefore remains unavailable until a geographically applicable
    factor and the required vehicle/service assumptions are supplied.
    """
    if route_type in {"步行", "骑行"}:
        return {
            "carbon_kg": 0.0,
            "carbon_status": "available_boundary_limited",
            "carbon_boundary": DIRECT_OPERATION_BOUNDARY,
            "carbon_factor": None,
            "carbon_factor_unit": None,
            "carbon_factor_source": None,
            "carbon_assumptions": [
                "按车辆直接运行阶段核算",
                "不含人体代谢、车辆制造、基础设施和生命周期排放",
                "骑行指普通自行车，不含电动自行车充电",
            ],
            "carbon_note": "直接运行排放为 0；不代表全生命周期零排放",
        }

    requirements = {
        "自驾": "需要车辆能源类型、实际能耗和乘员人数",
        "公交": "需要线路车型、能源消耗和载客量",
        "地铁": "需要当地轨道用电量、客运周转量和适用电力排放因子",
        "公交+地铁": "需要各分段交通方式、能源消耗和客运周转量",
    }
    return {
        "carbon_kg": None,
        "carbon_status": "unavailable_missing_activity_data",
        "carbon_boundary": None,
        "carbon_factor": None,
        "carbon_factor_unit": None,
        "carbon_factor_source": None,
        "carbon_assumptions": [],
        "carbon_note": requirements.get(route_type, "缺少适用排放因子和活动数据"),
    }
