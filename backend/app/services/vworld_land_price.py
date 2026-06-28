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
        raise VWorldConfigError(f"{env_name} is required.")
    return resolved


def validate_land_price_params(req_lvl: int, ld_code: str) -> None:
    if req_lvl not in (1, 2, 3):
        raise ValueError("reqLvl must be one of 1, 2, or 3.")
    if req_lvl == 1:
        return
    if req_lvl == 2 and not 2 <= len(ld_code) <= 5:
        raise ValueError("reqLvl=2 requires ldCode length between 2 and 5.")
    if req_lvl == 3 and not 2 <= len(ld_code) <= 10:
        raise ValueError("reqLvl=3 requires ldCode length between 2 and 10.")
    if not ld_code.isdigit():
        raise ValueError("ldCode must contain digits only.")


def resolve_vworld_ld_code(*, legal_dong_code: str = "", legal_dong_name: str = "", req_lvl: int) -> str:
    normalized_code = legal_dong_code.strip()
    normalized_name = legal_dong_name.strip()

    if req_lvl not in (1, 2, 3):
        raise ValueError("reqLvl must be one of 1, 2, or 3.")
    if req_lvl == 1:
        return ""
    if not normalized_code and not normalized_name:
        raise ValueError("legal_dong_code or legal_dong_name is required.")

    if normalized_code:
        if not normalized_code.isdigit():
            raise ValueError("legal_dong_code must contain digits only.")
        source_code = normalized_code
    else:
        matches = [
            row
            for row in load_legal_dong_codes()
            if row["legal_dong_name"] == normalized_name
        ]
        if not matches:
            raise ValueError(f"Legal dong name was not found: {normalized_name}")
        if len(matches) > 1:
            raise ValueError("Multiple legal dong rows matched. Pass legal_dong_code directly.")
        source_code = matches[0]["legal_dong_code"]

    if req_lvl == 2:
        if len(source_code) < 2:
            raise ValueError("reqLvl=2 requires at least a 2-digit legal dong code.")
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
    normalized_year = str(stdr_year).strip()
    normalized_code = ld_code.strip()
    normalized_format = response_format.lower().strip()

    if len(normalized_year) != 4 or not normalized_year.isdigit():
        raise ValueError("stdrYear must be a 4-digit year.")
    if page_no < 1:
        raise ValueError("pageNo must be greater than or equal to 1.")
    if not 1 <= num_of_rows <= VWORLD_MAX_ROWS_PER_PAGE:
        raise ValueError("numOfRows must be between 1 and 1000.")
    if normalized_format not in ("json", "xml"):
        raise ValueError("format must be json or xml.")
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
        raise VWorldRequestError(f"VWorld API HTTP error: {error.code}") from error
    except urllib.error.URLError as error:
        raise VWorldRequestError(f"VWorld API request failed: {error.reason}") from error

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
        try:
            return _repair_mojibake(json.loads(body))
        except json.JSONDecodeError as error:
            raise VWorldRequestError("VWorld API JSON response could not be parsed.") from error
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
        raise VWorldRequestError("VWorld API JSON response could not be parsed.")

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
            raise VWorldRequestError("VWorld API JSON response could not be parsed.")
        fields.extend(_extract_land_price_fields(page))

    return summarize_land_price_fields(
        fields=fields,
        stdr_year=stdr_year,
        req_lvl=req_lvl,
        ld_code=ld_code,
        total_count=total_count,
    )


def fetch_land_price_summary_by_legal_dong(
    *,
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
