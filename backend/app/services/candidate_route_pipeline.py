from __future__ import annotations

import json
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from app.schemas.od_candidates import CandidateEdge, CandidateNode
from app.services import route_mvp_config as config
from app.services.cost_grid import (
    DemProvider,
    PostgisDemProvider,
    generate_dem_route_grid,
    lon_lat_to_dem,
)
from app.services.cost_model import calculate_route_costs, evaluate_candidate_against_baseline
from app.services.land_compensation import (
    LAND_COMPENSATION_EXPLANATION,
    NullParcelRepository,
    ParcelRepository,
    estimate_land_compensation,
)
from app.services.pathfinding import find_least_cost_path
from app.services.region_filter import RegionContext, build_region_context
from app.services.road_graph_routing import build_road_graph_route
from app.services.road_network import snap_geometry_to_road_centerline
from app.services.route_economics import rank_candidate_routes
from app.services.route_segments import RouteSegmentDetail, classify_route_segments


ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = ROOT / "data" / "processed"
DEFAULT_ROAD_WIDTH_M = 20.0
logger = logging.getLogger(__name__)


def _node_lookup(nodes: list[CandidateNode]) -> dict[str, CandidateNode]:
    return {node.node_id: node for node in nodes}


def _route_length_km_from_cells(cells) -> float:
    return round(
        sum(math.hypot(end.x - start.x, end.y - start.y) for start, end in zip(cells, cells[1:]))
        / 1000.0,
        3,
    )


def _geometry_length_km(geometry: list[dict[str, float]]) -> float:
    points = [lon_lat_to_dem(point["lon"], point["lat"]) for point in geometry]
    return round(
        sum(math.hypot(end.x - start.x, end.y - start.y) for start, end in zip(points, points[1:]))
        / 1000.0,
        3,
    )


def _route_geometry(cells) -> list[dict[str, float]]:
    return [{"lat": cell.lat, "lon": cell.lon} for cell in cells]


def _simplify_coordinate_sequence(
    coordinates: list[dict[str, float]],
    *,
    max_points: int,
) -> list[dict[str, float]]:
    """Bound display payload size while preserving endpoints and route order."""
    if len(coordinates) <= max_points:
        return coordinates
    step = math.ceil((len(coordinates) - 1) / (max_points - 1))
    simplified = coordinates[::step]
    if simplified[-1] != coordinates[-1]:
        simplified.append(coordinates[-1])
    return simplified


def _empty_land_compensation(road_width_m: float = DEFAULT_ROAD_WIDTH_M) -> dict:
    price_source_summary = {
        source: {"parcel_count": 0, "compensation_total": 0.0}
        for source in (
            "official",
            "knn_2km",
            "knn_5km",
            "district_avg",
            "province_avg",
            "global_median",
            "missing",
        )
    }
    return {
        "total_land_compensation": 0.0,
        "factor": 1.5,
        "road_width_m": road_width_m,
        "parcel_count": 0,
        "official_count": 0,
        "estimated_count": 0,
        "source_counts": {},
        "land_compensation_total": 0.0,
        "land_compensation_by_land_type": {
            "forest": 0.0,
            "farmland": 0.0,
            "residential": 0.0,
            "commercial_industrial": 0.0,
            "unknown": 0.0,
        },
        "price_source_summary": price_source_summary,
        "items": [],
        "warnings": [],
        "explanation": LAND_COMPENSATION_EXPLANATION,
    }


def _base_row(
    edge: CandidateEdge,
    route_id: str,
    route_type: str,
    *,
    status: str = "success",
    failed_reason: str | None = None,
) -> dict:
    return {
        "route_id": route_id,
        "route_type": route_type,
        "from_node_id": edge.from_node_id,
        "to_node_id": edge.to_node_id,
        "estimated_flow": edge.estimated_flow,
        "straight_distance_km": edge.straight_distance_km,
        "route_geometry": [],
        "route_length_km": 0.0,
        "existing_road_length_km": 0.0,
        "connector_length_km": 0.0,
        "new_surface_road_length_km": 0.0,
        "surface_road_length_km": 0.0,
        "tunnel_length_km": 0.0,
        "tunnel_segment_count": 0,
        "status": status,
        "failed_reason": failed_reason,
        "total_grid_cost": 0.0,
        "average_slope": 0.0,
        "max_slope": 0.0,
        "segment_details": [],
        "route_generation_method": "failed" if status == "failed" else "unknown",
        "warnings": [],
        "explanation": [],
        "crossing_review_required": False,
        "road_nodes_before": 0,
        "road_nodes_after": 0,
        "road_edges_before": 0,
        "road_edges_after": 0,
        "cost_grid_cell_count": 0,
        "a_star_call_count": 0,
        "origin_road_node_id": None,
        "destination_road_node_id": None,
        "origin_snap_distance_m": None,
        "destination_snap_distance_m": None,
        "land_compensation": _empty_land_compensation(),
        **calculate_route_costs(0.0, 0.0),
    }


def _failed_route(
    edge: CandidateEdge,
    route_id: str,
    route_type: str,
    reason: str,
) -> dict:
    row = _base_row(edge, route_id, route_type, status="failed", failed_reason=reason)
    row["explanation"] = [f"{route_type} 생성 실패: {reason}"]
    return row


def _renumber_segments(route_id: str, segments: list[dict]) -> list[dict]:
    output = []
    for index, segment in enumerate(segments, start=1):
        normalized = dict(segment)
        normalized["route_id"] = route_id
        normalized["segment_id"] = f"{route_id}-S{index:03d}"
        if normalized.get("segment_type") == "surface_road":
            normalized["segment_type"] = "new_surface_road"
        if normalized.get("segment_type") == "existing_tunnel":
            normalized["segment_type"] = "existing_road"
        output.append(normalized)
    return output


def _segment_rows(route_id: str, details: list[RouteSegmentDetail]) -> list[dict]:
    rows = _renumber_segments(
        route_id,
        [{"route_id": route_id, **asdict(item)} for item in details],
    )
    existing_indexes = [
        index
        for index, row in enumerate(rows)
        if row.get("segment_type") == "existing_road"
        and len(row.get("segment_geometry", [])) >= 2
    ]
    if not existing_indexes:
        return rows

    flat_geometry: list[dict[str, float]] = []
    slices: dict[int, tuple[int, int]] = {}
    for index in existing_indexes:
        start = len(flat_geometry)
        flat_geometry.extend(rows[index]["segment_geometry"])
        slices[index] = (start, len(flat_geometry))
    try:
        snapped, snap_mask = snap_geometry_to_road_centerline(
            flat_geometry,
            max_distance_m=config.EXISTING_ROAD_CLASSIFICATION_DISTANCE_M,
        )
    except Exception as error:
        logger.warning("%s existing-road geometry snap failed: %s", route_id, error)
        return rows

    for index in existing_indexes:
        start, end = slices[index]
        if all(snap_mask[start:end]):
            geometry = snapped[start:end]
            rows[index]["segment_geometry"] = geometry
            rows[index]["segment_length_km"] = _geometry_length_km(geometry)
            rows[index]["geometry_source"] = "road_centerline_snap"
        else:
            # Never paint a partially unmatched DEM line as an existing road.
            rows[index]["segment_type"] = "new_surface_road"
            rows[index]["final_segment_type"] = "new_surface_road"
            rows[index]["decision_status"] = "road_centerline_snap_failed"
    return rows


def _project_route_geometry(route_geometry: list[dict[str, float]]):
    """Convert WGS84 route coordinates to a meter-based DEM CRS line."""
    from shapely.geometry import LineString

    points = [lon_lat_to_dem(point["lon"], point["lat"]) for point in route_geometry]
    if len(points) < 2:
        raise ValueError("토지보상비 계산에는 경로 좌표가 2개 이상 필요합니다.")
    return LineString([(point.x, point.y) for point in points])


def _project_new_build_geometry(row: dict):
    """Preserve disconnected construction segments as a MultiLineString."""
    from shapely.geometry import MultiLineString

    lines = []
    for segment in row.get("segment_details", []):
        if segment.get("segment_type") not in {"connector", "new_surface_road"}:
            continue
        geometry = segment.get("segment_geometry", [])
        if len(geometry) < 2:
            continue
        points = [
            lon_lat_to_dem(point["lon"], point["lat"])
            for point in geometry
        ]
        lines.append([(point.x, point.y) for point in points])
    if not lines:
        raise ValueError("토지보상비 계산 대상 신규 건설 구간이 없습니다.")
    return MultiLineString(lines)


def _new_build_geometry(row: dict) -> list[dict[str, float]]:
    eligible = [
        segment
        for segment in row.get("segment_details", [])
        if segment.get("segment_type") in {"connector", "new_surface_road"}
    ]
    coordinates: list[dict[str, float]] = []
    for segment in eligible:
        geometry = segment.get("segment_geometry", [])
        if not geometry:
            continue
        if coordinates and coordinates[-1] == geometry[0]:
            coordinates.extend(geometry[1:])
        else:
            coordinates.extend(geometry)
    return coordinates


def _apply_land_compensation(
    row: dict,
    *,
    parcel_repository: ParcelRepository | None,
    road_width_m: float,
    region_context: RegionContext | None = None,
) -> dict:
    """Apply land compensation only to connector/new-surface construction."""
    if row.get("status") != "success":
        return row

    new_build_geometry = _new_build_geometry(row)
    active_repository = parcel_repository or NullParcelRepository()
    if len(new_build_geometry) < 2:
        compensation = _empty_land_compensation(road_width_m)
    else:
        try:
            route_geom = (
                new_build_geometry
                if parcel_repository is None
                else _project_new_build_geometry(row)
            )
            compensation = estimate_land_compensation(
                route_geom,
                road_width_m,
                active_repository,
            )
        except Exception as error:
            compensation = _empty_land_compensation(road_width_m)
            compensation["warnings"] = [
                f"토지보상비 후처리 실패로 건설비만 반영했습니다: {error}"
            ]

    land_cost_eok = float(compensation["total_land_compensation"]) / 100_000_000.0
    row.update(
        calculate_route_costs(
            row["new_surface_road_length_km"],
            row["tunnel_length_km"],
            connector_length_km=row["connector_length_km"],
            land_compensation_cost_eok=land_cost_eok,
        )
    )
    row["land_compensation"] = compensation
    compensation["region_filter"] = (
        region_context.summary()
        if region_context is not None
        else build_region_context().summary()
    )
    row["warnings"] = list(row.get("warnings", [])) + list(compensation.get("warnings", []))
    return row


def _baseline_candidate(
    edge: CandidateEdge,
    nodes: list[CandidateNode],
    *,
    route_id: str,
    region_context: RegionContext | None,
) -> dict:
    graph_route = build_road_graph_route(
        edge,
        nodes,
        route_id=route_id,
        region_context=region_context,
    )
    row = _base_row(edge, route_id, "existing_baseline")
    row.update(
        {
            "route_geometry": graph_route.route_geometry,
            "route_length_km": graph_route.route_length_km,
            "existing_road_length_km": round(
                graph_route.existing_road_length_km + graph_route.existing_tunnel_length_km,
                3,
            ),
            "connector_length_km": graph_route.connector_length_km,
            "segment_details": _renumber_segments(route_id, graph_route.segment_details),
            "route_generation_method": "road_graph_a_star_baseline",
            "warnings": graph_route.warnings,
            "road_nodes_before": graph_route.road_nodes_before,
            "road_nodes_after": graph_route.road_nodes_after,
            "road_edges_before": graph_route.road_edges_before,
            "road_edges_after": graph_route.road_edges_after,
            "a_star_call_count": 1,
            "origin_road_node_id": getattr(graph_route, "origin_road_node_id", None),
            "destination_road_node_id": getattr(graph_route, "destination_road_node_id", None),
            "origin_snap_distance_m": getattr(graph_route, "origin_snap_distance_m", None),
            "destination_snap_distance_m": getattr(graph_route, "destination_snap_distance_m", None),
            "explanation": [
                "기존 도로망 A* 경로이며 신규 후보의 거리·시간·편익 비교 기준입니다.",
                "기존 도로 구간의 신규 건설비는 0으로 계산했습니다.",
            ],
        }
    )
    row.update(
        calculate_route_costs(
            0.0,
            0.0,
            connector_length_km=row["connector_length_km"],
        )
    )
    return row


def _dem_link(
    edge: CandidateEdge,
    *,
    route_id: str,
    route_type: str,
    start: dict[str, float],
    end: dict[str, float],
    dem_provider: DemProvider | None,
    apply_optional_layers: bool,
    region_context: RegionContext | None,
    buffer_multiplier: float,
) -> dict:
    grid, projected_start, projected_end = generate_dem_route_grid(
        start["lat"],
        start["lon"],
        end["lat"],
        end["lon"],
        candidate_id=route_id,
        buffer_multiplier=buffer_multiplier,
        dem_provider=dem_provider,
        apply_optional_layers=apply_optional_layers,
        region_context=region_context,
    )
    try:
        path = find_least_cost_path(grid, projected_start, projected_end)
        a_star_calls = 1
    except ValueError:
        grid, projected_start, projected_end = generate_dem_route_grid(
            start["lat"],
            start["lon"],
            end["lat"],
            end["lon"],
            candidate_id=route_id,
            buffer_multiplier=buffer_multiplier * 2.0,
            dem_provider=dem_provider,
            apply_optional_layers=apply_optional_layers,
            region_context=region_context,
        )
        path = find_least_cost_path(grid, projected_start, projected_end)
        a_star_calls = 2

    route_length_km = _route_length_km_from_cells(path.cells)
    segment_summary = classify_route_segments(route_id, path.cells)
    details = _segment_rows(route_id, segment_summary["segment_details"])
    existing_road_length_km = round(
        sum(
            detail["segment_length_km"]
            for detail in details
            if detail["segment_type"] == "existing_road"
        ),
        3,
    )
    new_surface_road_length_km = round(
        sum(
            detail["segment_length_km"]
            for detail in details
            if detail["segment_type"] == "new_surface_road"
        ),
        3,
    )
    tunnel_length_km = round(
        sum(
            detail["segment_length_km"]
            for detail in details
            if detail["segment_type"] == "tunnel"
        ),
        3,
    )
    route_length_km = round(
        existing_road_length_km + new_surface_road_length_km + tunnel_length_km,
        3,
    )
    crossing_review_required = bool(segment_summary["crossing_review_required"])
    explanation = [
        "기존 도로 저비용 편향 없이 DEM 비용격자 A*로 생성한 신규 링크입니다.",
        "경사·고저차·지형 위험·하천 회피 패널티를 반영했습니다.",
    ]
    if crossing_review_required:
        explanation.append("하천·계곡 위험이 감지되었습니다. MVP에서는 교량 미반영, 추가 검토 필요.")

    row = _base_row(edge, route_id, route_type)
    row.update(
        {
            "route_geometry": _route_geometry(path.cells),
            "route_length_km": route_length_km,
            "existing_road_length_km": existing_road_length_km,
            "new_surface_road_length_km": new_surface_road_length_km,
            "surface_road_length_km": new_surface_road_length_km,
            "tunnel_length_km": tunnel_length_km,
            "tunnel_segment_count": segment_summary["tunnel_segment_count"],
            "total_grid_cost": path.total_grid_cost,
            "average_slope": round(
                sum(cell.slope_degrees for cell in path.cells) / len(path.cells),
                2,
            )
            if path.cells
            else 0.0,
            "max_slope": round(max((cell.slope_degrees for cell in path.cells), default=0.0), 2),
            "segment_details": details,
            "route_generation_method": "dem_grid_a_star",
            "warnings": grid.warnings,
            "explanation": explanation,
            "crossing_review_required": crossing_review_required,
            "cost_grid_cell_count": grid.width * grid.height,
            "a_star_call_count": a_star_calls,
        }
    )
    row.update(
        calculate_route_costs(
            row["new_surface_road_length_km"],
            row["tunnel_length_km"],
        )
    )
    return row


def _new_direct_candidate(
    edge: CandidateEdge,
    nodes: list[CandidateNode],
    *,
    route_id: str,
    dem_provider: DemProvider | None,
    apply_optional_layers: bool,
    region_context: RegionContext | None,
    buffer_multiplier: float,
) -> dict:
    by_id = _node_lookup(nodes)
    from_node = by_id[edge.from_node_id]
    to_node = by_id[edge.to_node_id]
    return _dem_link(
        edge,
        route_id=route_id,
        route_type="new_direct",
        start={"lat": from_node.latitude, "lon": from_node.longitude},
        end={"lat": to_node.latitude, "lon": to_node.longitude},
        dem_provider=dem_provider,
        apply_optional_layers=apply_optional_layers,
        region_context=region_context,
        buffer_multiplier=buffer_multiplier,
    )


def _simple_segment(
    route_id: str,
    segment_type: str,
    geometry: list[dict[str, float]],
) -> dict | None:
    if len(geometry) < 2:
        return None
    length_km = _geometry_length_km(geometry)
    if length_km <= 0:
        return None
    return {
        "route_id": route_id,
        "segment_id": "",
        "segment_type": segment_type,
        "segment_length_km": length_km,
        "segment_geometry": geometry,
        "average_slope": 0.0,
        "max_slope": 0.0,
        "original_segment_type": segment_type,
        "final_segment_type": segment_type,
        "decision_status": "existing_asset" if segment_type == "existing_road" else "connector",
        "risk_reasons": [],
    }


def _baseline_context_segments(
    route_id: str,
    baseline: dict,
    start_index: int,
    end_index: int,
) -> list[dict]:
    geometry = baseline["route_geometry"]
    baseline_segments = baseline.get("segment_details", [])
    start_connector = next(
        (
            segment
            for segment in baseline_segments
            if segment.get("segment_type") == "connector"
        ),
        None,
    )
    end_connector = next(
        (
            segment
            for segment in reversed(baseline_segments)
            if segment.get("segment_type") == "connector"
        ),
        None,
    )
    start_road_index = max(
        0,
        len((start_connector or {}).get("segment_geometry", [])) - 1,
    )
    end_road_index = min(
        len(geometry) - 1,
        len(geometry) - len((end_connector or {}).get("segment_geometry", [])),
    )
    segments: list[dict] = []
    if start_index >= 1:
        connector = _simple_segment(
            route_id,
            "connector",
            geometry[: start_road_index + 1],
        )
        existing = _simple_segment(
            route_id,
            "existing_road",
            geometry[start_road_index : start_index + 1],
        )
        segments.extend(item for item in (connector, existing) if item)
    if end_index < len(geometry) - 1:
        existing = _simple_segment(
            route_id,
            "existing_road",
            geometry[end_index : end_road_index + 1],
        )
        connector = _simple_segment(
            route_id,
            "connector",
            geometry[end_road_index:],
        )
        segments.extend(item for item in (existing, connector) if item)
    return segments


def _hybrid_candidate(
    edge: CandidateEdge,
    baseline: dict,
    *,
    route_id: str,
    route_type: str,
    start_fraction: float,
    end_fraction: float,
    dem_provider: DemProvider | None,
    apply_optional_layers: bool,
    region_context: RegionContext | None,
    buffer_multiplier: float,
) -> dict:
    geometry = baseline["route_geometry"]
    if len(geometry) < 6:
        raise ValueError("기존 도로 baseline의 샘플 포인트가 부족합니다.")
    start_index = max(1, min(len(geometry) - 4, round((len(geometry) - 1) * start_fraction)))
    end_index = max(start_index + 2, min(len(geometry) - 2, round((len(geometry) - 1) * end_fraction)))
    prefix = geometry[: start_index + 1]
    suffix = geometry[end_index:]
    shortcut = _dem_link(
        edge,
        route_id=route_id,
        route_type=route_type,
        start=geometry[start_index],
        end=geometry[end_index],
        dem_provider=dem_provider,
        apply_optional_layers=apply_optional_layers,
        region_context=region_context,
        buffer_multiplier=buffer_multiplier,
    )

    context_segments = _baseline_context_segments(
        route_id,
        baseline,
        start_index,
        end_index,
    )
    shortcut_segments = shortcut["segment_details"]
    segments = _renumber_segments(route_id, context_segments + shortcut_segments)
    combined_geometry = prefix + shortcut["route_geometry"][1:-1] + suffix
    existing_length = round(
        sum(item["segment_length_km"] for item in segments if item["segment_type"] == "existing_road"),
        3,
    )
    connector_length = round(
        sum(item["segment_length_km"] for item in segments if item["segment_type"] == "connector"),
        3,
    )
    new_road_length = round(
        sum(item["segment_length_km"] for item in segments if item["segment_type"] == "new_surface_road"),
        3,
    )
    tunnel_length = round(
        sum(item["segment_length_km"] for item in segments if item["segment_type"] == "tunnel"),
        3,
    )

    shortcut.update(
        {
            "route_geometry": combined_geometry,
            "route_length_km": round(
                existing_length + connector_length + new_road_length + tunnel_length,
                3,
            ),
            "existing_road_length_km": existing_length,
            "connector_length_km": connector_length,
            "new_surface_road_length_km": new_road_length,
            "surface_road_length_km": new_road_length,
            "tunnel_length_km": tunnel_length,
            "tunnel_segment_count": sum(
                1 for item in segments if item["segment_type"] == "tunnel"
            ),
            "segment_details": segments,
            "route_generation_method": "road_baseline_plus_dem_shortcut",
            "explanation": [
                f"기존 도로 경로의 {start_fraction:.0%}~{end_fraction:.0%} 우회 구간을 DEM 신규 링크로 대체했습니다.",
                "기존 도로는 접속·보조 구간으로만 유지하고 신규 링크의 효과를 baseline과 비교합니다.",
            ]
            + (
                ["하천·계곡 위험이 감지되었습니다. MVP에서는 교량 미반영, 추가 검토 필요."]
                if shortcut.get("crossing_review_required")
                else []
            ),
        }
    )
    shortcut.update(
        calculate_route_costs(
            new_road_length,
            tunnel_length,
            connector_length_km=connector_length,
        )
    )
    return shortcut


def evaluate_candidate_edge_candidates(
    edge: CandidateEdge,
    nodes: list[CandidateNode],
    *,
    dem_provider: DemProvider | None = None,
    apply_optional_layers: bool = True,
    buffer_multiplier: float = 0.3,
    region_context: RegionContext | None = None,
) -> list[dict]:
    prefix = f"R{edge.rank:03d}"
    candidates: list[dict] = []
    baseline: dict | None = None

    if apply_optional_layers:
        try:
            baseline = _baseline_candidate(
                edge,
                nodes,
                route_id=f"{prefix}-B",
                region_context=region_context,
            )
            candidates.append(baseline)
        except Exception as error:
            logger.warning("%s baseline generation failed: %s", prefix, error)

    direct_candidate: dict | None = None
    search_jobs: list[tuple[str, str, object]] = [
        (
            "D",
            "new_direct",
            lambda: _new_direct_candidate(
                edge,
                nodes,
                route_id=f"{prefix}-D",
                dem_provider=dem_provider,
                apply_optional_layers=apply_optional_layers,
                region_context=region_context,
                buffer_multiplier=buffer_multiplier,
            ),
        )
    ]
    if baseline is not None:
        for suffix, route_type, start_fraction, end_fraction, active_buffer in (
            ("H", "hybrid_new_existing", 0.20, 0.70, buffer_multiplier),
            ("P", "bypass_improvement", 0.35, 0.85, buffer_multiplier * 0.75),
        ):
            search_jobs.append(
                (
                    suffix,
                    route_type,
                    lambda suffix=suffix,
                    route_type=route_type,
                    start_fraction=start_fraction,
                    end_fraction=end_fraction,
                    active_buffer=active_buffer: _hybrid_candidate(
                        edge,
                        baseline,
                        route_id=f"{prefix}-{suffix}",
                        route_type=route_type,
                        start_fraction=start_fraction,
                        end_fraction=end_fraction,
                        dem_provider=dem_provider,
                        apply_optional_layers=apply_optional_layers,
                        region_context=region_context,
                        buffer_multiplier=active_buffer,
                    ),
                )
            )

    completed: dict[str, dict] = {}
    with ThreadPoolExecutor(
        max_workers=min(config.MAX_PARALLEL_ROUTE_SEARCHES, len(search_jobs))
    ) as executor:
        futures = {
            executor.submit(job): (suffix, route_type)
            for suffix, route_type, job in search_jobs
        }
        for future in as_completed(futures):
            suffix, route_type = futures[future]
            try:
                completed[suffix] = future.result()
            except Exception as error:
                if route_type == "new_direct":
                    completed[suffix] = _failed_route(
                        edge,
                        f"{prefix}-D",
                        "new_direct",
                        str(error),
                    )
                else:
                    logger.warning(
                        "%s %s generation failed: %s",
                        prefix,
                        route_type,
                        error,
                    )

    for suffix in ("D", "H", "P"):
        candidate = completed.get(suffix)
        if candidate is not None:
            candidates.append(candidate)
    direct_candidate = completed.get("D")

    # A dedicated tunnel shortcut is expensive and commonly discarded. Run it
    # only after the direct route confirms that tunnel conditions exist.
    if (
        baseline is not None
        and direct_candidate is not None
        and direct_candidate.get("status") == "success"
        and direct_candidate.get("tunnel_length_km", 0.0) > 0
    ):
        try:
            tunnel_candidate = _hybrid_candidate(
                edge,
                baseline,
                route_id=f"{prefix}-T",
                route_type="tunnel_shortcut",
                start_fraction=0.15,
                end_fraction=0.85,
                dem_provider=dem_provider,
                apply_optional_layers=apply_optional_layers,
                region_context=region_context,
                buffer_multiplier=max(0.08, buffer_multiplier * 0.4),
            )
            if tunnel_candidate["tunnel_length_km"] > 0:
                candidates.append(tunnel_candidate)
        except Exception as error:
            logger.warning("%s tunnel_shortcut generation failed: %s", prefix, error)

    if baseline is not None:
        evaluate_candidate_against_baseline(baseline, baseline)
    for candidate in candidates:
        if candidate is baseline or candidate["status"] != "success":
            continue
        evaluate_candidate_against_baseline(candidate, baseline)
    return candidates


def evaluate_candidate_edge(
    edge: CandidateEdge,
    nodes: list[CandidateNode],
    **kwargs,
) -> dict:
    """Backward-compatible single-row helper returning the direct new route."""
    candidates = evaluate_candidate_edge_candidates(edge, nodes, **kwargs)
    return next(
        (row for row in candidates if row["route_type"] == "new_direct"),
        candidates[0],
    )


def _write_json(filename: str, payload) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _public_route(row: dict) -> dict:
    display_geometry = _simplify_coordinate_sequence(
        row["route_geometry"],
        max_points=500,
    )
    land_compensation = row.get("land_compensation", _empty_land_compensation())
    return {
        "route_id": row["route_id"],
        "route_type": row["route_type"],
        "from_node_id": row["from_node_id"],
        "to_node_id": row["to_node_id"],
        "route_geometry": display_geometry,
        "geometry": display_geometry,
        # Segment geometry is returned once in the top-level `segments` array.
        "segments": [],
        "route_length_km": row["route_length_km"],
        "total_length": row["route_length_km"],
        "existing_length": row.get("existing_road_length_km", 0.0),
        "existing_road_length_km": row.get("existing_road_length_km", 0.0),
        "connector_length": row.get("connector_length_km", 0.0),
        "connector_length_km": row.get("connector_length_km", 0.0),
        "new_road_length": row.get("new_surface_road_length_km", 0.0),
        "new_surface_road_length_km": row.get("new_surface_road_length_km", 0.0),
        "tunnel_length": row.get("tunnel_length_km", 0.0),
        "tunnel_length_km": row.get("tunnel_length_km", 0.0),
        "estimated_flow": row.get("estimated_flow", 0.0),
        "saving_score": row.get("saving_score", 0.0),
        "diversion_rate": row.get("diversion_rate", 0.0),
        "diverted_flow": row.get("diverted_flow", 0.0),
        "access_road_length_km": row.get("connector_length_km", 0.0),
        "existing_road_ratio": row.get("existing_road_ratio", 0.0),
        "new_construction_ratio": row.get("new_construction_ratio", 0.0),
        "construction_cost": row.get("construction_cost", row.get("total_screen_cost", 0.0)),
        "land_compensation_total": land_compensation.get(
            "land_compensation_total",
            land_compensation.get("total_land_compensation", 0.0),
        ),
        "land_compensation_by_land_type": land_compensation.get(
            "land_compensation_by_land_type",
            {},
        ),
        "price_source_summary": land_compensation.get("price_source_summary", {}),
        "annual_benefit": row.get("annual_benefit", 0.0),
        "annual_time_benefit": row.get("annual_time_benefit", 0.0),
        "annual_distance_benefit": row.get("annual_distance_benefit", 0.0),
        "annual_benefit_before_diversion": row.get("annual_benefit_before_diversion", 0.0),
        "total_benefit": row.get("total_benefit", 0.0),
        "total_benefit_before_diversion": row.get("total_benefit_before_diversion", 0.0),
        "benefit_cost_ratio": row.get("benefit_cost_ratio", 0.0),
        "bc_ratio": row.get("bc_ratio", row.get("benefit_cost_ratio", 0.0)),
        "net_benefit": row.get("net_benefit", 0.0),
        "distance_saving": row.get("distance_saving_km", 0.0),
        "distance_saving_km": row.get("distance_saving_km", 0.0),
        "time_saving": row.get("time_saving_minutes", 0.0),
        "time_saving_minutes": row.get("time_saving_minutes", 0.0),
        "time_saving_hours": row.get("time_saving_hours", 0.0),
        "new_segment_ratio": row.get("new_segment_ratio", 0.0),
        "distance_saving_ratio": row.get("distance_saving_ratio", 0.0),
        "time_saving_ratio": row.get("time_saving_ratio", 0.0),
        "is_meaningful_improvement": row.get("is_meaningful_improvement", False),
        "candidate_score": row.get("candidate_score", 0.0),
        "explanation": row.get("explanation", []),
        "crossing_review_required": row.get("crossing_review_required", False),
        "existing_road_access_length_km": row.get("existing_road_length_km", 0.0),
        "existing_road_access_percent": round(
            row.get("existing_road_length_km", 0.0) / row["route_length_km"] * 100.0,
            1,
        )
        if row["route_length_km"] > 0
        else 0.0,
        "route_generation_method": row["route_generation_method"],
        "origin_road_node_id": row.get("origin_road_node_id"),
        "destination_road_node_id": row.get("destination_road_node_id"),
        "origin_snap_distance_m": row.get("origin_snap_distance_m"),
        "destination_snap_distance_m": row.get("destination_snap_distance_m"),
        "status": row["status"],
        "failed_reason": row["failed_reason"],
    }


def _public_cost(row: dict) -> dict:
    return {
        "route_id": row["route_id"],
        "existing_road_length_km": row.get("existing_road_length_km", 0.0),
        "connector_length_km": row.get("connector_length_km", 0.0),
        "new_surface_road_length_km": row.get("new_surface_road_length_km", 0.0),
        "surface_road_length_km": row.get("new_surface_road_length_km", 0.0),
        "tunnel_length_km": row.get("tunnel_length_km", 0.0),
        "surface_road_cost": row.get("surface_road_cost", 0.0),
        "new_road_cost": row.get("new_road_cost", 0.0),
        "connector_cost": row.get("connector_cost", 0.0),
        "tunnel_cost": row.get("tunnel_cost", 0.0),
        "land_compensation_cost": row.get("land_compensation_cost", 0.0),
        "land_compensation": row.get("land_compensation", _empty_land_compensation()),
        "total_direct_cost": row.get("total_direct_cost", 0.0),
        "surface_road_screen_cost": row.get("surface_road_screen_cost", 0.0),
        "new_road_screen_cost": row.get("new_road_screen_cost", 0.0),
        "connector_screen_cost": row.get("connector_screen_cost", 0.0),
        "tunnel_screen_cost": row.get("tunnel_screen_cost", 0.0),
        "total_screen_cost": row.get("total_screen_cost", 0.0),
        "cost_assumptions": row.get("cost_assumptions", {}),
    }


def _build_output_files(rows: list[dict], ranked_rows: list[dict]) -> dict[str, list[dict]]:
    public_segments = []
    for row in rows:
        for segment in row["segment_details"]:
            public_segment = dict(segment)
            public_segment["segment_geometry"] = _simplify_coordinate_sequence(
                segment.get("segment_geometry", []),
                max_points=300,
            )
            public_segments.append(public_segment)
    return {
        "candidate_routes.json": [_public_route(row) for row in rows],
        "candidate_route_segments.json": public_segments,
        "candidate_route_costs.json": [_public_cost(row) for row in rows],
        "ranked_candidate_routes.json": ranked_rows,
    }


def build_candidate_routes(
    nodes: list[CandidateNode],
    edges: list[CandidateEdge],
    *,
    route_limit: int = config.DEFAULT_ROUTE_LIMIT,
    dem_provider: DemProvider | None = None,
    apply_optional_layers: bool = True,
    persist_files: bool = True,
    parcel_repository: ParcelRepository | None = None,
    road_width_m: float = DEFAULT_ROAD_WIDTH_M,
    selected_regions: list[str] | None = None,
    use_region_filter: bool = False,
    region_buffer_km: float = 10.0,
) -> dict:
    started_at = time.perf_counter()
    region_context = build_region_context(
        selected_regions,
        use_region_filter,
        region_buffer_km,
    )
    nodes_before = len(nodes)
    edges_before = len(edges)
    if region_context.enabled:
        active_nodes = [
            node
            for node in nodes
            if region_context.contains_point(node.longitude, node.latitude)
        ]
        active_node_ids = {node.node_id for node in active_nodes}
        active_edges = [
            edge
            for edge in edges
            if edge.from_node_id in active_node_ids and edge.to_node_id in active_node_ids
        ]
        if len(active_nodes) < 2 or not active_edges:
            raise ValueError(
                "선택 구역 내 후보 노드/엣지가 부족합니다. 구역을 추가하거나 "
                "region_buffer_km를 늘린 뒤 OD 후보를 다시 생성해주세요."
            )
    else:
        active_nodes = nodes
        active_edges = edges

    active_limit = min(max(route_limit, config.MIN_ROUTE_LIMIT), config.MAX_ROUTE_LIMIT)
    ordered_edges = sorted(
        active_edges,
        key=lambda edge: edge.estimated_flow,
        reverse=True,
    )
    active_dem_provider = dem_provider or PostgisDemProvider()

    generated_rows: list[dict] = []
    evaluated_edges: list[CandidateEdge] = []
    successful_new_count = 0
    for edge in ordered_edges:
        evaluated_edges.append(edge)
        edge_candidates = evaluate_candidate_edge_candidates(
            edge,
            active_nodes,
            dem_provider=active_dem_provider,
            apply_optional_layers=apply_optional_layers,
            region_context=region_context,
        )
        baseline = next(
            (row for row in edge_candidates if row["route_type"] == "existing_baseline"),
            None,
        )
        processed = [
            _apply_land_compensation(
                row,
                parcel_repository=parcel_repository,
                road_width_m=road_width_m,
                region_context=region_context,
            )
            for row in edge_candidates
        ]
        # Land compensation changes construction cost, so refresh benefits/scores.
        for row in processed:
            if row["status"] == "success":
                evaluate_candidate_against_baseline(row, baseline)
                logger.info(
                    "[CandidateRoute] candidate_id=%s origin_node_id=%s "
                    "destination_node_id=%s straight_distance_km=%.3f "
                    "existing_baseline_length_km=%.3f final_route_length_km=%.3f "
                    "existing_road_length_km=%.3f new_road_length_km=%.3f "
                    "tunnel_length_km=%.3f existing_road_ratio=%.4f "
                    "distance_saving_ratio=%.4f time_saving_ratio=%.4f "
                    "construction_cost=%.3f candidate_score=%.2f "
                    "route_generation_method=%s estimated_flow=%.3f "
                    "saving_score=%.4f diversion_rate=%.4f diverted_flow=%.3f "
                    "annual_benefit=%.3f total_benefit=%.3f bc_ratio=%.3f",
                    row["route_id"],
                    row["from_node_id"],
                    row["to_node_id"],
                    row.get("straight_distance_km", 0.0),
                    baseline.get("route_length_km", 0.0) if baseline else 0.0,
                    row.get("route_length_km", 0.0),
                    row.get("existing_road_length_km", 0.0),
                    row.get("new_surface_road_length_km", 0.0),
                    row.get("tunnel_length_km", 0.0),
                    row.get("existing_road_ratio", 0.0),
                    row.get("distance_saving_ratio", 0.0),
                    row.get("time_saving_ratio", 0.0),
                    row.get("construction_cost", 0.0),
                    row.get("candidate_score", 0.0),
                    row.get("route_generation_method", "unknown"),
                    row.get("estimated_flow", 0.0),
                    row.get("saving_score", 0.0),
                    row.get("diversion_rate", 0.0),
                    row.get("diverted_flow", 0.0),
                    row.get("annual_benefit", 0.0),
                    row.get("total_benefit", 0.0),
                    row.get("bc_ratio", 0.0),
                )
        generated_rows.extend(processed)
        successful_new_count += sum(
            1
            for row in processed
            if row["status"] == "success"
            and row["route_type"] != "existing_baseline"
        )
        if successful_new_count >= active_limit:
            break

    ranked_rows = rank_candidate_routes(generated_rows)[:active_limit]
    selected_route_ids = {row["route_id"] for row in ranked_rows}
    selected_pairs = {
        (row["from_node_id"], row["to_node_id"])
        for row in ranked_rows
    }
    rows = [
        row
        for row in generated_rows
        if row["route_id"] in selected_route_ids
        or (
            row["route_type"] == "existing_baseline"
            and (row["from_node_id"], row["to_node_id"]) in selected_pairs
        )
        or (not ranked_rows and row["status"] == "failed")
    ]
    best_row = max(
        (row for row in rows if row["status"] == "success"),
        key=lambda row: row.get("candidate_score", 0.0),
        default=None,
    )
    output_files = _build_output_files(rows, ranked_rows)
    saved_paths = (
        {
            filename: _write_json(filename, payload)
            for filename, payload in output_files.items()
        }
        if persist_files
        else {}
    )

    elapsed_seconds = round(time.perf_counter() - started_at, 3)
    region_filter_summary = region_context.summary(
        candidate_nodes_before=nodes_before,
        candidate_nodes_after=len(active_nodes),
        candidate_edges_before=edges_before,
        candidate_edges_after=len(active_edges),
        road_nodes_before=sum(row.get("road_nodes_before", 0) for row in rows),
        road_nodes_after=sum(row.get("road_nodes_after", 0) for row in rows),
        road_edges_before=sum(row.get("road_edges_before", 0) for row in rows),
        road_edges_after=sum(row.get("road_edges_after", 0) for row in rows),
        cost_grid_cells=sum(row.get("cost_grid_cell_count", 0) for row in rows),
        a_star_calls=sum(row.get("a_star_call_count", 0) for row in rows),
        elapsed_seconds=elapsed_seconds,
    )
    logger.info(
        "[Pipeline] edges=%s candidates=%s A*=%s elapsed_seconds=%s",
        len(evaluated_edges),
        len(rows),
        region_filter_summary["a_star_calls"],
        elapsed_seconds,
    )

    best_candidate = _public_route(best_row) if best_row is not None else None
    return {
        "routes": output_files["candidate_routes.json"],
        "candidates": output_files["candidate_routes.json"],
        "segments": output_files["candidate_route_segments.json"],
        "costs": output_files["candidate_route_costs.json"],
        "ranked_routes": ranked_rows,
        "best_candidate": best_candidate,
        # Singular legacy field requested by the expanded contract.
        "route": best_candidate,
        "warnings": sorted(
            {warning for row in rows for warning in row.get("warnings", [])}
        ),
        "result_files": saved_paths,
        "region_filter_summary": region_filter_summary,
    }
