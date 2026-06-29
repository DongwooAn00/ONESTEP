from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OD_RESPONSE = ROOT / "data" / "processed" / "gangwon_od_api_response.json"
ROUTE_RESPONSE = ROOT / "data" / "processed" / "gangwon_candidate_route_api_response.json"
RUN_METRICS = ROOT / "data" / "processed" / "gangwon_candidate_route_run_metrics.json"


def main() -> None:
    od_result = json.loads(OD_RESPONSE.read_text(encoding="utf-8"))
    region = od_result["stats"]["region_filter_summary"]
    payload = {
        "nodes": od_result["nodes"],
        "edges": od_result["edges"],
        "route_limit": 5,
        "selected_regions": region["selected_regions"],
        "use_region_filter": True,
        "region_buffer_km": region["buffer_km"],
    }
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:8000/api/candidate-routes",
        data=encoded,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    started = time.perf_counter()
    status = None
    error = None
    response_bytes = b""
    try:
        with urllib.request.urlopen(request, timeout=1800) as response:
            status = response.status
            response_bytes = response.read()
        ROUTE_RESPONSE.write_bytes(response_bytes)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        RUN_METRICS.write_text(
            json.dumps(
                {
                    "http_status": status,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "response_bytes": len(response_bytes),
                    "error": error,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
