from pydantic import BaseModel, Field

from app.schemas.od_candidates import CandidateEdge, CandidateNode


class CandidateRouteRequest(BaseModel):
    nodes: list[CandidateNode] = Field(min_length=2)
    edges: list[CandidateEdge] = Field(min_length=1)
    route_limit: int = Field(default=20, ge=1, le=50)


class CandidateRouteGeometry(BaseModel):
    lat: float
    lon: float


class CandidateRoute(BaseModel):
    route_id: str
    from_node_id: str
    to_node_id: str
    route_geometry: list[CandidateRouteGeometry]
    route_length_km: float
    existing_road_access_length_km: float = 0.0
    existing_road_access_percent: float = 0.0
    route_generation_method: str = "unknown"
    status: str
    failed_reason: str | None = None


class CandidateRouteSegment(BaseModel):
    route_id: str
    segment_id: str
    segment_type: str
    segment_length_km: float
    segment_geometry: list[CandidateRouteGeometry]
    average_slope: float
    max_slope: float


class CandidateRouteCost(BaseModel):
    route_id: str
    surface_road_length_km: float
    existing_road_length_km: float = 0.0
    existing_tunnel_length_km: float = 0.0
    new_surface_road_length_km: float = 0.0
    tunnel_length_km: float
    bridge_length_km: float
    surface_road_cost: float
    tunnel_cost: float
    bridge_cost: float
    total_direct_cost: float
    surface_road_screen_cost: float
    tunnel_screen_cost: float
    bridge_screen_cost: float
    total_screen_cost: float
    cost_assumptions: dict


class RankedCandidateRoute(BaseModel):
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
    segments: list[CandidateRouteSegment]
    costs: list[CandidateRouteCost]
    ranked_routes: list[RankedCandidateRoute]
    warnings: list[str] = Field(default_factory=list)
    result_files: dict[str, str] = Field(default_factory=dict)
