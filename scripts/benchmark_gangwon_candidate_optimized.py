from __future__ import annotations

import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas.od_candidates import CandidateEdge, CandidateNode  # noqa: E402
from app.services.candidate_route_pipeline import build_candidate_routes  # noqa: E402


def main() -> None:
    source = json.loads(
        (ROOT / "data" / "processed" / "gangwon_od_api_response.json").read_text(
            encoding="utf-8"
        )
    )
    nodes = [CandidateNode.model_validate(item) for item in source["nodes"]]
    edges = [CandidateEdge.model_validate(item) for item in source["edges"]]
    started = time.perf_counter()
    result = build_candidate_routes(
        nodes,
        edges,
        route_limit=5,
        persist_files=False,
        selected_regions=["강원특별자치도"],
        use_region_filter=True,
        region_buffer_km=0.0,
    )
    elapsed = time.perf_counter() - started
    payload = json.dumps(result, ensure_ascii=False).encode("utf-8")
    (
        ROOT
        / "data"
        / "processed"
        / "gangwon_candidate_optimized_result.json"
    ).write_bytes(payload)
    metrics = {
        "elapsed_seconds": round(elapsed, 3),
        "response_bytes": len(payload),
        "route_count": len(result["routes"]),
        "ranked_count": len(result["ranked_routes"]),
        "segment_count": len(result["segments"]),
        "route_geometry_points": sum(
            len(route.get("geometry") or []) for route in result["routes"]
        ),
        "segment_geometry_points": sum(
            len(segment.get("segment_geometry") or [])
            for segment in result["segments"]
        ),
        "warnings": result["warnings"],
        "region_filter_summary": result["region_filter_summary"],
    }
    output = ROOT / "data" / "processed" / "gangwon_candidate_optimized_metrics.json"
    output.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
