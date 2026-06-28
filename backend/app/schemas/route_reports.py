from __future__ import annotations

from pydantic import BaseModel, Field


class CandidateRouteReportsRequest(BaseModel):
    routes: list[dict] = Field(min_length=1)
    segments: list[dict] = Field(default_factory=list)
    costs: list[dict] = Field(default_factory=list)
    ranked_routes: list[dict] = Field(default_factory=list)
    route_ids: list[str] | None = None


class RouteReportMetrics(BaseModel):
    unit: str = "eok_krw"
    total_length_km: float | None = None
    road_length_km: float | None = None
    existing_road_length_km: float | None = None
    connector_length_km: float | None = None
    new_road_length_km: float | None = None
    tunnel_length_km: float | None = None
    road_construction_cost: float | None = None
    tunnel_construction_cost: float | None = None
    land_compensation_cost: float | None = None
    annual_maintenance_cost: float | None = None
    maintenance_cost: float | None = None
    construction_cost: float | None = None
    total_project_cost: float | None = None
    annual_benefit: float | None = None
    benefit: float | None = None
    benefit_cost_ratio: float | None = None
    net_present_value: float | None = None
    economic_score: float | None = None
    distance_saving_km: float | None = None
    time_saving_minutes: float | None = None
    average_slope: float | None = None
    max_slope: float | None = None


class RouteReport(BaseModel):
    route_id: str
    title: str
    summary: str
    route_overview: str
    cost_analysis: str
    benefit_analysis: str
    technical_review: str
    risk_review: str
    final_opinion: str
    advantages: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metrics: RouteReportMetrics
    markdown: str
    generator: str = "template"


class CandidateRouteReportsResult(BaseModel):
    reports: list[RouteReport]
    report_count: int
    generator: str = "template"
