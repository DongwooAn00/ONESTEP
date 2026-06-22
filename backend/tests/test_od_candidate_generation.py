from pathlib import Path

import pytest

from app.services.od_candidate_generation import build_od_candidates


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


def test_build_od_candidates_reports_missing_coordinates(tmp_path):
    csv_path = tmp_path / "od_without_coordinates.csv"
    csv_path.write_text(
        "origin_admin_dong_code,destination_admin_dong_code,passenger_car,bus,total\n"
        "111,222,10,5,15\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Origin/destination coordinate columns"):
        build_od_candidates(csv_path, "od_without_coordinates.csv", top_node_limit=30, persist_files=False)
