from __future__ import annotations

from dataclasses import dataclass, field

from app.services import route_mvp_config as config

TUNNEL_COST_SIMILAR_RATIO = 1.10

ROCK_CLASS_FACTORS = {
    "I": {"rock_score": 25, "ground_factor": 0.75, "constructability": "good"},
    "II": {"rock_score": 20, "ground_factor": 0.90, "constructability": "good"},
    "III": {"rock_score": 15, "ground_factor": 1.10, "constructability": "normal"},
    "IV": {"rock_score": -5, "ground_factor": 1.50, "constructability": "poor"},
    "V": {"rock_score": -40, "ground_factor": 2.50, "constructability": "very_poor"},
    "unknown": {"rock_score": 0, "ground_factor": 1.30, "constructability": "unknown"},
}

GROUND_CLASS_TO_ROCK_CLASS = {
    "good_rock": "II",
    "fair_rock": "III",
    "poor_rock": "IV",
    "very_poor_rock": "V",
    "very_poor": "V",
    "soil_behavior": "V",
    "unknown": "unknown",
}

ROMAN_TO_ROCK_CLASS = {
    "Ⅰ": "I",
    "Ⅱ": "II",
    "Ⅲ": "III",
    "Ⅳ": "IV",
    "Ⅴ": "V",
}

NUM_TO_ROCK_CLASS = {
    "1": "I",
    "2": "II",
    "3": "III",
    "4": "IV",
    "5": "V",
}


@dataclass(frozen=True)
class TunnelDecisionInput:
    road_grade_percent: float | None = None
    overburden_m: float | None = None
    estimated_rock_class: object | None = None
    rock_class: object | None = None
    local_relief_m: float | None = None
    slope_deg: float | None = None
    river_crossing: bool = False
    protected_area: bool = False
    urban_area: bool = False
    original_segment_type: str = "surface_road"
    segment_length_km: float = 0.0
    estimated_surface_cost_eok: float | None = None
    estimated_tunnel_cost_eok: float | None = None


@dataclass
class TunnelDecision:
    final_segment_type: str
    decision_status: str
    feasibility_flag: str | None
    tunnel_score: float | None
    overburden_condition: str
    estimated_rock_class: str
    rock_class: str
    rock_ground_factor: float
    rock_constructability: str
    estimated_surface_cost_eok: float | None
    estimated_tunnel_cost_eok: float | None
    decision_reason: str
    risk_reasons: list[str] = field(default_factory=list)


def normalize_rock_class(value: object | None) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, int):
        return NUM_TO_ROCK_CLASS.get(str(value), "unknown")
    if isinstance(value, float) and value.is_integer():
        return NUM_TO_ROCK_CLASS.get(str(int(value)), "unknown")

    text = str(value).strip()
    if not text:
        return "unknown"
    text_upper = text.upper()
    if text_upper in ROCK_CLASS_FACTORS:
        return text_upper
    if text in ROMAN_TO_ROCK_CLASS:
        return ROMAN_TO_ROCK_CLASS[text]
    if text_upper in NUM_TO_ROCK_CLASS:
        return NUM_TO_ROCK_CLASS[text_upper]
    return GROUND_CLASS_TO_ROCK_CLASS.get(text.lower(), "unknown")


def get_rock_class_factor(rock_class: object | None) -> float:
    normalized = normalize_rock_class(rock_class)
    return float(ROCK_CLASS_FACTORS[normalized]["ground_factor"])


def get_rock_constructability(rock_class: object | None) -> str:
    normalized = normalize_rock_class(rock_class)
    return str(ROCK_CLASS_FACTORS[normalized]["constructability"])


def get_rock_score(rock_class: object | None) -> float:
    normalized = normalize_rock_class(rock_class)
    return float(ROCK_CLASS_FACTORS[normalized]["rock_score"])


def classify_overburden_condition(overburden_m: float | None) -> str:
    if overburden_m is None:
        return "unknown"
    if overburden_m < 20:
        return "low_cover"
    if overburden_m < 50:
        return "shallow_tunnel"
    return "normal_tunnel"


def get_overburden_score(overburden_m: float | None) -> float:
    condition = classify_overburden_condition(overburden_m)
    if condition == "low_cover":
        return -40.0
    if condition == "shallow_tunnel":
        return 10.0
    if condition == "normal_tunnel":
        return 25.0
    return 0.0


def estimate_surface_segment_cost_eok(
    length_km: float,
    *,
    road_grade_percent: float | None = None,
    urban_area: bool = False,
) -> float:
    terrain_factor = 1.0
    if road_grade_percent is not None:
        if road_grade_percent >= 12:
            terrain_factor = 2.0
        elif road_grade_percent >= 8:
            terrain_factor = 1.5
    f_urban = config.URBAN_AREA_MULTIPLIER if urban_area else 1.0
    return round(length_km * config.ROAD_UNIT_COST_EOK_PER_KM * f_urban * terrain_factor, 3)


def estimate_tunnel_segment_cost_eok(
    length_km: float,
    *,
    rock_class: object | None = None,
    tunnel_lanes: int = 2,
) -> float:
    tunnel_unit = (
        config.TUNNEL_NATM_3LANE_THOUSAND_KRW_PER_M
        if tunnel_lanes == 3
        else config.TUNNEL_NATM_2LANE_THOUSAND_KRW_PER_M
    )
    length_m = length_km * 1000.0
    unit_eok_per_m = tunnel_unit / 100000.0
    if length_m <= 400:
        f_length = 0.994
    elif length_m <= 800:
        f_length = 0.998
    elif length_m <= 1000:
        f_length = 1.000
    elif length_m <= 1200:
        f_length = 1.006
    elif length_m <= 2000:
        f_length = 1.021
    elif length_m <= 4000:
        f_length = 1.062
    else:
        f_length = 1.08
    return round(
        length_m
        * unit_eok_per_m
        * config.DEFAULT_TUNNEL_AREA_FACTOR
        * get_rock_class_factor(rock_class)
        * f_length
        * config.DEFAULT_TUNNEL_AUX_FACTOR,
        3,
    )


def _fallback_slope_decision(payload: TunnelDecisionInput, risk_reasons: list[str]) -> TunnelDecision:
    slope = payload.slope_deg or 0.0
    high_relief = (payload.local_relief_m or 0.0) >= 80.0
    final_type = "tunnel" if slope >= 25.0 or high_relief else payload.original_segment_type
    status = "fallback_slope_based_tunnel_logic" if final_type == "tunnel" else "surface_preferred"
    return TunnelDecision(
        final_segment_type=final_type,
        decision_status=status,
        feasibility_flag=None,
        tunnel_score=None,
        overburden_condition="unknown",
        estimated_rock_class="unknown",
        rock_class="unknown",
        rock_ground_factor=ROCK_CLASS_FACTORS["unknown"]["ground_factor"],
        rock_constructability=ROCK_CLASS_FACTORS["unknown"]["constructability"],
        estimated_surface_cost_eok=payload.estimated_surface_cost_eok,
        estimated_tunnel_cost_eok=payload.estimated_tunnel_cost_eok,
        decision_reason="fallback_slope_based_tunnel_logic",
        risk_reasons=risk_reasons,
    )


def evaluate_tunnel_decision(payload: TunnelDecisionInput) -> TunnelDecision:
    risk_reasons: list[str] = []
    if payload.river_crossing:
        return TunnelDecision(
            final_segment_type="bridge",
            decision_status="bridge_required",
            feasibility_flag=None,
            tunnel_score=None,
            overburden_condition=classify_overburden_condition(payload.overburden_m),
            estimated_rock_class=normalize_rock_class(payload.estimated_rock_class),
            rock_class=normalize_rock_class(payload.rock_class or payload.estimated_rock_class),
            rock_ground_factor=get_rock_class_factor(payload.rock_class or payload.estimated_rock_class),
            rock_constructability=get_rock_constructability(payload.rock_class or payload.estimated_rock_class),
            estimated_surface_cost_eok=payload.estimated_surface_cost_eok,
            estimated_tunnel_cost_eok=payload.estimated_tunnel_cost_eok,
            decision_reason="bridge_due_to_river_crossing",
            risk_reasons=["bridge_cost_requires_detailed_review"],
        )

    has_overburden = payload.overburden_m is not None
    has_rock = payload.estimated_rock_class is not None or payload.rock_class is not None
    if not has_overburden and not has_rock:
        return _fallback_slope_decision(payload, risk_reasons)

    normalized_rock = normalize_rock_class(payload.rock_class or payload.estimated_rock_class)
    if normalized_rock == "unknown":
        risk_reasons.append("unknown_rock_class_default_ground_factor")
    if payload.overburden_m is None:
        risk_reasons.append("unknown_overburden")
    elif payload.overburden_m < 0:
        risk_reasons.append("negative_overburden_check_dem_or_profile")

    grade_score = 0.0
    if payload.road_grade_percent is not None:
        if payload.road_grade_percent >= 12:
            grade_score = 40.0
        elif payload.road_grade_percent >= 8:
            grade_score = 20.0

    overburden_score = get_overburden_score(payload.overburden_m)
    rock_score = get_rock_score(normalized_rock)
    relief_score = 15.0 if payload.local_relief_m is not None and payload.local_relief_m >= 80.0 else 0.0
    penalty_score = 0.0
    if normalized_rock == "V":
        penalty_score += 20.0
    if payload.overburden_m is not None and payload.overburden_m < 20.0:
        penalty_score += 20.0
    if payload.protected_area:
        penalty_score += 9999.0
        risk_reasons.append("protected_area_direct_conflict")

    tunnel_score = grade_score + overburden_score + rock_score + relief_score - penalty_score
    surface_cost = payload.estimated_surface_cost_eok
    tunnel_cost = payload.estimated_tunnel_cost_eok
    if surface_cost is None:
        surface_cost = estimate_surface_segment_cost_eok(
            payload.segment_length_km,
            road_grade_percent=payload.road_grade_percent,
            urban_area=payload.urban_area,
        )
    if tunnel_cost is None:
        tunnel_cost = estimate_tunnel_segment_cost_eok(payload.segment_length_km, rock_class=normalized_rock)

    decision_status = "surface_preferred"
    final_type = "surface_road"
    feasibility_flag = "avoid_or_reroute" if payload.protected_area or normalized_rock == "V" else None
    decision_reason = "surface_preferred"

    if payload.overburden_m is not None and payload.overburden_m < 0.0:
        decision_reason = "negative_overburden_check_dem_or_profile"
        final_type = "surface_road"
        decision_status = "surface_preferred"
    elif payload.overburden_m is not None and payload.overburden_m < 20.0:
        decision_reason = "low_overburden_cut_and_cover_or_surface_preferred"
        final_type = "surface_road"
        decision_status = "low_cover_tunnel_candidate" if tunnel_score >= 30 else "surface_preferred"
    elif tunnel_score >= 60.0:
        decision_status = "tunnel_preferred"
        final_type = "tunnel"
        decision_reason = (
            "road_grade_over_12_and_overburden_sufficient"
            if payload.road_grade_percent is not None and payload.road_grade_percent >= 12
            else "normal_tunnel_condition"
        )
    elif tunnel_score >= 30.0:
        decision_status = "tunnel_candidate"
        if tunnel_cost <= surface_cost * TUNNEL_COST_SIMILAR_RATIO:
            final_type = "tunnel"
            decision_reason = "normal_tunnel_condition"
        else:
            final_type = "surface_road"
            decision_reason = "poor_rock_high_cost_surface_preferred"

    if normalized_rock == "V" and "avoid_or_reroute_due_to_very_poor_rock" not in risk_reasons:
        risk_reasons.append("avoid_or_reroute_due_to_very_poor_rock")
    if normalized_rock == "V" and tunnel_cost > surface_cost * TUNNEL_COST_SIMILAR_RATIO:
        if final_type == "tunnel":
            final_type = "surface_road"
        decision_reason = "avoid_or_reroute_due_to_very_poor_rock"

    return TunnelDecision(
        final_segment_type=final_type,
        decision_status=decision_status,
        feasibility_flag=feasibility_flag,
        tunnel_score=round(tunnel_score, 2),
        overburden_condition=classify_overburden_condition(payload.overburden_m),
        estimated_rock_class=normalize_rock_class(payload.estimated_rock_class),
        rock_class=normalized_rock,
        rock_ground_factor=get_rock_class_factor(normalized_rock),
        rock_constructability=get_rock_constructability(normalized_rock),
        estimated_surface_cost_eok=surface_cost,
        estimated_tunnel_cost_eok=tunnel_cost,
        decision_reason=decision_reason,
        risk_reasons=risk_reasons,
    )
