from pydantic import BaseModel, Field

from app.schemas.route_cost import Coordinate, CostParameters


class RouteGenerationRequest(CostParameters):
    start_lat: float = Field(ge=-90, le=90)
    start_lon: float = Field(ge=-180, le=180)
    end_lat: float = Field(ge=-90, le=90)
    end_lon: float = Field(ge=-180, le=180)
    candidate_count: int = Field(default=3, ge=1, le=20)


class GeneratedRouteCandidate(BaseModel):
    name: str
    coordinates: list[Coordinate]


class RouteGenerationResult(BaseModel):
    candidates: list[GeneratedRouteCandidate]
