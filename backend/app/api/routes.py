from fastapi import APIRouter

from app.schemas.economic import AnalysisRequest, AnalysisResult
from app.schemas.route_cost import RouteCostRequest, RouteCostResult
from app.services.economic_analysis import analyze_project
from app.services.route_cost import analyze_route_cost

router = APIRouter()


@router.post("/analysis", response_model=AnalysisResult)
def create_analysis(payload: AnalysisRequest) -> AnalysisResult:
    return analyze_project(payload)


@router.post("/route-cost", response_model=RouteCostResult)
def create_route_cost(payload: RouteCostRequest) -> RouteCostResult:
    return analyze_route_cost(payload)
