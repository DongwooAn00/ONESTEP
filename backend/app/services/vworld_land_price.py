"""VWorld 개별공시지가를 법정동 단위로 집계한다."""

from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CSV_DIR = ROOT / "data" / "processed" / "csv"
VWORLD_LAND_PRICE_URL = "https://api.vworld.kr/ned/data/getIndvdLandPriceAttr"
MAX_ROWS_PER_REQUEST = 1000
MAX_SUPPORTED_YEAR = 2022


def _load_local_env() -> None:
    """프로세스 환경변수를 우선하며 프로젝트 루트의 .env를 보완해서 읽는다."""
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def _find_legal_dong_csv() -> Path:
    configured_path = os.getenv("LEGAL_DONG_CODE_CSV")
    if configured_path:
        path = Path(configured_path).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        if path.is_file():
            return path
        raise FileNotFoundError(f"법정동 코드 CSV를 찾을 수 없습니다: {path}")

    preferred_names = (
        "법정동코드.csv",
        "국토교통부_법정동코드.csv",
        "국토교통부_법정동코드_20250805.csv",
    )
    for name in preferred_names:
        path = DEFAULT_CSV_DIR / name
        if path.is_file():
            return path

    candidates = sorted(DEFAULT_CSV_DIR.glob("*법정동코드*.csv"))
    if candidates:
        return candidates[-1]
    raise FileNotFoundError(
        f"{DEFAULT_CSV_DIR} 폴더에 법정동코드 CSV 파일을 넣어 주세요."
    )


def _read_legal_dong_rows(csv_path: Path) -> list[dict[str, str]]:
    raw = csv_path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # 국토교통부 원본 파일은 일반적으로 CP949이며 일부 행에 비표준 문자가 있을 수 있다.
        text = raw.decode("cp949", errors="replace")

    reader = csv.DictReader(text.splitlines())
    required_columns = {"법정동코드", "법정동명"}
    if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
        raise ValueError(
            "법정동 코드 CSV에 '법정동코드', '법정동명' 컬럼이 필요합니다."
        )
    return list(reader)


def _resolve_legal_dong(
    *,
    legal_dong_code: str | None,
    legal_dong_name: str | None,
) -> tuple[str, str]:
    if bool(legal_dong_code) == bool(legal_dong_name):
        raise ValueError("legal_dong_code와 legal_dong_name 중 하나만 입력해 주세요.")

    rows = _read_legal_dong_rows(_find_legal_dong_csv())
    code = str(legal_dong_code).strip() if legal_dong_code else None
    name = " ".join(str(legal_dong_name).split()) if legal_dong_name else None

    if code and (len(code) != 10 or not code.isdigit()):
        raise ValueError("legal_dong_code는 숫자 10자리여야 합니다.")

    for row in rows:
        row_code = (row.get("법정동코드") or "").strip()
        row_name = " ".join((row.get("법정동명") or "").split())
        is_match = row_code == code if code else row_name == name
        if not is_match:
            continue

        closed = (row.get("폐지여부") or "").strip()
        if closed == "폐지":
            raise ValueError(f"폐지된 법정동입니다: {row_name} ({row_code})")
        return row_code, row_name

    lookup_value = code or name
    raise ValueError(f"법정동 코드 CSV에서 일치하는 지역을 찾지 못했습니다: {lookup_value}")


def _request_page(
    *,
    api_key: str,
    domain: str,
    legal_dong_code: str,
    stdr_year: int,
    page_no: int,
    timeout: float,
) -> dict[str, Any]:
    query = urlencode(
        {
            "key": api_key,
            "domain": domain,
            "pnu": legal_dong_code,
            "stdrYear": stdr_year,
            "format": "json",
            "numOfRows": MAX_ROWS_PER_REQUEST,
            "pageNo": page_no,
        }
    )
    request = Request(
        f"{VWORLD_LAND_PRICE_URL}?{query}",
        headers={"Accept": "application/json", "User-Agent": "ONESTEP/0.1"},
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"VWorld API HTTP 오류가 발생했습니다: {error.code}") from error
    except URLError as error:
        raise RuntimeError("VWorld API에 연결하지 못했습니다.") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("VWorld API 응답을 해석하지 못했습니다.") from error


def _parse_page(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    container = payload.get("indvdLandPrices")
    if not isinstance(container, dict):
        raise RuntimeError("VWorld API 응답에 indvdLandPrices가 없습니다.")

    result_code = str(container.get("resultCode") or "").strip()
    if result_code and result_code not in {"00", "0"}:
        message = str(container.get("resultMsg") or "알 수 없는 오류")
        raise RuntimeError(f"VWorld API 오류: {message} ({result_code})")

    try:
        total_count = int(container.get("totalCount") or 0)
    except (TypeError, ValueError) as error:
        raise RuntimeError("VWorld API의 totalCount 값이 올바르지 않습니다.") from error

    fields = container.get("field") or []
    if isinstance(fields, dict):
        fields = [fields]
    if not isinstance(fields, list):
        raise RuntimeError("VWorld API의 field 값이 올바르지 않습니다.")
    return [field for field in fields if isinstance(field, dict)], total_count


def fetch_land_price_summary_by_legal_dong(
    *,
    stdr_year: int,
    req_lvl: int,
    legal_dong_code: str | None = None,
    legal_dong_name: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """법정동 내 전체 필지의 개별공시지가(원/㎡) 평균을 반환한다.

    VWorld 응답에는 필지 면적이 없으므로 각 유효 필지를 동일한 가중치로 집계한다.
    페이지별 평균을 페이지의 유효 필지 수로 가중한 값과 동일하다.
    """
    try:
        year = int(stdr_year)
    except (TypeError, ValueError) as error:
        raise ValueError("stdr_year는 4자리 연도여야 합니다.") from error
    if year < 1900 or year > MAX_SUPPORTED_YEAR:
        raise ValueError(f"stdr_year는 1900~{MAX_SUPPORTED_YEAR} 범위여야 합니다.")
    if req_lvl not in {1, 2, 3}:
        raise ValueError("req_lvl은 1, 2, 3 중 하나여야 합니다.")
    if timeout <= 0:
        raise ValueError("timeout은 0보다 커야 합니다.")

    _load_local_env()
    api_key = os.getenv("VWORLD_API_KEY", "").strip()
    domain = os.getenv("VWORLD_DOMAIN", "").strip()
    if not api_key or not domain:
        raise RuntimeError("VWORLD_API_KEY와 VWORLD_DOMAIN 환경변수가 필요합니다.")

    resolved_code, resolved_name = _resolve_legal_dong(
        legal_dong_code=legal_dong_code,
        legal_dong_name=legal_dong_name,
    )

    first_payload = _request_page(
        api_key=api_key,
        domain=domain,
        legal_dong_code=resolved_code,
        stdr_year=year,
        page_no=1,
        timeout=timeout,
    )
    first_fields, total_count = _parse_page(first_payload)
    page_count = max(1, math.ceil(total_count / MAX_ROWS_PER_REQUEST))
    all_fields = list(first_fields)

    for page_no in range(2, page_count + 1):
        payload = _request_page(
            api_key=api_key,
            domain=domain,
            legal_dong_code=resolved_code,
            stdr_year=year,
            page_no=page_no,
            timeout=timeout,
        )
        fields, page_total_count = _parse_page(payload)
        if page_total_count != total_count:
            raise RuntimeError("VWorld API 조회 중 전체 필지 수가 변경되었습니다.")
        all_fields.extend(fields)

    prices: list[int] = []
    for field in all_fields:
        try:
            price = int(str(field.get("pblntfPclnd") or "").replace(",", ""))
        except ValueError:
            continue
        if price > 0:
            prices.append(price)

    if not prices:
        raise ValueError(
            f"{resolved_name}의 {year}년 개별공시지가 자료가 없습니다."
        )

    return {
        "stdr_year": year,
        "req_lvl": req_lvl,
        "legal_dong_code": resolved_code,
        "legal_dong_name": resolved_name,
        "parcel_count": total_count,
        "valid_price_count": len(prices),
        "weighted_average_price_krw_per_sqm": round(sum(prices) / len(prices), 2),
        "minimum_price_krw_per_sqm": min(prices),
        "maximum_price_krw_per_sqm": max(prices),
        "pages_fetched": page_count,
    }
