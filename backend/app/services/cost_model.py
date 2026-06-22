from __future__ import annotations

from dataclasses import dataclass

from app.services import route_mvp_config as config


@dataclass(frozen=True)
class CostAssumptions:
    road_unit_cost_eok_per_km: float = config.ROAD_UNIT_COST_EOK_PER_KM
    tunnel_unit_cost_thousand_krw_per_m: float = config.TUNNEL_NATM_2LANE_THOUSAND_KRW_PER_M
    bridge_unit_cost_eok_per_km: float = config.BRIDGE_UNIT_COST_EOK_PER_KM
    road_contingency: float = config.ROAD_CONTINGENCY
    tunnel_contingency: float = config.TUNNEL_CONTINGENCY
    bridge_contingency: float = config.BRIDGE_CONTINGENCY
    default_ground_factor: float = config.DEFAULT_GROUND_FACTOR
    tunnel_aux_factor: float = config.DEFAULT_TUNNEL_AUX_FACTOR
    tunnel_area_factor: float = config.DEFAULT_TUNNEL_AREA_FACTOR


def getGroundFactorByGeology(route_segment, geology_data) -> float:
    # TODO: Replace this MVP fallback with geology and ground-structure interpretation.
    if geology_data is None:
        return config.DEFAULT_GROUND_FACTOR

    ground_class = getattr(route_segment, "ground_class", None) or getattr(geology_data, "ground_class", None)
    if ground_class in {"good_rock", "양호암"}:
        return 0.70
    if ground_class in {"poor_rock", "불량암"}:
        return 1.50
    if ground_class in {"very_poor", "soil_behavior", "매우불량", "토사거동"}:
        return 2.80
    return config.DEFAULT_GROUND_FACTOR


def _tunnel_length_factor(length_m: float) -> float:
    if length_m <= 400:
        return 0.994
    if length_m <= 800:
        return 0.998
    if length_m <= 1000:
        return 1.000
    if length_m <= 1200:
        return 1.006
    if length_m <= 2000:
        return 1.021
    if length_m <= 4000:
        return 1.062
    return 1.08


def _thousand_krw_per_m_to_eok_per_m(value: float) -> float:
    # Internal route costs are stored in eok KRW (100,000,000 KRW).
    # A tunnel unit value is thousand KRW per meter, so value * 1,000 / 100,000,000.
    return value / 100000.0


def calculate_route_costs(
    surface_road_length_km: float,
    tunnel_length_km: float,
    bridge_length_km: float,
    *,
    urban_type: str = "rural",
    design_speed_kph: int = 80,
    tunnel_lanes: int = 2,
    geology_data=None,
    assumptions: CostAssumptions | None = None,
) -> dict:
    active = assumptions or CostAssumptions()
    f_urban = config.URBAN_COST_MULTIPLIERS.get(urban_type, 1.0)
    f_speed = config.SPEED_COST_MULTIPLIERS.get(design_speed_kph, 1.05 if design_speed_kph >= 100 else 1.0)
    tunnel_unit = (
        config.TUNNEL_NATM_3LANE_THOUSAND_KRW_PER_M
        if tunnel_lanes == 3
        else active.tunnel_unit_cost_thousand_krw_per_m
    )
    tunnel_length_m = tunnel_length_km * 1000.0
    f_ground = getGroundFactorByGeology(None, geology_data)
    f_length = _tunnel_length_factor(tunnel_length_m)

    surface_road_cost = surface_road_length_km * active.road_unit_cost_eok_per_km
    surface_road_cost_adjusted = surface_road_cost * f_urban * f_speed
    tunnel_cost = (
        tunnel_length_m
        * _thousand_krw_per_m_to_eok_per_m(tunnel_unit)
        * active.tunnel_area_factor
        * f_ground
        * f_length
        * active.tunnel_aux_factor
    )
    bridge_cost = bridge_length_km * active.bridge_unit_cost_eok_per_km

    surface_road_screen_cost = surface_road_cost_adjusted * (1 + active.road_contingency)
    tunnel_screen_cost = tunnel_cost * (1 + active.tunnel_contingency)
    bridge_screen_cost = bridge_cost * (1 + active.bridge_contingency)

    total_direct_cost = surface_road_cost_adjusted + tunnel_cost + bridge_cost
    total_screen_cost = surface_road_screen_cost + tunnel_screen_cost + bridge_screen_cost

    return {
        "surface_road_cost": round(surface_road_cost_adjusted, 3),
        "tunnel_cost": round(tunnel_cost, 3),
        "bridge_cost": round(bridge_cost, 3),
        "total_direct_cost": round(total_direct_cost, 3),
        "surface_road_screen_cost": round(surface_road_screen_cost, 3),
        "tunnel_screen_cost": round(tunnel_screen_cost, 3),
        "bridge_screen_cost": round(bridge_screen_cost, 3),
        "total_screen_cost": round(total_screen_cost, 3),
        "cost_assumptions": {
            "unit": "eok_krw",
            "road_unit_cost_eok_per_km": active.road_unit_cost_eok_per_km,
            "tunnel_unit_cost_thousand_krw_per_m": tunnel_unit,
            "bridge_unit_cost_eok_per_km": active.bridge_unit_cost_eok_per_km,
            "f_urban": f_urban,
            "f_speed": f_speed,
            "f_ground": f_ground,
            "f_length": f_length,
            "f_aux": active.tunnel_aux_factor,
            "road_contingency": active.road_contingency,
            "tunnel_contingency": active.tunnel_contingency,
            "bridge_contingency": active.bridge_contingency,
        },
    }
