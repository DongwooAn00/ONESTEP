from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.candidate_routes import CandidateRouteRequest
from app.schemas.od_candidates import CandidateEdge, CandidateNode
from app.services.candidate_route_pipeline import build_candidate_routes
from app.services.region_filter import build_region_context


class FlatDemProvider:
    def elevations(self, points):
        return [120.0 for _ in points]


def _node(node_id: str, latitude: float, longitude: float) -> CandidateNode:
    return CandidateNode(
        node_id=node_id,
        latitude=latitude,
        longitude=longitude,
        cluster_total_flow=100,
        included_od_count=1,
    )


def _edge(
    edge_id: str,
    from_node_id: str,
    to_node_id: str,
    rank: int,
) -> CandidateEdge:
    return CandidateEdge(
        edge_id=edge_id,
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        straight_distance_km=8.0,
        estimated_flow=100,
        rank=rank,
    )


def test_no_regions_and_disabled_filter_preserve_full_scope() -> None:
    context = build_region_context(None, False, 10)

    assert context.enabled is False
    assert context.contains_point(129.0, 35.0) is True


def test_empty_regions_with_enabled_flag_fall_back_to_full_scope() -> None:
    context = build_region_context([], True, 10)

    assert context.enabled is False
    assert context.selected_regions == ()


def test_multiple_regions_accept_points_in_any_buffered_bounds() -> None:
    context = build_region_context(
        ["서울특별시", "경기도"],
        True,
        10,
    )

    assert context.enabled is True
    assert context.contains_point(126.98, 37.56) is True
    assert context.contains_point(127.20, 37.25) is True
    assert context.contains_point(129.07, 35.18) is False


def test_candidate_pipeline_filters_nodes_and_edges_by_region() -> None:
    nodes = [
        _node("N001", 37.50, 126.95),
        _node("N002", 37.55, 127.03),
        _node("N003", 35.15, 129.05),
        _node("N004", 35.20, 129.10),
    ]
    edges = [
        _edge("E001", "N001", "N002", 1),
        _edge("E002", "N003", "N004", 2),
    ]

    result = build_candidate_routes(
        nodes,
        edges,
        route_limit=2,
        dem_provider=FlatDemProvider(),
        apply_optional_layers=False,
        persist_files=False,
        selected_regions=["서울특별시", "경기도"],
        use_region_filter=True,
        region_buffer_km=10,
    )

    summary = result["region_filter_summary"]
    assert summary["enabled"] is True
    assert summary["candidate_nodes_before"] == 4
    assert summary["candidate_nodes_after"] == 2
    assert summary["candidate_edges_before"] == 2
    assert summary["candidate_edges_after"] == 1
    assert len(result["routes"]) == 1


def test_gangwon_region_runs_dem_candidate_pipeline() -> None:
    nodes = [
        _node("N001", 37.75, 128.80),
        _node("N002", 37.80, 128.90),
    ]

    result = build_candidate_routes(
        nodes,
        [_edge("E001", "N001", "N002", 1)],
        route_limit=1,
        dem_provider=FlatDemProvider(),
        apply_optional_layers=False,
        persist_files=False,
        selected_regions=["강원특별자치도"],
        use_region_filter=True,
    )

    assert result["routes"][0]["status"] == "success"
    assert result["region_filter_summary"]["cost_grid_cells"] > 0


def test_unknown_region_has_clear_validation_error() -> None:
    with pytest.raises(ValidationError, match="지원하지 않는 행정구역"):
        CandidateRouteRequest(
            nodes=[
                _node("N001", 37.5, 127.0),
                _node("N002", 37.6, 127.1),
            ],
            edges=[_edge("E001", "N001", "N002", 1)],
            selected_regions=["없는 지역"],
            use_region_filter=True,
        )
