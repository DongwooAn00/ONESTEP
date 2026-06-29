from __future__ import annotations

from types import SimpleNamespace

from app.schemas.od_candidates import CandidateEdge, CandidateNode
from app.services.candidate_route_pipeline import build_candidate_routes
from app.services import candidate_route_pipeline, cost_grid
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
    assert result["region_filter_summary"]["enabled"] is False


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
    )
    assert abs(segment_total - route["route_length_km"]) <= 0.6


def test_cost_model_outputs_eok_units():
    costs = calculate_route_costs(
        new_surface_road_length_km=1.0,
        tunnel_length_km=1.0,
        connector_length_km=0.5,
        land_compensation_cost_eok=10.0,
    )

    assert costs["surface_road_cost"] == 184.0
    assert costs["connector_cost"] == 92.0
    assert "bridge_cost" not in costs
    assert costs["tunnel_cost"] > 0
    assert costs["land_compensation_cost"] == 10.0
    assert costs["cost_assumptions"]["unit"] == "eok_krw"
    assert costs["total_screen_cost"] > costs["total_direct_cost"]


def test_cost_model_uses_each_tunnel_segments_estimated_rock_class():
    common = {
        "new_surface_road_length_km": 0.0,
        "tunnel_length_km": 1.0,
    }
    good = calculate_route_costs(
        **common,
        segment_details=[
            {
                "segment_type": "tunnel",
                "segment_length_km": 1.0,
                "estimated_rock_class": "II",
            }
        ],
    )
    poor = calculate_route_costs(
        **common,
        segment_details=[
            {
                "segment_type": "tunnel",
                "segment_length_km": 1.0,
                "estimated_rock_class": "V",
            }
        ],
    )

    assert good["cost_assumptions"]["f_ground"] == 0.9
    assert poor["cost_assumptions"]["f_ground"] == 2.5
    assert poor["tunnel_cost"] > good["tunnel_cost"] * 2


def test_land_compensation_is_added_after_route_generation(monkeypatch):
    class DummyParcelRepository:
        pass

    monkeypatch.setattr(
        candidate_route_pipeline,
        "_project_new_build_geometry",
        lambda route_geometry: object(),
    )
    monkeypatch.setattr(
        candidate_route_pipeline,
        "estimate_land_compensation",
        lambda route_geom, road_width_m, repository: {
            "total_land_compensation": 100_000_000.0,
            "factor": 1.5,
            "road_width_m": road_width_m,
            "parcel_count": 1,
            "official_count": 1,
            "estimated_count": 0,
            "source_counts": {"official": 1},
            "land_compensation_total": 100_000_000.0,
            "land_compensation_by_land_type": {
                "forest": 100_000_000.0,
                "farmland": 0.0,
                "residential": 0.0,
                "commercial_industrial": 0.0,
                "unknown": 0.0,
            },
            "items": [],
            "warnings": [],
        },
    )

    result = build_candidate_routes(
        _nodes(),
        _edges()[:1],
        route_limit=1,
        dem_provider=FlatDemProvider(),
        apply_optional_layers=False,
        persist_files=False,
        parcel_repository=DummyParcelRepository(),
    )

    cost = result["costs"][0]
    construction_only = calculate_route_costs(
        new_surface_road_length_km=cost["surface_road_length_km"],
        tunnel_length_km=cost["tunnel_length_km"],
        connector_length_km=cost["connector_length_km"],
    )
    assert cost["land_compensation_cost"] == 1.0
    assert result["routes"][0]["land_compensation_total"] == 100_000_000.0
    assert (
        result["routes"][0]["land_compensation_by_land_type"]["forest"]
        == 100_000_000.0
    )
    assert cost["total_direct_cost"] == construction_only["total_direct_cost"] + 1.0
    assert cost["total_screen_cost"] == construction_only["total_screen_cost"] + 1.0


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
            "new_surface_road_length_km": 10,
            "tunnel_length_km": 0,
            "bridge_count": 1,
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
            "new_surface_road_length_km": 10,
            "tunnel_length_km": 0,
            "status": "success",
            "failed_reason": None,
        },
    ]

    ranked = rank_candidate_routes(rows)

    assert ranked[0]["economic_score"] >= ranked[1]["economic_score"]
    assert ranked[0]["bridge_count"] == 1
    assert ranked == sorted(ranked, key=lambda route: route["economic_score"], reverse=True)


def test_result_contract_contains_candidates_and_best_candidate():
    result = build_candidate_routes(
        _nodes(),
        _edges()[:1],
        route_limit=1,
        dem_provider=FlatDemProvider(),
        apply_optional_layers=False,
        persist_files=False,
    )

    assert result["candidates"] == result["routes"]
    assert result["best_candidate"]["route_type"] == "new_direct"
    assert result["route"] == result["best_candidate"]
    assert result["costs"][0]["bridge_length_km"] == 0
    assert "bridge_cost" not in result["costs"][0]
    assert {
        segment["segment_type"] for segment in result["segments"]
    } <= {"existing_road", "connector", "new_surface_road", "tunnel", "bridge"}


def test_existing_baseline_does_not_prevent_new_and_hybrid_candidates(monkeypatch):
    geometry = [
        {"lat": 36.50 + index * 0.007, "lon": 127.00 + index * 0.011}
        for index in range(9)
    ]
    monkeypatch.setattr(
        candidate_route_pipeline,
        "build_road_graph_route",
        lambda *args, **kwargs: SimpleNamespace(
            route_geometry=geometry,
            route_length_km=9.0,
            existing_road_length_km=8.4,
            existing_tunnel_length_km=0.0,
            new_surface_road_length_km=0.0,
            connector_length_km=0.6,
            segment_details=[
                {
                    "route_id": "R001-B",
                    "segment_id": "R001-B-S001",
                    "segment_type": "connector",
                    "segment_length_km": 0.3,
                    "segment_geometry": geometry[:2],
                    "average_slope": 0.0,
                    "max_slope": 0.0,
                },
                {
                    "route_id": "R001-B",
                    "segment_id": "R001-B-S002",
                    "segment_type": "existing_road",
                    "segment_length_km": 8.4,
                    "segment_geometry": geometry[1:-1],
                    "average_slope": 0.0,
                    "max_slope": 0.0,
                },
                {
                    "route_id": "R001-B",
                    "segment_id": "R001-B-S003",
                    "segment_type": "connector",
                    "segment_length_km": 0.3,
                    "segment_geometry": geometry[-2:],
                    "average_slope": 0.0,
                    "max_slope": 0.0,
                },
            ],
            existing_road_access_length_km=8.4,
            existing_road_access_percent=93.3,
            warnings=[],
            road_nodes_before=20,
            road_nodes_after=20,
            road_edges_before=30,
            road_edges_after=30,
        ),
    )
    original_grid_builder = cost_grid.generate_dem_route_grid

    def build_grid_without_database_layers(*args, **kwargs):
        kwargs["apply_optional_layers"] = False
        return original_grid_builder(*args, **kwargs)

    monkeypatch.setattr(
        candidate_route_pipeline,
        "generate_dem_route_grid",
        build_grid_without_database_layers,
    )

    result = build_candidate_routes(
        _nodes(),
        _edges()[:1],
        route_limit=3,
        dem_provider=FlatDemProvider(),
        apply_optional_layers=True,
        persist_files=False,
    )

    route_types = {route["route_type"] for route in result["candidates"]}
    assert "existing_baseline" in route_types
    assert "new_direct" in route_types
    assert "hybrid_new_existing" in route_types
    assert "bypass_improvement" in route_types
    assert all(route["route_type"] != "existing_baseline" for route in result["ranked_routes"])
    assert len(result["ranked_routes"]) == 3


def test_population_fallback_penalizes_urban_cells(monkeypatch):
    radius = cost_grid.config.URBAN_POPULATION_RADIUS_M
    monkeypatch.setattr(
        cost_grid,
        "_population_urban_index",
        lambda: ({(0, 0): [(100.0, 100.0, 40_000)]}, radius),
    )
    urban = cost_grid.CostCell(
        row=0,
        col=0,
        x=0.0,
        y=0.0,
        lon=127.0,
        lat=37.0,
        elevation_m=100.0,
        cost=1.0,
    )
    rural = cost_grid.CostCell(
        row=0,
        col=1,
        x=radius * 4,
        y=radius * 4,
        lon=127.2,
        lat=37.2,
        elevation_m=100.0,
        cost=1.0,
    )
    grid = cost_grid.CostGrid(
        cells=[[urban, rural]],
        cell_size_m=500.0,
        origin_x=0.0,
        origin_y=0.0,
        warnings=[],
    )

    assert cost_grid._apply_population_urban_penalty(grid) is True
    assert urban.builtup_area is True
    assert urban.cost == cost_grid.config.URBAN_POPULATION_HIGH_MULTIPLIER
    assert rural.builtup_area is False
    assert rural.cost == 1.0


def test_geology_layer_populates_cost_cells(monkeypatch):
    monkeypatch.setattr(
        cost_grid,
        "_find_existing_table",
        lambda names: {
            ("geology_litho",): "geology_litho",
            ("geology_faults",): "geology_faults",
            ("geology_boundaries",): "geology_boundaries",
        }.get(tuple(names)),
    )
    monkeypatch.setattr(
        cost_grid,
        "_table_columns",
        lambda table_name: frozenset({"refrock"}) if table_name == "geology_litho" else frozenset(),
    )

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, *args, **kwargs):
            return None

        def fetchall(self):
            return [
                (1, "화강암", 40.0, 120.0),
                (2, "알 수 없는 암종", None, None),
            ]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(cost_grid, "connect", lambda: FakeConnection())

    cells = [
        cost_grid.CostCell(
            row=0,
            col=0,
            x=0.0,
            y=0.0,
            lon=127.0,
            lat=37.0,
            elevation_m=100.0,
            slope_degrees=10.0,
        ),
        cost_grid.CostCell(
            row=0,
            col=1,
            x=500.0,
            y=0.0,
            lon=127.01,
            lat=37.0,
            elevation_m=105.0,
            slope_degrees=5.0,
        ),
    ]
    grid = cost_grid.CostGrid(
        cells=[cells],
        cell_size_m=500.0,
        origin_x=0.0,
        origin_y=0.0,
        warnings=[],
    )

    cost_grid._apply_optional_geology(grid)

    assert cells[0].estimated_rock_class in {"II", "III", "IV", "V"}
    assert cells[0].rock_class == cells[0].estimated_rock_class
    assert cells[0].fault_dist_m == 40.0
    assert cells[0].boundary_dist_m == 120.0
    assert cells[0].rock_ground_factor is not None
    assert cells[1].estimated_rock_class == "III"
    assert "unknown_refrock_default_class_III" in cells[1].risk_reasons
