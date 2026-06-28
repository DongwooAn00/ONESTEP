from pydantic import BaseModel, Field


class LegalDongCodeItem(BaseModel):
    legal_dong_code: str
    legal_dong_name: str


class LegalDongCodeResult(BaseModel):
    items: list[LegalDongCodeItem]


class LandPriceRequest(BaseModel):
    stdr_year: int = Field(ge=1900, le=2100)
    req_lvl: int = Field(ge=1, le=3)
    ld_code: str = ""
    page_no: int = Field(default=1, ge=1)
    num_of_rows: int = Field(default=10, ge=1, le=1000)


class LegalDongLandPriceRequest(BaseModel):
    stdr_year: int = Field(ge=1900, le=2100)
    req_lvl: int = Field(ge=1, le=3)
    legal_dong_code: str = ""
    legal_dong_name: str = ""
    page_no: int = Field(default=1, ge=1)
    num_of_rows: int = Field(default=10, ge=1, le=1000)


class LandPriceResult(BaseModel):
    data: dict


class LandPriceSummary(BaseModel):
    stdr_year: int
    req_lvl: int
    ld_code: str
    ld_code_name: str | None = None
    total_count: int
    used_count: int
    skipped_count: int
    total_area_sqm: float
    weighted_average_price_krw_per_sqm: float | None = None
    simple_average_price_krw_per_sqm: float | None = None
    min_price_krw_per_sqm: float | None = None
    max_price_krw_per_sqm: float | None = None


class LandPriceSummaryResult(BaseModel):
    summary: LandPriceSummary
