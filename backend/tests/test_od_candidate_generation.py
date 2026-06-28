from io import StringIO
from pathlib import Path

import pytest

from app.services.od_candidate_generation import build_od_candidates, build_od_candidates_with_supplemental


ROOT = Path(__file__).resolve().parents[2]


def test_build_od_candidates_from_coordinate_sample():
    result = build_od_candidates(
        ROOT / "backend" / "tests" / "fixtures" / "od_sample_with_coords.csv",
        "od_sample_with_coords.csv",
        top_node_limit=100,
        persist_files=False,
    )

    assert result.nodes
    assert result.edges
    assert result.stats.selected_top_percent is None
    assert result.stats.selected_top_rows == 12
    assert result.stats.coordinate_excluded_rows == 0
    assert result.stats.non_positive_flow_excluded_rows == 0
    assert result.stats.iterative_cluster_counts == [10, 20, 30, 50]
    assert result.stats.pre_merge_node_count >= result.stats.merged_node_count >= len(result.nodes)
    assert result.edges == sorted(result.edges, key=lambda edge: edge.estimated_flow, reverse=True)
    assert all(5 <= edge.straight_distance_km <= 100 for edge in result.edges)
    assert result.nodes[0].x is not None
    assert result.nodes[0].y is not None
    assert result.nodes[0].source_k_values
    assert result.nodes[0].merged_count >= 1
    assert result.edges[0].od_count >= 1
    assert result.edges[0].source == "all_od_weighted_kmeans"


def test_build_od_candidates_can_filter_top_percent():
    result = build_od_candidates(
        ROOT / "backend" / "tests" / "fixtures" / "od_sample_with_coords.csv",
        "od_sample_with_coords.csv",
        flow_filter_percent=10,
        low_impact_prune_percent=None,
        top_node_limit=30,
        persist_files=False,
    )

    assert result.stats.selected_top_percent == 10
    assert result.stats.selected_top_rows == 2
    assert result.nodes
    assert result.edges


def test_build_od_candidates_can_merge_supplemental_scenario_od():
    supplemental = StringIO(
        "origin_latitude,origin_longitude,destination_latitude,destination_longitude,passenger_car,freight\n"
        "36.30,127.30,36.80,127.80,10000,2000\n"
        "36.35,127.35,36.85,127.85,12000,3000\n"
    )

    result = build_od_candidates_with_supplemental(
        ROOT / "backend" / "tests" / "fixtures" / "od_sample_with_coords.csv",
        supplemental,
        "od_sample_with_coords.csv + scenario_od.csv",
        low_impact_prune_percent=None,
        top_node_limit=100,
        persist_files=False,
    )

    assert result.nodes
    assert result.edges
    assert result.stats.total_od_rows == 14
    assert result.stats.selected_top_rows == 14
    assert any("2 supplemental rows" in warning for warning in result.stats.warnings)


def test_build_od_candidates_can_use_only_supplemental_scenario_od():
    supplemental = StringIO(
        "origin_latitude,origin_longitude,destination_latitude,destination_longitude,passenger_car,freight\n"
        "36.30,127.30,36.80,127.80,10000,2000\n"
        "36.35,127.35,36.85,127.85,12000,3000\n"
    )

    result = build_od_candidates_with_supplemental(
        None,
        supplemental,
        "scenario_od.csv",
        include_base_od=False,
        low_impact_prune_percent=None,
        top_node_limit=100,
        persist_files=False,
    )

    assert result.nodes
    assert result.edges
    assert result.stats.total_od_rows == 2
    assert result.stats.selected_top_rows == 2


def test_build_od_candidates_reports_missing_coordinates(tmp_path):
    csv_path = tmp_path / "od_without_coordinates.csv"
    csv_path.write_text(
        "origin_admin_dong_code,destination_admin_dong_code,passenger_car,bus,total\n"
        "111,222,10,5,15\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Origin/destination coordinate columns"):
        build_od_candidates(csv_path, "od_without_coordinates.csv", top_node_limit=30, persist_files=False)


def test_build_od_candidates_filters_rows_to_selected_regions():
    source = StringIO(
        "origin_latitude,origin_longitude,destination_latitude,destination_longitude,total_flow\n"
        "37.50,126.90,37.58,127.05,100\n"
        "37.52,126.92,37.60,127.08,90\n"
        "37.48,126.88,37.56,127.02,80\n"
        "37.54,126.95,37.62,127.10,70\n"
        "35.10,129.00,35.25,129.18,1000\n"
        "35.12,129.02,35.27,129.20,900\n"
    )

    result = build_od_candidates(
        source,
        "mixed_regions.csv",
        low_impact_prune_percent=None,
        top_node_limit=100,
        persist_files=False,
        selected_regions=["서울특별시", "경기도"],
        use_region_filter=True,
        region_buffer_km=10,
    )

    summary = result.stats.region_filter_summary
    assert summary["enabled"] is True
    assert summary["od_rows_before"] == 6
    assert summary["od_rows_after"] == 4
    assert result.stats.region_excluded_rows == 2
    assert all(node.latitude > 37 for node in result.nodes)


def test_empty_selected_regions_keep_existing_full_calculation():
    result = build_od_candidates(
        ROOT / "backend" / "tests" / "fixtures" / "od_sample_with_coords.csv",
        "od_sample_with_coords.csv",
        persist_files=False,
        selected_regions=[],
        use_region_filter=True,
    )

    assert result.stats.region_filter_summary["enabled"] is False
    assert result.stats.region_excluded_rows == 0
