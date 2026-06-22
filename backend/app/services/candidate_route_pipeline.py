from __future__ import annotations

import json
import math
from pathlib import Path

from app.schemas.od_candidates import CandidateEdge, CandidateNode
from app.services import route_mvp_config as config
from app.services.cost_grid import DemProvider, build_cost_grid
from app.services.cost_model import calculate_route_costs
from app.services.pathfinding import find_least_cost_path
from app.services.route_economics import calculate_distance_saving_km, rank_candidate_routes
from app.services.route_segments import RouteSegmentDetail, classify_route_segments

ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = ROOT / "data" / "processed"


def _route_length_km(cells) -> float:
    return round(
        sum(math.hypot(end.x - start.x, end.y - start.y) for start, end in zip(cells, cells[1:])) / 1000.0,
        3,
    )


def _route_geometry(cells) -> list[dict[str, float]]:
    return [{"lat": cell.lat, "lon": cell.lon} for cell in cells]


def _segment_rows(route_id: str, details: list[RouteSegmentDetail]) -> list[dict]:
    return [
        {
            "route_id": route_id,
            "segment_id": item.segment_id,
            "segment_type": item.segment_type,
            "segment_length_km": item.segment_length_km,
            "segment_geometry": item.segment_geometry,
            "average_slope": item.average_slope,
            "max_slope": item.max_slope,
        }
        for item in details
    ]


def _failed_route(edge: CandidateEdge, reason: str) -> dict:
    return {
        "route_id": f"R{edge.rank:03d}",
        "from_node_id": edge.from_node_id,
        "to_node_id": edge.to_node_id,
        "estimated_flow": edge.estimated_flow,
        "straight_distance_km": edge.straight_distance_km,
        "route_geometry": [],
        "route_length_km": 0.0,
        "total_grid_cost": 0.0,
        "average_slope": 0.0,
        "max_slope": 0.0,
        "river_crossing_count": 0,
        "surface_road_length_km": 0.0,
        "tunnel_length_km": 0.0,
        "bridge_length_km": 0.0,
        "tunnel_segment_count": 0,
        "bridge_segment_count": 0,
        "status": "failed",
        "failed_reason": reason,
        "distance_saving_km": 0.0,
        "surface_road_cost": 0.0,
        "tunnel_cost": 0.0,
        "bridge_cost": 0.0,
        "total_direct_cost": 0.0,
        "surface_road_screen_cost": 0.0,
        "tunnel_screen_cost": 0.0,
        "bridge_screen_cost": 0.0,
        "total_screen_cost": 0.0,
        "cost_assumptions": {},
        "segment_details": [],
        "warnings": [],
    }


def evaluate_candidate_edge(
    edge: CandidateEdge,
    nodes: list[CandidateNode],
    *,
    dem_provider: DemProvider | None = None,
    apply_optional_layers: bool = True,
    buffer_multiplier: float = 0.3,
) -> dict:
    route_id = f"R{edge.rank:03d}"
    try:
        grid, start, end = build_cost_grid(
            edge,
            nodes,
            buffer_multiplier=buffer_multiplier,
            dem_provider=dem_provider,
            apply_optional_layers=apply_optional_layers,
        )
        try:
            path = find_least_cost_path(grid, start, end)
        except ValueError:
            grid, start, end = build_cost_grid(
                edge,
                nodes,
                buffer_multiplier=buffer_multiplier * 2,
                dem_provider=dem_provider,
                apply_optional_layers=apply_optional_layers,
            )
            path = find_least_cost_path(grid, start, end)

        route_length_km = _route_length_km(path.cells)
        segment_summary = classify_route_segments(route_id, path.cells)
        details: list[RouteSegmentDetail] = segment_summary["segment_details"]
        average_slope = (
            sum(cell.slope_degrees for cell in path.cells) / len(path.cells) if path.cells else 0.0
        )
        max_slope = max((cell.slope_degrees for cell in path.cells), default=0.0)
        river_crossing_count = segment_summary["bridge_segment_count"]
        costs = calculate_route_costs(
            segment_summary["surface_road_length_km"],
            segment_summary["tunnel_length_km"],
            segment_summary["bridge_length_km"],
        )
        distance_saving_km = calculate_distance_saving_km(
            straight_distance_km=edge.straight_distance_km,
            new_route_length_km=route_length_km,
        )

        return {
            "route_id": route_id,
            "from_node_id": edge.from_node_id,
            "to_node_id": edge.to_node_id,
            "estimated_flow": edge.estimated_flow,
            "straight_distance_km": edge.straight_distance_km,
            "route_geometry": _route_geometry(path.cells),
            "route_length_km": route_length_km,
            "total_grid_cost": path.total_grid_cost,
            "average_slope": round(average_slope, 2),
            "max_slope": round(max_slope, 2),
            "river_crossing_count": river_crossing_count,
            "surface_road_length_km": segment_summary["surface_road_length_km"],
            "tunnel_length_km": segment_summary["tunnel_length_km"],
            "bridge_length_km": segment_summary["bridge_length_km"],
            "tunnel_segment_count": segment_summary["tunnel_segment_count"],
            "bridge_segment_count": segment_summary["bridge_segment_count"],
            "status": "success",
            "failed_reason": None,
            "distance_saving_km": distance_saving_km,
            "segment_details": _segment_rows(route_id, details),
            "warnings": grid.warnings,
            **costs,
        }
    except Exception as error:
        return _failed_route(edge, str(error))


def _write_json(filename: str, payload) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _build_output_files(rows: list[dict], ranked_rows: list[dict]) -> dict[str, list[dict]]:
    candidate_routes = [
        {
            "route_id": row["route_id"],
            "from_node_id": row["from_node_id"],
            "to_node_id": row["to_node_id"],
            "route_geometry": row["route_geometry"],
            "route_length_km": row["route_length_km"],
            "status": row["status"],
            "failed_reason": row["failed_reason"],
        }
        for row in rows
    ]
    candidate_route_segments = [
        segment
        for row in rows
        for segment in row["segment_details"]
    ]
    candidate_route_costs = [
        {
            "route_id": row["route_id"],
            "surface_road_length_km": row["surface_road_length_km"],
            "tunnel_length_km": row["tunnel_length_km"],
            "bridge_length_km": row["bridge_length_km"],
            "surface_road_cost": row["surface_road_cost"],
            "tunnel_cost": row["tunnel_cost"],
            "bridge_cost": row["bridge_cost"],
            "total_direct_cost": row["total_direct_cost"],
            "surface_road_screen_cost": row["surface_road_screen_cost"],
            "tunnel_screen_cost": row["tunnel_screen_cost"],
            "bridge_screen_cost": row["bridge_screen_cost"],
            "total_screen_cost": row["total_screen_cost"],
            "cost_assumptions": row["cost_assumptions"],
        }
        for row in rows
    ]
    return {
        "candidate_routes.json": candidate_routes,
        "candidate_route_segments.json": candidate_route_segments,
        "candidate_route_costs.json": candidate_route_costs,
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
) -> dict:
    active_limit = min(max(route_limit, config.MIN_ROUTE_LIMIT), config.MAX_ROUTE_LIMIT)
    selected_edges = sorted(edges, key=lambda edge: edge.estimated_flow, reverse=True)[:active_limit]
    rows = [
        evaluate_candidate_edge(
            edge,
            nodes,
            dem_provider=dem_provider,
            apply_optional_layers=apply_optional_layers,
        )
        for edge in selected_edges
    ]
    ranked_rows = rank_candidate_routes(rows)
    output_files = _build_output_files(rows, ranked_rows)
    saved_paths = {
        filename: _write_json(filename, payload)
        for filename, payload in output_files.items()
    } if persist_files else {}

    return {
        "routes": output_files["candidate_routes.json"],
        "segments": output_files["candidate_route_segments.json"],
        "costs": output_files["candidate_route_costs.json"],
        "ranked_routes": ranked_rows,
        "warnings": sorted({warning for row in rows for warning in row.get("warnings", [])}),
        "result_files": saved_paths,
    }
