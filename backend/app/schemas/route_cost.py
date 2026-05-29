from pydantic import BaseModel, Field, model_validator


class RouteCostRequest(BaseModel):
    start_lat: float = Field(ge=-90, le=90)
    start_lon: float = Field(ge=-180, le=180)
    end_lat: float = Field(ge=-90, le=90)
    end_lon: float = Field(ge=-180, le=180)
    rock_factor: float = Field(default=1.15, ge=0.5, le=3.0)
    sample_interval_m: float = Field(default=90, ge=30, le=500)
    road_unit_cost_billion_krw_per_km: float = Field(default=12, ge=0)
    tunnel_unit_cost_billion_krw_per_km: float = Field(default=80, ge=0)
    steep_road_factor: float = Field(default=1.3, ge=1)


class Coordinate(BaseModel):
    lat: float
    lon: float


class CostParameters(BaseModel):
    rock_factor: float = Field(default=1.15, ge=0.5, le=3.0)
    sample_interval_m: float = Field(default=90, ge=30, le=500)
    road_unit_cost_billion_krw_per_km: float = Field(default=12, ge=0)
    tunnel_unit_cost_billion_krw_per_km: float = Field(default=80, ge=0)
    steep_road_factor: float = Field(default=1.3, ge=1)


class AccessPoint(BaseModel):
    node_id: str
    distance_m: float
    coordinate: Coordinate


class RouteSegment(BaseModel):
    segment_type: str
    length_m: float
    average_slope_percent: float
    max_slope_percent: float


class RouteCandidate(BaseModel):
    name: str
    total_length_m: float
    road_length_m: float
    steep_road_length_m: float
    tunnel_length_m: float
    max_slope_percent: float
    min_elevation_m: float
    max_elevation_m: float
    estimated_cost_billion_krw: float
    segments: list[RouteSegment]
    coordinates: list[Coordinate]


class EvaluateRouteRequest(CostParameters):
    name: str = Field(default="candidate")
    coordinates: list[Coordinate] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_distinct_coordinates(self) -> "EvaluateRouteRequest":
        unique_coordinates = {(coordinate.lat, coordinate.lon) for coordinate in self.coordinates}
        if len(unique_coordinates) < 2:
            raise ValueError("서로 다른 좌표가 2개 이상 필요합니다.")
        return self


class EvaluateRouteResult(BaseModel):
    candidate: RouteCandidate


class RouteCostResult(BaseModel):
    start_access: AccessPoint
    end_access: AccessPoint
    recommended_candidate: str
    candidates: list[RouteCandidate]
