from pydantic import BaseModel, Field


class AnalysisRequest(BaseModel):
    tunnel_length_km: float = Field(gt=0)
    construction_cost_billion_krw: float = Field(ge=0)
    annual_benefit_billion_krw: float = Field(ge=0)
    annual_operation_cost_billion_krw: float = Field(ge=0)
    operation_years: int = Field(gt=0)
    discount_rate_percent: float = Field(ge=0)


class AnalysisResult(BaseModel):
    benefit_cost_ratio: float
    net_present_value_billion_krw: float
    total_present_benefit_billion_krw: float
    total_present_cost_billion_krw: float
