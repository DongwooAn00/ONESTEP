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


def calculate_distance_saving_km(
    *,
    straight_distance_km: float,
    new_route_length_km: float,
    existing_route_length_km: float | None = None,
    detour_factor_assumption: float = config.DETOUR_FACTOR_ASSUMPTION,
) -> float:
    if existing_route_length_km is not None:
        return max(0.0, existing_route_length_km - new_route_length_km)
    assumed_existing = straight_distance_km * detour_factor_assumption
    return max(0.0, assumed_existing - new_route_length_km)


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
                "summary": {
                    "label": "MVP 예비 경제성 점수",
                    "status": row["status"],
                    "route_length_km": row["route_length_km"],
                    "surface_road_length_km": row["surface_road_length_km"],
                    "tunnel_length_km": row["tunnel_length_km"],
                    "bridge_length_km": row["bridge_length_km"],
                    "failed_reason": row.get("failed_reason"),
                },
            }
        )

    ranked.sort(key=lambda item: (item["economic_score"], item["estimated_flow"]), reverse=True)
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked
