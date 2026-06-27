from app.services.geotechnical_model import TunnelDecisionInput, evaluate_tunnel_decision
from app.services.rock_class_estimator import estimate_base_class_from_refrock, estimate_rock_class


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


def test_river_crossing_overrides_tunnel():
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
    assert "bridge_due_to_river_crossing" in decision.decision_reason


def test_refrock_substring_granite_maps_to_class_two():
    base_class, risk_reasons = estimate_base_class_from_refrock("흑운모화강암")

    assert base_class == 2
    assert risk_reasons == []


def test_unknown_refrock_defaults_to_class_three():
    estimate = estimate_rock_class(refrock="알 수 없는 암종", overburden_m=80)

    assert estimate.estimated_rock_class == "III"
    assert "unknown_refrock_default_class_III" in estimate.risk_reasons
