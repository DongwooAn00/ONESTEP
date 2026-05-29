from fastapi import APIRouter

from app.schemas.economic import AnalysisRequest, AnalysisResult
from app.schemas.route_generation import RouteGenerationRequest, RouteGenerationResult
from app.schemas.route_cost import EvaluateRouteRequest, EvaluateRouteResult, RouteCostRequest, RouteCostResult
from app.services.economic_analysis import analyze_project
from app.services.route_cost import analyze_route_cost, evaluate_route
from app.services.route_generation import generate_route_candidates

router = APIRouter()


@router.post("/analysis", response_model=AnalysisResult)
def create_analysis(payload: AnalysisRequest) -> AnalysisResult:
    return analyze_project(payload)


@router.post("/route-cost", response_model=RouteCostResult)
def create_route_cost(payload: RouteCostRequest) -> RouteCostResult:
    return analyze_route_cost(payload)


@router.post("/evaluate-route", response_model=EvaluateRouteResult)
def create_route_evaluation(payload: EvaluateRouteRequest) -> EvaluateRouteResult:
    return evaluate_route(payload)


@router.post("/generate-route", response_model=RouteGenerationResult)
def create_route_generation(payload: RouteGenerationRequest) -> RouteGenerationResult:
    return generate_route_candidates(payload)
