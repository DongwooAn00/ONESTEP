from __future__ import annotations

import math
from dataclasses import dataclass

from app.services import route_mvp_config as config
from app.services.geotechnical_model import get_rock_class_factor, normalize_rock_class


@dataclass(frozen=True)
class CostAssumptions:
    road_unit_cost_eok_per_km: float = config.ROAD_UNIT_COST_EOK_PER_KM
    tunnel_unit_cost_thousand_krw_per_m: float = config.TUNNEL_NATM_2LANE_THOUSAND_KRW_PER_M
    road_contingency: float = config.ROAD_CONTINGENCY
    tunnel_contingency: float = config.TUNNEL_CONTINGENCY
    default_ground_factor: float = config.DEFAULT_GROUND_FACTOR
    tunnel_aux_factor: float = config.DEFAULT_TUNNEL_AUX_FACTOR
    tunnel_area_factor: float = config.DEFAULT_TUNNEL_AREA_FACTOR


def getGroundFactorByGeology(route_segment, geology_data) -> float:
    rock_class = None
    if route_segment is not None:
        rock_class = getattr(route_segment, "rock_class", None) or getattr(route_segment, "estimated_rock_class", None)
    if geology_data is not None:
        if isinstance(geology_data, dict):
            rock_class = rock_class or geology_data.get("rock_class") or geology_data.get("estimated_rock_class")
        else:
            rock_class = rock_class or getattr(geology_data, "rock_class", None) or getattr(geology_data, "estimated_rock_class", None)
    normalized = normalize_rock_class(rock_class)
    if normalized != "unknown":
        return get_rock_class_factor(normalized)

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
    new_surface_road_length_km: float,
    tunnel_length_km: float,
    *,
    connector_length_km: float = 0.0,
    land_compensation_cost_eok: float = 0.0,
    urban_type: str = "rural",
    design_speed_kph: int = 80,
    tunnel_lanes: int = 2,
    geology_data=None,
    assumptions: CostAssumptions | None = None,
) -> dict:
    """신규 일반도로·접속도로·터널 공사비를 억원 단위로 합산한다."""
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

    new_road_cost = new_surface_road_length_km * active.road_unit_cost_eok_per_km
    connector_cost = connector_length_km * active.road_unit_cost_eok_per_km
    new_road_cost_adjusted = new_road_cost * f_urban * f_speed
    connector_cost_adjusted = connector_cost * f_urban * f_speed
    tunnel_cost = (
        tunnel_length_m
        * _thousand_krw_per_m_to_eok_per_m(tunnel_unit)
        * active.tunnel_area_factor
        * f_ground
        * f_length
        * active.tunnel_aux_factor
    )
    new_road_screen_cost = new_road_cost_adjusted * (1 + active.road_contingency)
    connector_screen_cost = connector_cost_adjusted * (1 + active.road_contingency)
    tunnel_screen_cost = tunnel_cost * (1 + active.tunnel_contingency)

    safe_land_compensation_cost = max(0.0, float(land_compensation_cost_eok))
    total_direct_cost = (
        new_road_cost_adjusted
        + connector_cost_adjusted
        + tunnel_cost
        + safe_land_compensation_cost
    )
    total_screen_cost = (
        new_road_screen_cost
        + connector_screen_cost
        + tunnel_screen_cost
        + safe_land_compensation_cost
    )

    return {
        "surface_road_cost": round(new_road_cost_adjusted, 3),
        "new_road_cost": round(new_road_cost_adjusted, 3),
        "connector_cost": round(connector_cost_adjusted, 3),
        "tunnel_cost": round(tunnel_cost, 3),
        "land_compensation_cost": round(safe_land_compensation_cost, 3),
        "total_direct_cost": round(total_direct_cost, 3),
        "surface_road_screen_cost": round(new_road_screen_cost, 3),
        "new_road_screen_cost": round(new_road_screen_cost, 3),
        "connector_screen_cost": round(connector_screen_cost, 3),
        "tunnel_screen_cost": round(tunnel_screen_cost, 3),
        "total_screen_cost": round(total_screen_cost, 3),
        "cost_assumptions": {
            "unit": "eok_krw",
            "road_unit_cost_eok_per_km": active.road_unit_cost_eok_per_km,
            "tunnel_unit_cost_thousand_krw_per_m": tunnel_unit,
            "f_urban": f_urban,
            "f_speed": f_speed,
            "f_ground": f_ground,
            "f_length": f_length,
            "f_aux": active.tunnel_aux_factor,
            "road_contingency": active.road_contingency,
            "tunnel_contingency": active.tunnel_contingency,
            "land_compensation_unit": "eok_krw",
        },
    }


def evaluate_candidate_against_baseline(
    candidate: dict,
    baseline: dict | None,
    *,
    analysis_years: int = 30,
    discount_rate: float = 0.045,
    value_of_time_krw_per_hour: float = 20_000.0,
    vehicle_cost_krw_per_km: float = 200.0,
) -> dict:
    """Evaluate a candidate by improvement over the existing-road baseline."""
    existing_speed_kph = 60.0
    new_speed_kph = 80.0
    connector_speed_kph = 40.0
    tunnel_speed_kph = 80.0

    def travel_time_hours(row: dict) -> float:
        existing = float(row.get("existing_road_length_km", 0.0))
        connector = float(row.get("connector_length_km", 0.0))
        new_road = float(row.get("new_surface_road_length_km", 0.0))
        tunnel = float(row.get("tunnel_length_km", 0.0))
        accounted = existing + connector + new_road + tunnel
        remainder = max(0.0, float(row.get("route_length_km", 0.0)) - accounted)
        return (
            existing / existing_speed_kph
            + connector / connector_speed_kph
            + (new_road + remainder) / new_speed_kph
            + tunnel / tunnel_speed_kph
        )

    baseline_length = float(
        baseline.get("route_length_km", 0.0)
        if baseline
        else candidate.get("straight_distance_km", 0.0) * config.DETOUR_FACTOR_ASSUMPTION
    )
    baseline_time = (
        travel_time_hours(baseline)
        if baseline
        else baseline_length / existing_speed_kph
    )
    candidate_length = float(candidate.get("route_length_km", 0.0))
    candidate_time = travel_time_hours(candidate)
    distance_saving = max(0.0, baseline_length - candidate_length)
    time_saving = max(0.0, baseline_time - candidate_time)
    flow = max(0.0, float(candidate.get("estimated_flow", 0.0)))

    annual_time_benefit = time_saving * flow * 365.0 * value_of_time_krw_per_hour / 100_000_000.0
    annual_distance_benefit = distance_saving * flow * 365.0 * vehicle_cost_krw_per_km / 100_000_000.0
    annual_benefit = annual_time_benefit + annual_distance_benefit
    annuity_factor = (
        (1.0 - (1.0 + discount_rate) ** -analysis_years) / discount_rate
        if discount_rate > 0
        else float(analysis_years)
    )
    total_benefit = annual_benefit * annuity_factor
    construction_cost = max(0.0, float(candidate.get("total_screen_cost", 0.0)))
    benefit_cost_ratio = total_benefit / construction_cost if construction_cost > 0 else 0.0
    net_benefit = total_benefit - construction_cost

    existing_length = float(candidate.get("existing_road_length_km", 0.0))
    connector_length = float(candidate.get("connector_length_km", 0.0))
    new_road_length = float(candidate.get("new_surface_road_length_km", 0.0))
    tunnel_length = float(candidate.get("tunnel_length_km", 0.0))
    new_length = connector_length + new_road_length + tunnel_length
    new_segment_ratio = new_length / candidate_length if candidate_length > 0 else 0.0
    tunnel_ratio = tunnel_length / new_length if new_length > 0 else 0.0
    terrain_risk = min(1.0, max(0.0, float(candidate.get("max_slope", 0.0))) / 45.0)

    if candidate.get("route_type") == "existing_baseline":
        score = 0.0
    else:
        improvement_score = min(35.0, distance_saving / max(baseline_length, 0.001) * 100.0)
        time_score = min(30.0, time_saving / max(baseline_time, 0.001) * 100.0)
        demand_score = min(15.0, math.log1p(flow) / math.log(100_001.0) * 15.0)
        bc_score = min(20.0, benefit_cost_ratio * 10.0)
        meaningful_new_build = min(10.0, new_segment_ratio * 20.0)
        cost_penalty = min(20.0, construction_cost / max(total_benefit, 1.0) * 10.0)
        tunnel_penalty = max(0.0, tunnel_ratio - 0.45) * 25.0
        trivial_connector_penalty = 20.0 if new_road_length + tunnel_length < 0.5 else 0.0
        score = max(
            0.0,
            min(
                100.0,
                improvement_score
                + time_score
                + demand_score
                + bc_score
                + meaningful_new_build
                - cost_penalty
                - tunnel_penalty
                - terrain_risk * 10.0
                - trivial_connector_penalty,
            ),
        )

    candidate.update(
        {
            "existing_length_km": round(existing_length, 3),
            "connector_length_km": round(connector_length, 3),
            "new_road_length_km": round(new_road_length, 3),
            "construction_cost": round(construction_cost, 3),
            "annual_benefit": round(annual_benefit, 3),
            "total_benefit": round(total_benefit, 3),
            "benefit_cost_ratio": round(benefit_cost_ratio, 3),
            "net_benefit": round(net_benefit, 3),
            "distance_saving_km": round(distance_saving, 3),
            "time_saving_minutes": round(time_saving * 60.0, 2),
            "new_segment_ratio": round(new_segment_ratio, 4),
            "terrain_risk_penalty": round(terrain_risk, 4),
            "candidate_score": round(score, 2),
            # Legacy ranking name retained for the current frontend.
            "economic_score": round(score, 2),
        }
    )
    return candidate
