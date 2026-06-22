from __future__ import annotations

from app.schemas.od_candidates import CandidateEdge, CandidateNode
from app.services.candidate_route_pipeline import build_candidate_routes
from app.services.cost_model import calculate_route_costs
from app.services.route_economics import rank_candidate_routes


class FlatDemProvider:
    def elevations(self, points):
        return [120.0 + (point.x % 1000) * 0.002 for point in points]


class MissingDemProvider:
    def elevations(self, points):
        return [None for _ in points]


def _nodes():
    return [
        CandidateNode(node_id="N001", latitude=36.50, longitude=127.00, cluster_total_flow=1000, included_od_count=4),
        CandidateNode(node_id="N002", latitude=36.55, longitude=127.08, cluster_total_flow=900, included_od_count=3),
        CandidateNode(node_id="N003", latitude=36.60, longitude=127.16, cluster_total_flow=800, included_od_count=3),
        CandidateNode(node_id="N004", latitude=36.65, longitude=127.24, cluster_total_flow=700, included_od_count=2),
    ]


def _edges():
    return [
        CandidateEdge(
            edge_id="E001",
            from_node_id="N001",
            to_node_id="N002",
            straight_distance_km=9.0,
            estimated_flow=3000,
            rank=1,
        ),
        CandidateEdge(
            edge_id="E002",
            from_node_id="N002",
            to_node_id="N003",
            straight_distance_km=8.8,
            estimated_flow=2200,
            rank=2,
        ),
        CandidateEdge(
            edge_id="E003",
            from_node_id="N003",
            to_node_id="N004",
            straight_distance_km=8.5,
            estimated_flow=1600,
            rank=3,
        ),
    ]


def test_candidate_routes_run_for_three_sample_edges():
    result = build_candidate_routes(
        _nodes(),
        _edges(),
        route_limit=3,
        dem_provider=FlatDemProvider(),
        apply_optional_layers=False,
        persist_files=False,
    )

    assert len(result["routes"]) == 3
    assert all(route["status"] == "success" for route in result["routes"])
    assert result["segments"]
    assert result["costs"]


def test_candidate_route_marks_dem_missing_as_failed():
    result = build_candidate_routes(
        _nodes(),
        _edges()[:1],
        route_limit=1,
        dem_provider=MissingDemProvider(),
        apply_optional_layers=False,
        persist_files=False,
    )

    assert result["routes"][0]["status"] == "failed"
    assert result["routes"][0]["failed_reason"]


def test_segment_lengths_are_close_to_route_length():
    result = build_candidate_routes(
        _nodes(),
        _edges()[:1],
        route_limit=1,
        dem_provider=FlatDemProvider(),
        apply_optional_layers=False,
        persist_files=False,
    )

    route = result["routes"][0]
    cost = result["costs"][0]
    segment_total = (
        cost["surface_road_length_km"]
        + cost["tunnel_length_km"]
        + cost["bridge_length_km"]
    )
    assert abs(segment_total - route["route_length_km"]) <= 0.6


def test_cost_model_outputs_eok_units():
    costs = calculate_route_costs(surface_road_length_km=1.0, tunnel_length_km=1.0, bridge_length_km=1.0)

    assert costs["surface_road_cost"] == 184.0
    assert costs["bridge_cost"] == 601.0
    assert costs["tunnel_cost"] > 0
    assert costs["cost_assumptions"]["unit"] == "eok_krw"
    assert costs["total_screen_cost"] > costs["total_direct_cost"]


def test_ranked_candidate_routes_sort_by_economic_score():
    rows = [
        {
            "route_id": "R001",
            "from_node_id": "N001",
            "to_node_id": "N002",
            "estimated_flow": 1000,
            "distance_saving_km": 4,
            "total_screen_cost": 100,
            "route_length_km": 10,
            "surface_road_length_km": 10,
            "tunnel_length_km": 0,
            "bridge_length_km": 0,
            "status": "success",
            "failed_reason": None,
        },
        {
            "route_id": "R002",
            "from_node_id": "N002",
            "to_node_id": "N003",
            "estimated_flow": 1000,
            "distance_saving_km": 1,
            "total_screen_cost": 500,
            "route_length_km": 10,
            "surface_road_length_km": 10,
            "tunnel_length_km": 0,
            "bridge_length_km": 0,
            "status": "success",
            "failed_reason": None,
        },
    ]

    ranked = rank_candidate_routes(rows)

    assert ranked[0]["economic_score"] >= ranked[1]["economic_score"]
    assert ranked == sorted(ranked, key=lambda route: route["economic_score"], reverse=True)
