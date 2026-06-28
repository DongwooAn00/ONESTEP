<<<<<<< HEAD
from pathlib import Path

import pytest

from app.services import vworld_land_price


def _write_legal_dong_csv(path: Path) -> None:
    path.write_text(
        "법정동코드,법정동명,폐지여부\n"
        "4793025021,경상북도 울진군 울진읍 읍내리,존재\n",
        encoding="utf-8",
    )


def test_fetches_every_page_and_calculates_parcel_average(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    csv_path = tmp_path / "법정동코드.csv"
    _write_legal_dong_csv(csv_path)
    monkeypatch.setenv("LEGAL_DONG_CODE_CSV", str(csv_path))
    monkeypatch.setenv("VWORLD_API_KEY", "test-key")
    monkeypatch.setenv("VWORLD_DOMAIN", "http://localhost")
    monkeypatch.setattr(vworld_land_price, "MAX_ROWS_PER_REQUEST", 2)

    requested_pages: list[int] = []

    def fake_request_page(**kwargs):
        page_no = kwargs["page_no"]
        requested_pages.append(page_no)
        page_prices = {1: ["100", "300"], 2: ["500"]}[page_no]
        return {
            "indvdLandPrices": {
                "field": [
                    {"pblntfPclnd": price}
                    for price in page_prices
                ],
                "totalCount": "3",
                "resultCode": "",
                "resultMsg": "",
            }
        }

    monkeypatch.setattr(vworld_land_price, "_request_page", fake_request_page)

    summary = vworld_land_price.fetch_land_price_summary_by_legal_dong(
        stdr_year=2022,
        req_lvl=3,
        legal_dong_name="경상북도 울진군 울진읍 읍내리",
    )

    assert requested_pages == [1, 2]
    assert summary["legal_dong_code"] == "4793025021"
    assert summary["weighted_average_price_krw_per_sqm"] == 300.0
    assert summary["valid_price_count"] == 3


def test_rejects_year_after_2022() -> None:
    with pytest.raises(ValueError, match="2022"):
        vworld_land_price.fetch_land_price_summary_by_legal_dong(
            stdr_year=2023,
            req_lvl=3,
            legal_dong_code="4793025021",
        )


def test_requires_exactly_one_location_identifier() -> None:
    with pytest.raises(ValueError, match="중 하나만"):
        vworld_land_price._resolve_legal_dong(
            legal_dong_code="4793025021",
            legal_dong_name="경상북도 울진군 울진읍 읍내리",
        )
=======
import json

import pytest

from app.services.legal_dong_code import list_legal_dong_codes
from app.services.vworld_land_price import (
    fetch_individual_land_prices,
    fetch_individual_land_prices_by_legal_dong,
    resolve_vworld_ld_code,
    summarize_land_price_fields,
)


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({"response": {"status": "OK"}}).encode("utf-8")

    class _Headers:
        def get_content_charset(self):
            return "utf-8"

    headers = _Headers()


def test_list_legal_dong_codes_returns_sido_rows():
    rows = list_legal_dong_codes(req_lvl=1)

    assert any(row["legal_dong_code"] == "1100000000" for row in rows)


def test_fetch_individual_land_prices_builds_vworld_request(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = fetch_individual_land_prices(
        api_key="test-key",
        domain="localhost",
        stdr_year=2015,
        req_lvl=3,
        ld_code="4793025021",
        num_of_rows=10,
        page_no=1,
    )

    assert result == {"response": {"status": "OK"}}
    assert "getIndvdLandPrice" in captured["url"]
    assert "stdrYear=2015" in captured["url"]
    assert "reqLvl=3" in captured["url"]
    assert "ldCode=4793025021" in captured["url"]
    assert captured["timeout"] == 10


def test_fetch_individual_land_prices_validates_req_lvl_code_length():
    with pytest.raises(ValueError):
        fetch_individual_land_prices(
            api_key="test-key",
            domain="localhost",
            stdr_year=2015,
            req_lvl=2,
            ld_code="1",
        )


def test_resolve_vworld_ld_code_converts_full_legal_dong_code():
    assert resolve_vworld_ld_code(req_lvl=2, legal_dong_code="4793025021") == "47930"
    assert resolve_vworld_ld_code(req_lvl=3, legal_dong_code="4793025021") == "4793025021"


def test_fetch_individual_land_prices_by_legal_dong_builds_vworld_request(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return _FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = fetch_individual_land_prices_by_legal_dong(
        api_key="test-key",
        domain="localhost",
        stdr_year=2015,
        req_lvl=2,
        legal_dong_code="4793025021",
    )

    assert result == {"response": {"status": "OK"}}
    assert "reqLvl=2" in captured["url"]
    assert "ldCode=47930" in captured["url"]


def test_summarize_land_price_fields_uses_area_weighted_average():
    summary = summarize_land_price_fields(
        stdr_year=2022,
        req_lvl=3,
        ld_code="1111010100",
        total_count=3,
        fields=[
            {
                "ldCodeNm": "서울특별시 종로구 청운동",
                "ladPblntfPclnd": "100",
                "ladAr": "10",
            },
            {
                "ldCodeNm": "서울특별시 종로구 청운동",
                "ladPblntfPclnd": "200",
                "ladAr": "30",
            },
            {
                "ldCodeNm": "서울특별시 종로구 청운동",
                "ladPblntfPclnd": "",
                "ladAr": "20",
            },
        ],
    )

    assert summary["ld_code_name"] == "서울특별시 종로구 청운동"
    assert summary["total_count"] == 3
    assert summary["used_count"] == 2
    assert summary["skipped_count"] == 1
    assert summary["total_area_sqm"] == 40
    assert summary["weighted_average_price_krw_per_sqm"] == 175
    assert summary["simple_average_price_krw_per_sqm"] == 150
>>>>>>> 2759c0f66d0ef022f7d0f892afee68f370dee2cd
