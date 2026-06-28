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
