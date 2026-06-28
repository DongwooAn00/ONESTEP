from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger(__name__)
ROAD_ANNUAL_MAINTENANCE_RATE = 0.015
TUNNEL_ANNUAL_MAINTENANCE_RATE = 0.025
MAINTENANCE_ANALYSIS_YEARS = 30
MAINTENANCE_DISCOUNT_RATE = 0.045


def _as_dict(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return dict(value)


def _number(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def _rounded(value: float | None, digits: int = 3) -> float | None:
    return round(value, digits) if value is not None else None


@dataclass
class RouteReportData:
    route_id: str
    route_type: str
    from_node_id: str | None
    to_node_id: str | None
    total_length_km: float | None
    road_length_km: float | None
    existing_road_length_km: float | None
    connector_length_km: float | None
    new_road_length_km: float | None
    tunnel_length_km: float | None
    road_construction_cost: float | None
    tunnel_construction_cost: float | None
    land_compensation_cost: float | None
    annual_maintenance_cost: float | None
    maintenance_cost: float | None
    construction_cost: float | None
    total_project_cost: float | None
    annual_benefit: float | None
    total_benefit: float | None
    benefit_cost_ratio: float | None
    net_present_value: float | None
    economic_score: float | None
    distance_saving_km: float | None
    time_saving_minutes: float | None
    average_slope: float | None
    max_slope: float | None
    has_tunnel: bool
    uses_existing_road: bool
    has_new_road: bool
    crossing_review_required: bool
    unsupported_bridge_count: int = 0
    source_explanations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _maintenance_present_value(annual_cost: float | None) -> float | None:
    if annual_cost is None:
        return None
    factor = (
        (1.0 - (1.0 + MAINTENANCE_DISCOUNT_RATE) ** -MAINTENANCE_ANALYSIS_YEARS)
        / MAINTENANCE_DISCOUNT_RATE
    )
    return annual_cost * factor


def build_route_report_data(
    route: dict,
    *,
    segments: list[dict] | None = None,
    cost: dict | None = None,
    ranked_route: dict | None = None,
) -> RouteReportData:
    route = _as_dict(route)
    cost = _as_dict(cost)
    ranked = _as_dict(ranked_route)
    summary = _as_dict(ranked.get("summary"))
    active_segments = [_as_dict(item) for item in (segments or route.get("segments") or [])]

    bridge_segments = [
        item for item in active_segments if item.get("segment_type") == "bridge"
    ]
    if bridge_segments:
        logger.warning(
            "Route report ignored %s unsupported bridge segments for %s.",
            len(bridge_segments),
            route.get("route_id"),
        )
    supported_segments = [
        item for item in active_segments if item.get("segment_type") != "bridge"
    ]

    existing_length = _number(
        route.get("existing_road_length_km"),
        route.get("existing_length"),
        summary.get("existing_road_length_km"),
        cost.get("existing_road_length_km"),
    )
    connector_length = _number(
        route.get("connector_length_km"),
        route.get("connector_length"),
        summary.get("connector_length_km"),
        cost.get("connector_length_km"),
    )
    new_road_length = _number(
        route.get("new_surface_road_length_km"),
        route.get("new_road_length"),
        summary.get("new_surface_road_length_km"),
        cost.get("new_surface_road_length_km"),
        cost.get("surface_road_length_km"),
    )
    tunnel_length = _number(
        route.get("tunnel_length_km"),
        route.get("tunnel_length"),
        summary.get("tunnel_length_km"),
        cost.get("tunnel_length_km"),
    )
    total_length = _number(
        route.get("route_length_km"),
        route.get("total_length"),
        summary.get("route_length_km"),
    )
    length_parts = [existing_length, connector_length, new_road_length, tunnel_length]
    if total_length is None and any(value is not None for value in length_parts):
        total_length = sum(value or 0.0 for value in length_parts)
    road_length = (
        sum(value or 0.0 for value in (existing_length, connector_length, new_road_length))
        if any(value is not None for value in (existing_length, connector_length, new_road_length))
        else None
    )

    road_cost = _number(cost.get("new_road_screen_cost"), cost.get("surface_road_screen_cost"))
    connector_cost = _number(cost.get("connector_screen_cost"), cost.get("connector_cost"))
    if road_cost is not None or connector_cost is not None:
        road_construction_cost = (road_cost or 0.0) + (connector_cost or 0.0)
    else:
        road_construction_cost = _number(cost.get("surface_road_cost"), cost.get("new_road_cost"))
    tunnel_construction_cost = _number(cost.get("tunnel_screen_cost"), cost.get("tunnel_cost"))
    land_compensation = _as_dict(cost.get("land_compensation"))
    land_warnings = [
        str(item) for item in (land_compensation.get("warnings") or []) if item
    ]
    land_compensation_cost = _number(cost.get("land_compensation_cost"))
    if land_compensation_cost == 0.0 and land_warnings:
        land_compensation_cost = None
    construction_cost = _number(
        route.get("construction_cost"),
        ranked.get("construction_cost"),
        cost.get("total_screen_cost"),
        ranked.get("total_screen_cost"),
    )
    annual_maintenance = None
    if road_construction_cost is not None or tunnel_construction_cost is not None:
        annual_maintenance = (
            (road_construction_cost or 0.0) * ROAD_ANNUAL_MAINTENANCE_RATE
            + (tunnel_construction_cost or 0.0) * TUNNEL_ANNUAL_MAINTENANCE_RATE
        )
    maintenance_cost = _maintenance_present_value(annual_maintenance)
    total_project_cost = (
        (construction_cost or 0.0) + maintenance_cost
        if construction_cost is not None and maintenance_cost is not None
        else construction_cost
    )

    slopes = [
        _number(item.get("average_slope"))
        for item in supported_segments
        if _number(item.get("average_slope")) is not None
    ]
    max_slopes = [
        _number(item.get("max_slope"))
        for item in supported_segments
        if _number(item.get("max_slope")) is not None
    ]
    weighted_lengths = [
        _number(item.get("segment_length_km")) or 0.0 for item in supported_segments
    ]
    slope_weight = sum(weighted_lengths)
    average_slope = (
        sum(slope * length for slope, length in zip(slopes, weighted_lengths)) / slope_weight
        if slopes and slope_weight > 0 and len(slopes) == len(weighted_lengths)
        else (_number(route.get("average_slope")) if not slopes else sum(slopes) / len(slopes))
    )
    max_slope = max(max_slopes) if max_slopes else _number(route.get("max_slope"))

    warnings = list(dict.fromkeys(
        [str(item) for item in (route.get("warnings") or []) if item]
        + [str(item) for item in (ranked.get("warnings") or []) if item]
        + land_warnings
    ))
    crossing_review = bool(
        route.get("crossing_review_required")
        or any(
            "교량 미반영" in str(reason)
            for segment in supported_segments
            for reason in (segment.get("risk_reasons") or [])
        )
    )
    if bridge_segments:
        warnings.append(
            f"교량 segment {len(bridge_segments)}건은 MVP 보고서 계산에서 제외했습니다."
        )

    return RouteReportData(
        route_id=str(route.get("route_id") or ranked.get("route_id") or "unknown"),
        route_type=str(route.get("route_type") or ranked.get("route_type") or "unknown"),
        from_node_id=route.get("from_node_id") or ranked.get("from_node_id"),
        to_node_id=route.get("to_node_id") or ranked.get("to_node_id"),
        total_length_km=_rounded(total_length),
        road_length_km=_rounded(road_length),
        existing_road_length_km=_rounded(existing_length),
        connector_length_km=_rounded(connector_length),
        new_road_length_km=_rounded(new_road_length),
        tunnel_length_km=_rounded(tunnel_length),
        road_construction_cost=_rounded(road_construction_cost),
        tunnel_construction_cost=_rounded(tunnel_construction_cost),
        land_compensation_cost=_rounded(land_compensation_cost),
        annual_maintenance_cost=_rounded(annual_maintenance),
        maintenance_cost=_rounded(maintenance_cost),
        construction_cost=_rounded(construction_cost),
        total_project_cost=_rounded(total_project_cost),
        annual_benefit=_rounded(_number(route.get("annual_benefit"), ranked.get("annual_benefit"))),
        total_benefit=_rounded(_number(route.get("total_benefit"), ranked.get("total_benefit"))),
        benefit_cost_ratio=_rounded(_number(route.get("benefit_cost_ratio"), ranked.get("benefit_cost_ratio"))),
        net_present_value=_rounded(_number(route.get("net_benefit"), ranked.get("net_benefit"))),
        economic_score=_rounded(_number(route.get("candidate_score"), ranked.get("candidate_score"), ranked.get("economic_score")), 2),
        distance_saving_km=_rounded(_number(route.get("distance_saving_km"), ranked.get("distance_saving_km"))),
        time_saving_minutes=_rounded(_number(route.get("time_saving_minutes"), ranked.get("time_saving_minutes")), 2),
        average_slope=_rounded(average_slope, 2),
        max_slope=_rounded(max_slope, 2),
        has_tunnel=(tunnel_length or 0.0) > 0,
        uses_existing_road=(existing_length or 0.0) > 0,
        has_new_road=(new_road_length or 0.0) > 0,
        crossing_review_required=crossing_review,
        unsupported_bridge_count=len(bridge_segments),
        source_explanations=[str(item) for item in (route.get("explanation") or []) if item],
        warnings=list(dict.fromkeys(warnings)),
    )
