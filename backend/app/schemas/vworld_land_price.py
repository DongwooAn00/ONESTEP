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
