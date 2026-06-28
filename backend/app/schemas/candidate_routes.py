from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.region_filter import normalize_region_names
from app.schemas.od_candidates import CandidateEdge, CandidateNode


class CandidateRouteRequest(BaseModel):
    nodes: list[CandidateNode] = Field(min_length=2)
    edges: list[CandidateEdge] = Field(min_length=1)
    route_limit: int = Field(default=20, ge=1, le=50)
    selected_regions: list[str] | None = None
    use_region_filter: bool = False
    region_buffer_km: float = Field(default=10.0, ge=0, le=100)

    @field_validator("selected_regions")
    @classmethod
    def validate_selected_regions(cls, value: list[str] | None) -> list[str] | None:
        """지원하지 않는 시도명은 API 계산 전에 명확히 거부한다."""
        if value is None:
            return None
        return list(normalize_region_names(value))


class CandidateRouteGeometry(BaseModel):
    lat: float
    lon: float


class CandidateRoute(BaseModel):
    model_config = ConfigDict(extra="allow")

    route_id: str
    route_type: str = "new_direct"
    from_node_id: str
    to_node_id: str
    route_geometry: list[CandidateRouteGeometry]
    route_length_km: float
    geometry: list[CandidateRouteGeometry] = Field(default_factory=list)
    segments: list[dict] = Field(default_factory=list)
    connector_length_km: float = 0.0
    new_surface_road_length_km: float = 0.0
    tunnel_length_km: float = 0.0
    construction_cost: float = 0.0
    annual_benefit: float = 0.0
    total_benefit: float = 0.0
    benefit_cost_ratio: float = 0.0
    distance_saving_km: float = 0.0
    time_saving_minutes: float = 0.0
    candidate_score: float = 0.0
    explanation: list[str] = Field(default_factory=list)
    existing_road_access_length_km: float = 0.0
    existing_road_access_percent: float = 0.0
    route_generation_method: str = "unknown"
    status: str
    failed_reason: str | None = None


class CandidateRouteSegment(BaseModel):
    model_config = ConfigDict(extra="allow")

    route_id: str
    segment_id: str
    segment_type: str
    segment_length_km: float
    segment_geometry: list[CandidateRouteGeometry]
    average_slope: float
    max_slope: float


class CandidateRouteCost(BaseModel):
    model_config = ConfigDict(extra="allow")

    route_id: str
    surface_road_length_km: float
    existing_road_length_km: float = 0.0
    connector_length_km: float = 0.0
    new_surface_road_length_km: float = 0.0
    tunnel_length_km: float
    surface_road_cost: float
    new_road_cost: float = 0.0
    connector_cost: float = 0.0
    tunnel_cost: float
    land_compensation_cost: float = 0.0
    land_compensation: dict = Field(default_factory=dict)
    total_direct_cost: float
    surface_road_screen_cost: float
    new_road_screen_cost: float = 0.0
    connector_screen_cost: float = 0.0
    tunnel_screen_cost: float
    total_screen_cost: float
    cost_assumptions: dict


class RankedCandidateRoute(BaseModel):
    model_config = ConfigDict(extra="allow")

    rank: int
    route_id: str
    from_node_id: str
    to_node_id: str
    estimated_flow: float
    distance_saving_km: float
    total_screen_cost: float
    economic_score: float
    summary: dict


class CandidateRouteResult(BaseModel):
    routes: list[CandidateRoute]
    candidates: list[CandidateRoute] = Field(default_factory=list)
    segments: list[CandidateRouteSegment]
    costs: list[CandidateRouteCost]
    ranked_routes: list[RankedCandidateRoute]
    best_candidate: CandidateRoute | None = None
    route: CandidateRoute | None = None
    warnings: list[str] = Field(default_factory=list)
    result_files: dict[str, str] = Field(default_factory=dict)
    region_filter_summary: dict = Field(default_factory=dict)
