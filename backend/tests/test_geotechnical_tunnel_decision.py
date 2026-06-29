from app.services.geotechnical_model import TunnelDecisionInput, evaluate_tunnel_decision
from app.services.cost_grid import CostCell
from app.services.rock_class_estimator import estimate_base_class_from_refrock, estimate_rock_class
from app.services.route_segments import classify_route_segments


def test_high_grade_sufficient_cover_good_rock_prefers_tunnel():
    decision = evaluate_tunnel_decision(
        TunnelDecisionInput(
            road_grade_percent=13,
            overburden_m=80,
            estimated_rock_class="II",
            local_relief_m=100,
            segment_length_km=1.0,
        )
    )

    assert decision.final_segment_type == "tunnel"


def test_low_overburden_does_not_confirm_normal_tunnel():
    decision = evaluate_tunnel_decision(
        TunnelDecisionInput(
            road_grade_percent=13,
            overburden_m=10,
            estimated_rock_class="II",
            segment_length_km=1.0,
        )
    )

    assert decision.final_segment_type == "surface_road"
    assert decision.decision_status in {"surface_preferred", "low_cover_tunnel_candidate"}
    assert "low_overburden" in decision.decision_reason


def test_negative_overburden_is_preserved_in_decision_reason():
    decision = evaluate_tunnel_decision(
        TunnelDecisionInput(
            road_grade_percent=13,
            overburden_m=-5,
            estimated_rock_class="II",
            segment_length_km=1.0,
        )
    )

    assert decision.final_segment_type == "surface_road"
    assert decision.decision_reason == "negative_overburden_check_dem_or_profile"
    assert "negative_overburden_check_dem_or_profile" in decision.risk_reasons


def test_very_poor_rock_applies_high_ground_factor_and_avoid_flag():
    decision = evaluate_tunnel_decision(
        TunnelDecisionInput(
            road_grade_percent=13,
            overburden_m=80,
            estimated_rock_class="V",
            segment_length_km=1.0,
        )
    )

    assert decision.decision_status in {"tunnel_candidate", "surface_preferred"}
    assert decision.feasibility_flag == "avoid_or_reroute"
    assert decision.rock_ground_factor >= 2.50


def test_missing_overburden_and_rock_uses_slope_fallback():
    decision = evaluate_tunnel_decision(
        TunnelDecisionInput(
            overburden_m=None,
            estimated_rock_class=None,
            slope_deg=25,
            segment_length_km=1.0,
        )
    )

    assert decision.final_segment_type == "tunnel"
    assert "fallback_slope_based_tunnel_logic" in decision.decision_reason


def test_river_crossing_prioritizes_bridge_over_tunnel():
    decision = evaluate_tunnel_decision(
        TunnelDecisionInput(
            river_crossing=True,
            road_grade_percent=13,
            overburden_m=80,
            estimated_rock_class="II",
            local_relief_m=100,
            segment_length_km=1.0,
        )
    )

    assert decision.final_segment_type == "bridge"
    assert decision.decision_reason == "bridge_due_to_river_crossing"


def test_refrock_substring_granite_maps_to_class_two():
    base_class, risk_reasons = estimate_base_class_from_refrock("흑운모화강암")

    assert base_class == 2
    assert risk_reasons == []


def test_misdecoded_utf8_dbf_refrock_is_recovered_before_matching():
    mojibake = "흑운모화강암".encode("utf-8").decode("latin1")
    base_class, risk_reasons = estimate_base_class_from_refrock(mojibake)

    assert base_class == 2
    assert risk_reasons == []


def test_unknown_refrock_defaults_to_class_three():
    estimate = estimate_rock_class(refrock="알 수 없는 암종", overburden_m=80)

    assert estimate.estimated_rock_class == "III"
    assert "unknown_refrock_default_class_III" in estimate.risk_reasons


def test_grouped_segment_rock_label_matches_worst_ground_factor():
    cells = [
        CostCell(
            row=0,
            col=index,
            x=index * 500.0,
            y=0.0,
            lon=127.0 + index * 0.005,
            lat=37.0,
            elevation_m=100.0,
            slope_degrees=5.0,
            overburden_m=10.0,
            estimated_rock_class=rock_class,
            rock_class=rock_class,
        )
        for index, rock_class in enumerate(("II", "V", "V"))
    ]

    result = classify_route_segments("R-ROCK", cells)
    segment = result["segment_details"][0]

    assert segment.estimated_rock_class == "V"
    assert segment.rock_class == "V"
    assert segment.rock_ground_factor == 2.5
