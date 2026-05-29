from app.schemas.economic import AnalysisRequest, AnalysisResult


def _present_value_factor(year: int, discount_rate: float) -> float:
    return 1 / ((1 + discount_rate) ** year)


def analyze_project(payload: AnalysisRequest) -> AnalysisResult:
    discount_rate = payload.discount_rate_percent / 100

    present_benefit = 0.0
    present_operation_cost = 0.0

    for year in range(1, payload.operation_years + 1):
        factor = _present_value_factor(year, discount_rate)
        present_benefit += payload.annual_benefit_billion_krw * factor
        present_operation_cost += payload.annual_operation_cost_billion_krw * factor

    present_cost = payload.construction_cost_billion_krw + present_operation_cost
    net_present_value = present_benefit - present_cost
    benefit_cost_ratio = present_benefit / present_cost if present_cost > 0 else 0

    return AnalysisResult(
        benefit_cost_ratio=round(benefit_cost_ratio, 3),
        net_present_value_billion_krw=round(net_present_value, 3),
        total_present_benefit_billion_krw=round(present_benefit, 3),
        total_present_cost_billion_krw=round(present_cost, 3),
    )
