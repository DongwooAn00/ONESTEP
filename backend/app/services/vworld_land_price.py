<<<<<<< HEAD
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
=======
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.services.legal_dong_code import load_legal_dong_codes


VWORLD_LAND_PRICE_URL = "https://api.vworld.kr/ned/data/getIndvdLandPrice"
VWORLD_MAX_ROWS_PER_PAGE = 1000


class VWorldConfigError(RuntimeError):
    pass


class VWorldRequestError(RuntimeError):
    pass


def _repair_mojibake(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _repair_mojibake(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_repair_mojibake(item) for item in value]
    if not isinstance(value, str):
        return value

    if not any(marker in value for marker in ("ì", "í", "ê", "ë", "\u0080", "\u0081", "\u0085")):
        return value

    for encoding in ("latin1", "cp1252"):
        try:
            return value.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return value


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def _extract_land_price_container(data: dict[str, Any]) -> dict[str, Any]:
    if "statelndvdLandPrices" in data and isinstance(data["statelndvdLandPrices"], dict):
        return data["statelndvdLandPrices"]
    response = data.get("response")
    if isinstance(response, dict):
        return response
    return {}


def _extract_land_price_fields(data: dict[str, Any]) -> list[dict[str, Any]]:
    container = _extract_land_price_container(data)
    fields = container.get("field", [])
    if isinstance(fields, dict):
        return [fields]
    if isinstance(fields, list):
        return [field for field in fields if isinstance(field, dict)]
    return []


def summarize_land_price_fields(
    *,
    fields: list[dict[str, Any]],
    stdr_year: int | str,
    req_lvl: int,
    ld_code: str,
    total_count: int | None = None,
) -> dict[str, Any]:
    valid_rows = []
    skipped_count = 0
    for field in fields:
        price = _to_float(field.get("ladPblntfPclnd"))
        area = _to_float(field.get("ladAr"))
        if price is None or area is None or area <= 0:
            skipped_count += 1
            continue
        valid_rows.append((field, price, area))

    prices = [price for _, price, _ in valid_rows]
    total_area = sum(area for _, _, area in valid_rows)
    weighted_sum = sum(price * area for _, price, area in valid_rows)
    weighted_average = weighted_sum / total_area if total_area > 0 else None
    first_named = next((field for field, _, _ in valid_rows if field.get("ldCodeNm")), None)

    return {
        "stdr_year": int(stdr_year),
        "req_lvl": req_lvl,
        "ld_code": ld_code,
        "ld_code_name": first_named.get("ldCodeNm") if first_named else None,
        "total_count": total_count if total_count is not None else len(fields),
        "used_count": len(valid_rows),
        "skipped_count": skipped_count,
        "total_area_sqm": round(total_area, 3),
        "weighted_average_price_krw_per_sqm": round(weighted_average, 3) if weighted_average is not None else None,
        "simple_average_price_krw_per_sqm": round(sum(prices) / len(prices), 3) if prices else None,
        "min_price_krw_per_sqm": min(prices) if prices else None,
        "max_price_krw_per_sqm": max(prices) if prices else None,
    }


def _resolve_credential(value: str | None, env_name: str) -> str:
    resolved = value or os.environ.get(env_name, "")
    if not resolved:
        raise VWorldConfigError(f"{env_name} 환경변수를 설정하거나 함수 인자로 전달해야 합니다.")
    return resolved


def validate_land_price_params(req_lvl: int, ld_code: str) -> None:
    if req_lvl not in (1, 2, 3):
        raise ValueError("reqLvl은 1, 2, 3 중 하나여야 합니다.")
    if req_lvl == 1:
        return
    if req_lvl == 2 and not 2 <= len(ld_code) <= 5:
        raise ValueError("reqLvl=2는 ldCode가 2~5자리여야 합니다.")
    if req_lvl == 3 and not 2 <= len(ld_code) <= 10:
        raise ValueError("reqLvl=3은 ldCode가 2~10자리여야 합니다.")
    if not ld_code.isdigit():
        raise ValueError("ldCode는 숫자 문자열이어야 합니다.")


def resolve_vworld_ld_code(*, legal_dong_code: str = "", legal_dong_name: str = "", req_lvl: int) -> str:
    """법정동 코드/이름을 VWorld API의 reqLvl에 맞는 ldCode로 변환합니다."""
    normalized_code = legal_dong_code.strip()
    normalized_name = legal_dong_name.strip()

    if req_lvl not in (1, 2, 3):
        raise ValueError("reqLvl은 1, 2, 3 중 하나여야 합니다.")
    if req_lvl == 1:
        return ""
    if not normalized_code and not normalized_name:
        raise ValueError("legal_dong_code 또는 legal_dong_name 중 하나는 필요합니다.")

    if normalized_code:
        if not normalized_code.isdigit():
            raise ValueError("legal_dong_code는 숫자 문자열이어야 합니다.")
        source_code = normalized_code
    else:
        matches = [
            row
            for row in load_legal_dong_codes()
            if row["legal_dong_name"] == normalized_name
        ]
        if not matches:
            raise ValueError(f"법정동명을 찾을 수 없습니다: {normalized_name}")
        if len(matches) > 1:
            raise ValueError("동일한 법정동명이 여러 개입니다. legal_dong_code를 직접 전달하세요.")
        source_code = matches[0]["legal_dong_code"]

    if req_lvl == 2:
        if len(source_code) < 2:
            raise ValueError("reqLvl=2 변환에는 최소 2자리 법정동 코드가 필요합니다.")
        return source_code[:5]

    return source_code[:10]


def fetch_individual_land_prices(
    *,
    stdr_year: int | str,
    req_lvl: int,
    ld_code: str = "",
    page_no: int = 1,
    num_of_rows: int = 10,
    api_key: str | None = None,
    domain: str | None = None,
    response_format: str = "json",
    timeout: float = 10,
) -> dict[str, Any] | str:
    """VWorld 개별공시지가 목록 조회 API(getIndvdLandPrice)를 호출합니다."""
    normalized_year = str(stdr_year).strip()
    normalized_code = ld_code.strip()
    normalized_format = response_format.lower().strip()

    if len(normalized_year) != 4 or not normalized_year.isdigit():
        raise ValueError("stdrYear는 YYYY 형식의 4자리 연도여야 합니다.")
    if page_no < 1:
        raise ValueError("pageNo는 1 이상이어야 합니다.")
    if not 1 <= num_of_rows <= 1000:
        raise ValueError("numOfRows는 1~1000 사이여야 합니다.")
    if normalized_format not in ("json", "xml"):
        raise ValueError("format은 json 또는 xml이어야 합니다.")
    validate_land_price_params(req_lvl, normalized_code)

    params = {
        "key": _resolve_credential(api_key, "VWORLD_API_KEY"),
        "domain": _resolve_credential(domain, "VWORLD_DOMAIN"),
        "stdrYear": normalized_year,
        "reqLvl": str(req_lvl),
        "format": normalized_format,
        "numOfRows": str(num_of_rows),
        "pageNo": str(page_no),
    }
    if req_lvl != 1:
        params["ldCode"] = normalized_code

    url = f"{VWORLD_LAND_PRICE_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, method="GET")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read()
            charset = response.headers.get_content_charset() if hasattr(response, "headers") else None
    except urllib.error.HTTPError as error:
        raise VWorldRequestError(f"VWorld API HTTP 오류: {error.code}") from error
    except urllib.error.URLError as error:
        raise VWorldRequestError(f"VWorld API 요청 실패: {error.reason}") from error

    body = None
    encodings = [charset] if charset else []
    encodings.extend(["utf-8", "cp949", "euc-kr"])
    for encoding in encodings:
        if not encoding:
            continue
        try:
            body = raw_body.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if body is None:
        body = raw_body.decode("utf-8", errors="replace")

    if normalized_format == "json":
        return _repair_mojibake(json.loads(body))
    return body


def fetch_individual_land_prices_by_legal_dong(
    *,
    stdr_year: int | str,
    req_lvl: int,
    legal_dong_code: str = "",
    legal_dong_name: str = "",
    page_no: int = 1,
    num_of_rows: int = 10,
    api_key: str | None = None,
    domain: str | None = None,
    response_format: str = "json",
    timeout: float = 10,
) -> dict[str, Any] | str:
    """법정동 CSV 기준 코드/이름을 받아 VWorld 개별공시지가 API를 호출합니다."""
    ld_code = resolve_vworld_ld_code(
        legal_dong_code=legal_dong_code,
        legal_dong_name=legal_dong_name,
        req_lvl=req_lvl,
    )
    return fetch_individual_land_prices(
        stdr_year=stdr_year,
        req_lvl=req_lvl,
        ld_code=ld_code,
        page_no=page_no,
        num_of_rows=num_of_rows,
        api_key=api_key,
        domain=domain,
        response_format=response_format,
        timeout=timeout,
    )


def fetch_land_price_summary(
    *,
    stdr_year: int | str,
    req_lvl: int,
    ld_code: str = "",
    api_key: str | None = None,
    domain: str | None = None,
    timeout: float = 10,
) -> dict[str, Any]:
    first_page = fetch_individual_land_prices(
        stdr_year=stdr_year,
        req_lvl=req_lvl,
        ld_code=ld_code,
        page_no=1,
        num_of_rows=VWORLD_MAX_ROWS_PER_PAGE,
        api_key=api_key,
        domain=domain,
        timeout=timeout,
    )
    if not isinstance(first_page, dict):
        raise VWorldRequestError("VWorld API JSON 응답을 파싱하지 못했습니다.")

    container = _extract_land_price_container(first_page)
    total_count = _to_int(container.get("totalCount"))
    fields = _extract_land_price_fields(first_page)
    page_count = (total_count + VWORLD_MAX_ROWS_PER_PAGE - 1) // VWORLD_MAX_ROWS_PER_PAGE

    for page_no in range(2, page_count + 1):
        page = fetch_individual_land_prices(
            stdr_year=stdr_year,
            req_lvl=req_lvl,
            ld_code=ld_code,
            page_no=page_no,
            num_of_rows=VWORLD_MAX_ROWS_PER_PAGE,
            api_key=api_key,
            domain=domain,
            timeout=timeout,
        )
        if not isinstance(page, dict):
            raise VWorldRequestError("VWorld API JSON 응답을 파싱하지 못했습니다.")
        fields.extend(_extract_land_price_fields(page))

    return summarize_land_price_fields(
        fields=fields,
        stdr_year=stdr_year,
        req_lvl=req_lvl,
        ld_code=ld_code,
        total_count=total_count,
    )
>>>>>>> 2759c0f66d0ef022f7d0f892afee68f370dee2cd


def fetch_land_price_summary_by_legal_dong(
    *,
<<<<<<< HEAD
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
=======
    stdr_year: int | str,
    req_lvl: int,
    legal_dong_code: str = "",
    legal_dong_name: str = "",
    api_key: str | None = None,
    domain: str | None = None,
    timeout: float = 10,
) -> dict[str, Any]:
    ld_code = resolve_vworld_ld_code(
        legal_dong_code=legal_dong_code,
        legal_dong_name=legal_dong_name,
        req_lvl=req_lvl,
    )
    return fetch_land_price_summary(
        stdr_year=stdr_year,
        req_lvl=req_lvl,
        ld_code=ld_code,
        api_key=api_key,
        domain=domain,
        timeout=timeout,
    )
>>>>>>> 2759c0f66d0ef022f7d0f892afee68f370dee2cd
