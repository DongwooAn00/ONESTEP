from __future__ import annotations

from app.services import route_mvp_config as config


def _min_max(values: list[float]) -> list[float]:
    if not values:
        return []
    minimum = min(values)
    maximum = max(values)
    if maximum == minimum:
        return [50.0 for _ in values]
    return [((value - minimum) / (maximum - minimum)) * 100.0 for value in values]


def _assumed_existing_route_length_km(
    *,
    straight_distance_km: float,
    detour_factor_assumption: float = config.DETOUR_FACTOR_ASSUMPTION,
) -> float:
    return straight_distance_km * detour_factor_assumption


def calculate_distance_saving_km(
    *,
    straight_distance_km: float,
    new_route_length_km: float,
    existing_route_length_km: float | None = None,
    detour_factor_assumption: float = config.DETOUR_FACTOR_ASSUMPTION,
) -> float:
    if existing_route_length_km is not None:
        return max(0.0, existing_route_length_km - new_route_length_km)
    assumed_existing = _assumed_existing_route_length_km(
        straight_distance_km=straight_distance_km,
        detour_factor_assumption=detour_factor_assumption,
    )
    return max(0.0, assumed_existing - new_route_length_km)


def _tunnel_risk_summary(row: dict) -> dict:
    segments = row.get("segment_details", [])
    tunnel_segments = [
        segment for segment in segments if segment.get("final_segment_type") == "tunnel" or segment.get("segment_type") == "tunnel"
    ]
    tunnel_length_by_rock_class = {"II": 0.0, "III": 0.0, "IV": 0.0, "V": 0.0, "unknown": 0.0}
    high_risk_tunnel_length_m = 0.0
    low_overburden_tunnel_length_m = 0.0
    very_poor_rock_tunnel_length_m = 0.0
    scores = []
    ground_factors = []

    for segment in tunnel_segments:
        length_m = float(segment.get("segment_length_km") or 0.0) * 1000.0
        rock_class = segment.get("rock_class") or segment.get("estimated_rock_class") or "unknown"
        if rock_class not in tunnel_length_by_rock_class:
            rock_class = "unknown"
        tunnel_length_by_rock_class[rock_class] += length_m
        if rock_class in {"IV", "V"}:
            high_risk_tunnel_length_m += length_m
        if segment.get("overburden_condition") == "low_cover":
            low_overburden_tunnel_length_m += length_m
        if rock_class == "V":
            very_poor_rock_tunnel_length_m += length_m
        if segment.get("tunnel_score") is not None:
            scores.append(float(segment["tunnel_score"]))
        if segment.get("rock_ground_factor") is not None:
            ground_factors.append(float(segment["rock_ground_factor"]))

    return {
        "total_tunnel_length_m": round(float(row.get("tunnel_length_km", 0.0)) * 1000.0, 1),
        "tunnel_count": int(row.get("tunnel_segment_count", len(tunnel_segments))),
        "bridge_count": int(row.get("bridge_segment_count", 0)),
        "surface_road_length_m": round(float(row.get("surface_road_length_km", 0.0)) * 1000.0, 1),
        "tunnel_length_by_rock_class": {
            key: round(value, 1) for key, value in tunnel_length_by_rock_class.items()
        },
        "high_risk_tunnel_length_m": round(high_risk_tunnel_length_m, 1),
        "low_overburden_tunnel_length_m": round(low_overburden_tunnel_length_m, 1),
        "very_poor_rock_tunnel_length_m": round(very_poor_rock_tunnel_length_m, 1),
        "avg_tunnel_score": round(sum(scores) / len(scores), 2) if scores else None,
        "max_rock_ground_factor": round(max(ground_factors), 2) if ground_factors else None,
    }


def rank_candidate_routes(route_rows: list[dict]) -> list[dict]:
    successful = [row for row in route_rows if row["status"] == "success"]
    benefit_values = [
        row["estimated_flow"] * row["distance_saving_km"]
        for row in successful
    ]
    cost_values = [row["total_screen_cost"] for row in successful]
    benefit_scores = _min_max(benefit_values)
    cost_penalties = _min_max(cost_values)
    raw_scores = [benefit - cost for benefit, cost in zip(benefit_scores, cost_penalties)]
    normalized_scores = _min_max(raw_scores)

    by_route_id = {
        row["route_id"]: round(score, 2)
        for row, score in zip(successful, normalized_scores)
    }
    ranked = []
    for row in route_rows:
        score = by_route_id.get(row["route_id"], 0.0)
        tunnel_summary = _tunnel_risk_summary(row)
        assumed_existing_length = _assumed_existing_route_length_km(
            straight_distance_km=row.get("straight_distance_km", 0.0),
        )
        benefit_proxy = row["estimated_flow"] * row["distance_saving_km"]
        cost_per_flow_saving = row["total_screen_cost"] / benefit_proxy if benefit_proxy > 0 else None
        ranked.append(
            {
                "rank": 0,
                "route_id": row["route_id"],
                "from_node_id": row["from_node_id"],
                "to_node_id": row["to_node_id"],
                "estimated_flow": row["estimated_flow"],
                "distance_saving_km": round(row["distance_saving_km"], 3),
                "total_screen_cost": round(row["total_screen_cost"], 3),
                "economic_score": score,
                **tunnel_summary,
                "summary": {
                    "label": "MVP 예비 경제성 점수",
                    "status": row["status"],
                    "straight_distance_km": row.get("straight_distance_km", 0.0),
                    "assumed_existing_route_length_km": round(assumed_existing_length, 3),
                    "route_length_km": row["route_length_km"],
                    "distance_saving_km": round(row["distance_saving_km"], 3),
                    "benefit_proxy": round(benefit_proxy, 3),
                    "cost_per_flow_saving": round(cost_per_flow_saving, 6) if cost_per_flow_saving is not None else None,
                    "surface_road_length_km": row["surface_road_length_km"],
                    "existing_road_length_km": row.get("existing_road_length_km", 0.0),
                    "existing_tunnel_length_km": row.get("existing_tunnel_length_km", 0.0),
                    "new_surface_road_length_km": row.get("new_surface_road_length_km", row["surface_road_length_km"]),
                    "tunnel_length_km": row["tunnel_length_km"],
                    "bridge_length_km": row["bridge_length_km"],
                    "existing_road_access_length_km": row.get("existing_road_access_length_km", 0.0),
                    "existing_road_access_percent": row.get("existing_road_access_percent", 0.0),
                    "route_generation_method": row.get("route_generation_method", "unknown"),
                    "river_crossing_count": row.get("river_crossing_count", 0),
                    "failed_reason": row.get("failed_reason"),
                    **tunnel_summary,
                },
            }
        )

    ranked.sort(key=lambda item: (item["economic_score"], item["estimated_flow"]), reverse=True)
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked
