from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.services.legal_dong_code import load_legal_dong_codes


VWORLD_LAND_PRICE_URL = "https://api.vworld.kr/ned/data/getIndvdLandPrice"


class VWorldConfigError(RuntimeError):
    pass


class VWorldRequestError(RuntimeError):
    pass


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
            charset = response.headers.get_content_charset()
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
        return json.loads(body)
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
