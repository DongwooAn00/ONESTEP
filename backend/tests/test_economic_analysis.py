from app.schemas.economic import AnalysisRequest
from app.services.economic_analysis import analyze_project


def test_analyze_project_returns_core_indicators():
    payload = AnalysisRequest(
        tunnel_length_km=3.2,
        construction_cost_billion_krw=4200,
        annual_benefit_billion_krw=300,
        annual_operation_cost_billion_krw=25,
        operation_years=30,
        discount_rate_percent=4.5,
    )

    result = analyze_project(payload)

    assert result.benefit_cost_ratio > 0
    assert result.total_present_benefit_billion_krw > 0
    assert result.total_present_cost_billion_krw > 4200
