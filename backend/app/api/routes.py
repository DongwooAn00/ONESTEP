from io import StringIO

from fastapi import APIRouter, File, Form, HTTPException

from app.schemas.candidate_routes import CandidateRouteRequest, CandidateRouteResult
from app.schemas.economic import AnalysisRequest, AnalysisResult
from app.schemas.od_candidates import ODCandidateResult
from app.schemas.route_cost import EvaluateRouteRequest, EvaluateRouteResult, RouteCostRequest, RouteCostResult
from app.schemas.route_generation import RouteGenerationRequest, RouteGenerationResult
from app.services.candidate_route_pipeline import build_candidate_routes
from app.services.economic_analysis import analyze_project
from app.services.od_candidate_generation import build_od_candidates
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


@router.post("/candidate-routes", response_model=CandidateRouteResult)
def create_candidate_routes(payload: CandidateRouteRequest) -> CandidateRouteResult:
    return build_candidate_routes(payload.nodes, payload.edges, route_limit=payload.route_limit)


@router.post("/od-candidates", response_model=ODCandidateResult)
async def create_od_candidates(
    top_node_limit: int = Form(default=100),
    flow_filter_percent: int | None = Form(default=None),
    low_impact_prune_percent: int | None = Form(default=20),
    edge_limit: int = Form(default=50),
    min_estimated_flow: float | None = Form(default=None),
    sample_size: int | None = Form(default=None),
    file: bytes | None = File(default=None),
) -> ODCandidateResult:
    if top_node_limit < 1 or top_node_limit > 100:
        raise HTTPException(status_code=400, detail="top_node_limit must be between 1 and 100.")
    if flow_filter_percent not in (None, 5, 10, 20):
        raise HTTPException(status_code=400, detail="flow_filter_percent must be empty, 5, 10, or 20.")
    if low_impact_prune_percent is not None and not 0 <= low_impact_prune_percent <= 30:
        raise HTTPException(status_code=400, detail="low_impact_prune_percent must be empty or between 0 and 30.")
    if edge_limit < 1 or edge_limit > 100:
        raise HTTPException(status_code=400, detail="edge_limit must be between 1 and 100.")
    if sample_size is not None and sample_size < 1:
        raise HTTPException(status_code=400, detail="sample_size must be empty or greater than 0.")

    try:
        if file is None:
            return build_od_candidates(
                None,
                "synthetic_admin_dong_od_by_mode.csv",
                flow_filter_percent=flow_filter_percent,
                top_node_limit=top_node_limit,
                low_impact_prune_percent=low_impact_prune_percent,
                edge_limit=edge_limit,
                min_estimated_flow=min_estimated_flow,
                sample_size=sample_size,
            )

        uploaded_csv = StringIO(file.decode("utf-8-sig"))
        return build_od_candidates(
            uploaded_csv,
            "uploaded_od.csv",
            flow_filter_percent=flow_filter_percent,
            top_node_limit=top_node_limit,
            low_impact_prune_percent=low_impact_prune_percent,
            edge_limit=edge_limit,
            min_estimated_flow=min_estimated_flow,
            sample_size=sample_size,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
