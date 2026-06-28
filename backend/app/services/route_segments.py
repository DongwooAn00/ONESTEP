from __future__ import annotations

import math
from dataclasses import dataclass, replace

from app.services import route_mvp_config as config
from app.services.cost_grid import CostCell
from app.services.geotechnical_model import (
    TunnelDecisionInput,
    estimate_surface_segment_cost_eok,
    estimate_tunnel_segment_cost_eok,
    evaluate_tunnel_decision,
)


@dataclass
class RouteSegmentDetail:
    segment_id: str
    segment_type: str
    segment_length_km: float
    segment_geometry: list[dict[str, float]]
    average_slope: float
    max_slope: float
    original_segment_type: str | None = None
    final_segment_type: str | None = None
    decision_status: str | None = None
    feasibility_flag: str | None = None
    tunnel_score: float | None = None
    overburden_m: float | None = None
    overburden_condition: str | None = None
    estimated_rock_class: str | None = None
    rock_class: str | None = None
    rock_ground_factor: float | None = None
    rock_constructability: str | None = None
    road_grade_percent: float | None = None
    slope_deg: float | None = None
    local_relief_m: float | None = None
    fault_dist_m: float | None = None
    boundary_dist_m: float | None = None
    estimated_surface_cost_eok: float | None = None
    estimated_tunnel_cost_eok: float | None = None
    decision_reason: str | None = None
    risk_reasons: list[str] | None = None


@dataclass(frozen=True)
class _AtomicSegment:
    segment_type: str
    start: CostCell
    end: CostCell
    length_km: float
    average_slope: float
    max_slope: float
    river_rank: str | None = None
    original_segment_type: str | None = None
    decision_status: str | None = None
    feasibility_flag: str | None = None
    tunnel_score: float | None = None
    overburden_m: float | None = None
    overburden_condition: str | None = None
    estimated_rock_class: str | None = None
    rock_class: str | None = None
    rock_ground_factor: float | None = None
    rock_constructability: str | None = None
    road_grade_percent: float | None = None
    slope_deg: float | None = None
    local_relief_m: float | None = None
    fault_dist_m: float | None = None
    boundary_dist_m: float | None = None
    estimated_surface_cost_eok: float | None = None
    estimated_tunnel_cost_eok: float | None = None
    decision_reason: str | None = None
    risk_reasons: tuple[str, ...] = ()


def _distance_km(start: CostCell, end: CostCell) -> float:
    return math.hypot(end.x - start.x, end.y - start.y) / 1000.0


def _local_relief_m(cells: list[CostCell], index: int, window: int = 3) -> float:
    start = max(0, index - window)
    end = min(len(cells), index + window + 1)
    elevations = [cell.elevation_m for cell in cells[start:end] if cell.elevation_m is not None]
    return max(elevations) - min(elevations) if elevations else 0.0


def _initial_type(cells: list[CostCell], index: int, start: CostCell, end: CostCell) -> tuple[str, str | None]:
    river_rank = start.river_rank or end.river_rank
    max_slope = max(start.slope_degrees, end.slope_degrees)
    high_relief = _local_relief_m(cells, index) >= 80 and max(start.cost, end.cost) >= 5.0
    if max_slope >= 25 or max_slope >= 20 or high_relief:
        return "tunnel", None
    return "new_surface_road", river_rank


def _road_grade_percent(start: CostCell, end: CostCell, length_km: float) -> float | None:
    if start.elevation_m is None or end.elevation_m is None or length_km <= 0:
        return None
    return abs(end.elevation_m - start.elevation_m) / (length_km * 1000.0) * 100.0


def _avg_optional(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _max_optional(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _atom_with_decision(cells: list[CostCell], index: int, start: CostCell, end: CostCell) -> _AtomicSegment | None:
    length_km = _distance_km(start, end)
    if length_km <= 0:
        return None
    original_type, river_rank = _initial_type(cells, index, start, end)
    average_slope = (start.slope_degrees + end.slope_degrees) / 2.0
    max_slope = max(start.slope_degrees, end.slope_degrees)
    local_relief = max(
        _local_relief_m(cells, index),
        _avg_optional([start.local_relief_m, end.local_relief_m]) or 0.0,
    )
    road_grade = _road_grade_percent(start, end, length_km)
    overburden = _avg_optional([start.overburden_m, end.overburden_m])
    estimated_rock = start.estimated_rock_class or end.estimated_rock_class
    rock_class = start.rock_class or end.rock_class or estimated_rock
    fault_dist = _min_optional([start.fault_dist_m, end.fault_dist_m])
    boundary_dist = _min_optional([start.boundary_dist_m, end.boundary_dist_m])
    surface_cost = estimate_surface_segment_cost_eok(
        length_km,
        road_grade_percent=road_grade,
        urban_area=start.builtup_area or end.builtup_area,
    )
    tunnel_cost = estimate_tunnel_segment_cost_eok(length_km, rock_class=rock_class or estimated_rock)
    decision = evaluate_tunnel_decision(
        TunnelDecisionInput(
            road_grade_percent=road_grade,
            overburden_m=overburden,
            estimated_rock_class=estimated_rock,
            rock_class=rock_class,
            local_relief_m=local_relief,
            slope_deg=max_slope,
            # Bridges are outside this MVP. Water crossings remain a grid
            # penalty/risk note and never become a bridge segment.
            river_crossing=False,
            protected_area=start.protected or end.protected,
            urban_area=start.builtup_area or end.builtup_area,
            original_segment_type=original_type,
            segment_length_km=length_km,
            estimated_surface_cost_eok=surface_cost,
            estimated_tunnel_cost_eok=tunnel_cost,
        )
    )
    risk_reasons = list(decision.risk_reasons)
    if river_rank:
        risk_reasons.append("MVP에서는 교량 미반영, 추가 검토 필요")
    for cell in (start, end):
        if cell.risk_reasons:
            risk_reasons.extend(cell.risk_reasons)
    return _AtomicSegment(
        segment_type=(
            "tunnel"
            if decision.final_segment_type == "tunnel"
            else "new_surface_road"
        ),
        start=start,
        end=end,
        length_km=length_km,
        average_slope=average_slope,
        max_slope=max_slope,
        river_rank=river_rank,
        original_segment_type=original_type,
        decision_status=decision.decision_status,
        feasibility_flag=decision.feasibility_flag,
        tunnel_score=decision.tunnel_score,
        overburden_m=overburden,
        overburden_condition=decision.overburden_condition,
        estimated_rock_class=decision.estimated_rock_class,
        rock_class=decision.rock_class,
        rock_ground_factor=decision.rock_ground_factor,
        rock_constructability=decision.rock_constructability,
        road_grade_percent=road_grade,
        slope_deg=max_slope,
        local_relief_m=local_relief,
        fault_dist_m=fault_dist,
        boundary_dist_m=boundary_dist,
        estimated_surface_cost_eok=decision.estimated_surface_cost_eok,
        estimated_tunnel_cost_eok=decision.estimated_tunnel_cost_eok,
        decision_reason=decision.decision_reason,
        risk_reasons=tuple(dict.fromkeys(risk_reasons)),
    )


def _min_optional(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def _atomic_segments(cells: list[CostCell]) -> list[_AtomicSegment]:
    atoms = []
    for index, (start, end) in enumerate(zip(cells, cells[1:])):
        atom = _atom_with_decision(cells, index, start, end)
        if atom is not None:
            atoms.append(atom)
    return atoms


def _downgrade_short_tunnels(atoms: list[_AtomicSegment]) -> list[_AtomicSegment]:
    result = list(atoms)
    index = 0
    while index < len(result):
        if result[index].segment_type != "tunnel":
            index += 1
            continue
        end = index
        length_km = 0.0
        while end < len(result) and result[end].segment_type == "tunnel":
            length_km += result[end].length_km
            end += 1
        if length_km < 0.3:
            for cursor in range(index, end):
                atom = result[cursor]
                result[cursor] = replace(atom, segment_type="new_surface_road")
        index = end
    return result


def _merge_tunnel_gaps(atoms: list[_AtomicSegment]) -> list[_AtomicSegment]:
    result = list(atoms)
    index = 1
    while index < len(result) - 1:
        if result[index].segment_type == "tunnel":
            index += 1
            continue
        gap_start = index
        gap_length_km = 0.0
        while index < len(result) and result[index].segment_type != "tunnel":
            gap_length_km += result[index].length_km
            index += 1
        has_tunnel_before = gap_start > 0 and result[gap_start - 1].segment_type == "tunnel"
        has_tunnel_after = index < len(result) and result[index].segment_type == "tunnel"
        if has_tunnel_before and has_tunnel_after and gap_length_km < 0.2:
            for cursor in range(gap_start, index):
                atom = result[cursor]
                result[cursor] = replace(atom, segment_type="tunnel")
    return result


def _weighted_optional(group: list[_AtomicSegment], attr: str) -> float | None:
    weighted = [
        (getattr(atom, attr), atom.length_km)
        for atom in group
        if getattr(atom, attr) is not None
    ]
    total = sum(length for _, length in weighted)
    if total <= 0:
        return None
    return sum(value * length for value, length in weighted) / total


def _max_attr(group: list[_AtomicSegment], attr: str) -> float | None:
    values = [getattr(atom, attr) for atom in group if getattr(atom, attr) is not None]
    return max(values) if values else None


def _min_attr(group: list[_AtomicSegment], attr: str) -> float | None:
    values = [getattr(atom, attr) for atom in group if getattr(atom, attr) is not None]
    return min(values) if values else None


def _first_present(group: list[_AtomicSegment], attr: str):
    for atom in group:
        value = getattr(atom, attr)
        if value is not None:
            return value
    return None


def _sum_optional(group: list[_AtomicSegment], attr: str) -> float | None:
    values = [getattr(atom, attr) for atom in group if getattr(atom, attr) is not None]
    return round(sum(values), 3) if values else None


def _risk_reasons(group: list[_AtomicSegment]) -> list[str]:
    reasons: list[str] = []
    for atom in group:
        reasons.extend(atom.risk_reasons)
    return list(dict.fromkeys(reasons))


def classify_route_segments(route_id: str, cells: list[CostCell]) -> dict:
    atoms = _merge_tunnel_gaps(_downgrade_short_tunnels(_atomic_segments(cells)))
    if not atoms:
        return {
            "new_surface_road_length_km": 0.0,
            "tunnel_length_km": 0.0,
            "tunnel_segment_count": 0,
            "segment_details": [],
            "crossing_review_required": False,
        }

    grouped: list[list[_AtomicSegment]] = []
    for atom in atoms:
        if not grouped or grouped[-1][-1].segment_type != atom.segment_type:
            grouped.append([atom])
        else:
            grouped[-1].append(atom)

    details: list[RouteSegmentDetail] = []
    for index, group in enumerate(grouped, start=1):
        segment_type = group[0].segment_type
        raw_length_km = sum(atom.length_km for atom in group)
        length_km = raw_length_km
        weighted_slope = (
            sum(atom.average_slope * atom.length_km for atom in group) / raw_length_km if raw_length_km else 0.0
        )
        geometry = [{"lat": group[0].start.lat, "lon": group[0].start.lon}]
        geometry.extend({"lat": atom.end.lat, "lon": atom.end.lon} for atom in group)
        details.append(
            RouteSegmentDetail(
                segment_id=f"{route_id}-S{index:03d}",
                segment_type=segment_type,
                segment_length_km=round(length_km, 3),
                segment_geometry=geometry,
                average_slope=round(weighted_slope, 2),
                max_slope=round(max(atom.max_slope for atom in group), 2),
                original_segment_type=_first_present(group, "original_segment_type") or segment_type,
                final_segment_type=segment_type,
                decision_status=_first_present(group, "decision_status"),
                feasibility_flag=_first_present(group, "feasibility_flag"),
                tunnel_score=round(_weighted_optional(group, "tunnel_score"), 2)
                if _weighted_optional(group, "tunnel_score") is not None
                else None,
                overburden_m=round(_weighted_optional(group, "overburden_m"), 2)
                if _weighted_optional(group, "overburden_m") is not None
                else None,
                overburden_condition=_first_present(group, "overburden_condition"),
                estimated_rock_class=_first_present(group, "estimated_rock_class"),
                rock_class=_first_present(group, "rock_class"),
                rock_ground_factor=round(_max_attr(group, "rock_ground_factor"), 2)
                if _max_attr(group, "rock_ground_factor") is not None
                else None,
                rock_constructability=_first_present(group, "rock_constructability"),
                road_grade_percent=round(_weighted_optional(group, "road_grade_percent"), 2)
                if _weighted_optional(group, "road_grade_percent") is not None
                else None,
                slope_deg=round(_weighted_optional(group, "slope_deg"), 2)
                if _weighted_optional(group, "slope_deg") is not None
                else None,
                local_relief_m=round(_max_attr(group, "local_relief_m"), 2)
                if _max_attr(group, "local_relief_m") is not None
                else None,
                fault_dist_m=round(_min_attr(group, "fault_dist_m"), 2)
                if _min_attr(group, "fault_dist_m") is not None
                else None,
                boundary_dist_m=round(_min_attr(group, "boundary_dist_m"), 2)
                if _min_attr(group, "boundary_dist_m") is not None
                else None,
                estimated_surface_cost_eok=_sum_optional(group, "estimated_surface_cost_eok"),
                estimated_tunnel_cost_eok=_sum_optional(group, "estimated_tunnel_cost_eok"),
                decision_reason=_first_present(group, "decision_reason"),
                risk_reasons=_risk_reasons(group),
            )
        )

    return {
        "new_surface_road_length_km": round(
            sum(item.segment_length_km for item in details if item.segment_type == "new_surface_road"),
            3,
        ),
        "tunnel_length_km": round(sum(item.segment_length_km for item in details if item.segment_type == "tunnel"), 3),
        "tunnel_segment_count": sum(1 for item in details if item.segment_type == "tunnel"),
        "segment_details": details,
        "crossing_review_required": any(
            "MVP에서는 교량 미반영" in reason
            for item in details
            for reason in (item.risk_reasons or [])
        ),
    }
