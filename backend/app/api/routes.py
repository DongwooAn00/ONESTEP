from io import StringIO

from fastapi import APIRouter, File, Form, HTTPException

from app.schemas.candidate_routes import CandidateRouteRequest, CandidateRouteResult
from app.schemas.economic import AnalysisRequest, AnalysisResult
from app.schemas.od_candidates import ODCandidateResult
from app.schemas.route_cost import EvaluateRouteRequest, EvaluateRouteResult, RouteCostRequest, RouteCostResult
from app.schemas.route_generation import RouteGenerationRequest, RouteGenerationResult
from app.schemas.vworld_land_price import (
    LandPriceRequest,
    LandPriceResult,
    LegalDongCodeResult,
    LegalDongLandPriceRequest,
)
from app.services.candidate_route_pipeline import build_candidate_routes
from app.services.economic_analysis import analyze_project
from app.services.legal_dong_code import list_legal_dong_codes
from app.services.od_candidate_generation import build_od_candidates, build_od_candidates_with_supplemental
from app.services.route_cost import analyze_route_cost, evaluate_route
from app.services.route_generation import generate_route_candidates
from app.services.vworld_land_price import (
    VWorldConfigError,
    VWorldRequestError,
    fetch_individual_land_prices,
    fetch_individual_land_prices_by_legal_dong,
)

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


@router.get("/legal-dong-codes", response_model=LegalDongCodeResult)
def get_legal_dong_codes(req_lvl: int, ld_code: str = "") -> LegalDongCodeResult:
    try:
        return LegalDongCodeResult(items=list_legal_dong_codes(req_lvl, ld_code))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.post("/land-prices", response_model=LandPriceResult)
def create_land_price_lookup(payload: LandPriceRequest) -> LandPriceResult:
    try:
        data = fetch_individual_land_prices(
            stdr_year=payload.stdr_year,
            req_lvl=payload.req_lvl,
            ld_code=payload.ld_code,
            page_no=payload.page_no,
            num_of_rows=payload.num_of_rows,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except VWorldConfigError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except VWorldRequestError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="VWorld API JSON 응답을 파싱하지 못했습니다.")
    return LandPriceResult(data=data)


@router.post("/land-prices/by-legal-dong", response_model=LandPriceResult)
def create_land_price_lookup_by_legal_dong(payload: LegalDongLandPriceRequest) -> LandPriceResult:
    try:
        data = fetch_individual_land_prices_by_legal_dong(
            stdr_year=payload.stdr_year,
            req_lvl=payload.req_lvl,
            legal_dong_code=payload.legal_dong_code,
            legal_dong_name=payload.legal_dong_name,
            page_no=payload.page_no,
            num_of_rows=payload.num_of_rows,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except VWorldConfigError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except VWorldRequestError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="VWorld API JSON 응답을 파싱하지 못했습니다.")
    return LandPriceResult(data=data)


@router.post("/od-candidates", response_model=ODCandidateResult)
async def create_od_candidates(
    top_node_limit: int = Form(default=100),
    flow_filter_percent: int | None = Form(default=None),
    low_impact_prune_percent: int | None = Form(default=20),
    edge_limit: int = Form(default=50),
    min_estimated_flow: float | None = Form(default=None),
    sample_size: int | None = Form(default=None),
    include_base_od: bool = Form(default=True),
    file: bytes | None = File(default=None),
    supplemental_file: bytes | None = File(default=None),
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
    if not include_base_od and supplemental_file is None:
        raise HTTPException(status_code=400, detail="Select at least one OD source.")

    try:
        base_source = StringIO(file.decode("utf-8-sig")) if file is not None else None
        if supplemental_file is not None:
            supplemental_csv = StringIO(supplemental_file.decode("utf-8-sig"))
            if include_base_od:
                source_name = (
                    "uploaded_od.csv + scenario_od.csv"
                    if file is not None
                    else "synthetic_admin_dong_od_by_mode.csv + scenario_od.csv"
                )
            else:
                source_name = "scenario_od.csv"
            return build_od_candidates_with_supplemental(
                base_source,
                supplemental_csv,
                source_name,
                include_base_od=include_base_od,
                flow_filter_percent=flow_filter_percent,
                top_node_limit=top_node_limit,
                low_impact_prune_percent=low_impact_prune_percent,
                edge_limit=edge_limit,
                min_estimated_flow=min_estimated_flow,
                sample_size=sample_size,
            )

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

        return build_od_candidates(
            base_source,
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
