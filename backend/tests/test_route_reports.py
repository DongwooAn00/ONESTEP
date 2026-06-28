from __future__ import annotations

from app.api.routes import create_candidate_route_reports
from app.schemas.route_reports import CandidateRouteReportsRequest
from app.services.route_report_service import generate_candidate_route_reports


def _route(route_id: str = "R001-D", tunnel_length: float = 2.0) -> dict:
    return {
        "route_id": route_id,
        "route_type": "new_direct",
        "from_node_id": "N001",
        "to_node_id": "N002",
        "route_length_km": 12.0,
        "existing_road_length_km": 1.0,
        "connector_length_km": 0.5,
        "new_surface_road_length_km": 8.5 if tunnel_length else 10.5,
        "tunnel_length_km": tunnel_length,
        "construction_cost": 3200.0,
        "annual_benefit": 280.0,
        "total_benefit": 4300.0,
        "benefit_cost_ratio": 1.34,
        "net_benefit": 1100.0,
        "candidate_score": 82.5,
        "distance_saving_km": 3.2,
        "time_saving_minutes": 7.5,
        "explanation": ["DEM 기반 직접 신규 노선입니다."],
    }


def _cost(route_id: str = "R001-D") -> dict:
    return {
        "route_id": route_id,
        "new_road_screen_cost": 1800.0,
        "connector_screen_cost": 100.0,
        "tunnel_screen_cost": 1200.0,
        "land_compensation_cost": 100.0,
        "total_screen_cost": 3200.0,
    }


def _segments(route_id: str = "R001-D", include_bridge: bool = False) -> list[dict]:
    rows = [
        {
            "route_id": route_id,
            "segment_id": f"{route_id}-S001",
            "segment_type": "new_surface_road",
            "segment_length_km": 10.0,
            "average_slope": 4.0,
            "max_slope": 11.0,
        },
        {
            "route_id": route_id,
            "segment_id": f"{route_id}-S002",
            "segment_type": "tunnel",
            "segment_length_km": 2.0,
            "average_slope": 14.0,
            "max_slope": 26.0,
        },
    ]
    if include_bridge:
        rows.append(
            {
                "route_id": route_id,
                "segment_id": f"{route_id}-S003",
                "segment_type": "bridge",
                "segment_length_km": 0.4,
                "average_slope": 0.0,
                "max_slope": 0.0,
            }
        )
    return rows


def test_template_report_is_generated_from_candidate_values():
    result = generate_candidate_route_reports(
        CandidateRouteReportsRequest(
            routes=[_route()],
            segments=_segments(),
            costs=[_cost()],
        )
    )

    report = result.reports[0]
    assert result.report_count == 1
    assert report.route_id == "R001-D"
    assert "12.00km" in report.summary
    assert "B/C" in report.summary
    assert report.metrics.tunnel_length_km == 2.0
    assert report.metrics.total_project_cost > report.metrics.construction_cost
    assert "## 6. 종합 검토 의견" in report.markdown


def test_report_without_tunnel_is_still_generated():
    route = _route(tunnel_length=0.0)
    result = generate_candidate_route_reports(
        CandidateRouteReportsRequest(routes=[route], costs=[_cost()])
    )

    report = result.reports[0]
    assert report.metrics.tunnel_length_km == 0.0
    assert "터널 구간이 확인되지 않았습니다" in report.route_overview


def test_report_handles_missing_cost_and_benefit_values():
    route = _route()
    route.update(
        {
            "construction_cost": None,
            "annual_benefit": None,
            "total_benefit": None,
            "benefit_cost_ratio": None,
            "net_benefit": None,
        }
    )
    result = generate_candidate_route_reports(
        CandidateRouteReportsRequest(routes=[route], costs=[{"route_id": "R001-D"}])
    )

    report = result.reports[0]
    assert report.metrics.benefit_cost_ratio is None
    assert "현재 산정 불가" in report.benefit_analysis
    assert "경제성 결론을 유보" in report.final_opinion


def test_unsupported_bridge_segment_is_ignored_with_warning():
    result = generate_candidate_route_reports(
        CandidateRouteReportsRequest(
            routes=[_route()],
            segments=_segments(include_bridge=True),
            costs=[_cost()],
        )
    )

    report = result.reports[0]
    assert any("교량 segment 1건" in item for item in report.limitations)
    assert report.metrics.road_length_km == 10.0


def test_multiple_candidate_reports_can_be_generated_and_filtered():
    result = generate_candidate_route_reports(
        CandidateRouteReportsRequest(
            routes=[_route("R001-D"), _route("R002-H")],
            costs=[_cost("R001-D"), _cost("R002-H")],
        )
    )
    filtered = generate_candidate_route_reports(
        CandidateRouteReportsRequest(
            routes=[_route("R001-D"), _route("R002-H")],
            costs=[_cost("R001-D"), _cost("R002-H")],
            route_ids=["R002-H"],
        )
    )

    assert result.report_count == 2
    assert filtered.report_count == 1
    assert filtered.reports[0].route_id == "R002-H"


def test_candidate_route_reports_api_returns_report():
    response = create_candidate_route_reports(
        CandidateRouteReportsRequest(
            routes=[_route()],
            segments=_segments(),
            costs=[_cost()],
            ranked_routes=[],
            route_ids=["R001-D"],
        )
    )

    assert response.report_count == 1
    assert response.reports[0].generator == "template"
