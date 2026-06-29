import pytest

from app.services.cost_grid import CostCell
from app.services.cost_model import calculate_diversion_rate, evaluate_candidate_against_baseline
from app.services.route_segments import classify_route_segments


def _cell(index: int, *, elevation: float = 100.0, slope: float = 2.0, road_distance: float | None = None):
    return CostCell(
        row=0,
        col=index,
        x=index * 500.0,
        y=0.0,
        lon=127.0 + index * 0.005,
        lat=37.0,
        elevation_m=elevation,
        slope_degrees=slope,
        road_rank="road" if road_distance is not None else None,
        road_distance_m=road_distance,
    )


def test_dem_path_within_50m_of_existing_road_is_reclassified_as_existing():
    cells = [_cell(index, road_distance=40.0) for index in range(4)]

    result = classify_route_segments("R001-D", cells)

    assert result["existing_road_length_km"] == 1.5
    assert result["new_surface_road_length_km"] == 0.0
    assert {segment.segment_type for segment in result["segment_details"]} == {"existing_road"}


def test_existing_road_requires_both_cells_within_50m():
    one_missing = [_cell(0, road_distance=20.0), _cell(1, road_distance=None)]
    too_far = [_cell(0, road_distance=20.0), _cell(1, road_distance=120.0)]

    missing_result = classify_route_segments("R-MISSING", one_missing)
    far_result = classify_route_segments("R-FAR", too_far)

    assert missing_result["existing_road_length_km"] == 0.0
    assert far_result["existing_road_length_km"] == 0.0
    assert missing_result["new_surface_road_length_km"] == 0.5
    assert far_result["new_surface_road_length_km"] == 0.5


def test_short_steep_piece_does_not_survive_as_tunnel():
    cells = [
        _cell(0, elevation=100.0, slope=30.0),
        _cell(1, elevation=180.0, slope=30.0),
    ]

    result = classify_route_segments("R001-D", cells)

    assert result["tunnel_length_km"] == 0.0
    assert result["new_surface_road_length_km"] == 0.5


def test_less_than_five_percent_improvement_is_flagged_and_baseline_remains_default():
    baseline = {
        "route_type": "existing_baseline",
        "route_length_km": 10.0,
        "existing_road_length_km": 10.0,
        "total_screen_cost": 0.0,
        "estimated_flow": 1000,
    }
    candidate = {
        "route_type": "hybrid_new_existing",
        "route_length_km": 9.7,
        "existing_road_length_km": 9.0,
        "new_surface_road_length_km": 0.7,
        "total_screen_cost": 500.0,
        "estimated_flow": 1000,
    }

    evaluate_candidate_against_baseline(baseline, baseline)
    evaluate_candidate_against_baseline(candidate, baseline)

    assert candidate["distance_saving_ratio"] == 0.03
    assert candidate["is_meaningful_improvement"] is False
    assert baseline["candidate_score"] > candidate["candidate_score"]
    assert candidate["existing_road_ratio"] > candidate["new_construction_ratio"]


def test_diversion_rate_uses_weighted_savings_threshold_and_cap():
    saving_score, diversion_rate = calculate_diversion_rate(0.04, 0.04)
    assert saving_score == 0.04
    assert diversion_rate == 0.0

    saving_score, diversion_rate = calculate_diversion_rate(0.10, 0.10)
    assert saving_score == 0.10
    assert diversion_rate == pytest.approx(0.30)

    saving_score, diversion_rate = calculate_diversion_rate(0.50, 0.50)
    assert saving_score == 0.50
    assert diversion_rate == 0.70


def test_benefits_and_demand_use_diverted_flow_not_total_potential_flow():
    baseline = {
        "route_type": "existing_baseline",
        "route_length_km": 10.0,
        "existing_road_length_km": 10.0,
        "total_screen_cost": 0.0,
        "estimated_flow": 1000,
    }
    candidate = {
        "route_type": "hybrid_new_existing",
        "route_length_km": 9.0,
        "existing_road_length_km": 8.0,
        "new_surface_road_length_km": 1.0,
        "total_screen_cost": 100.0,
        "estimated_flow": 1000,
    }

    evaluate_candidate_against_baseline(candidate, baseline)

    assert candidate["diverted_flow"] == candidate["estimated_flow"] * candidate["diversion_rate"]
    assert candidate["annual_benefit"] < candidate["annual_benefit_before_diversion"]
    assert candidate["annual_time_benefit"] + candidate["annual_distance_benefit"] == pytest.approx(
        candidate["annual_benefit"],
        abs=0.001,
    )
    assert candidate["bc_ratio"] == candidate["benefit_cost_ratio"]
