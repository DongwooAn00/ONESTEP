from __future__ import annotations

from app.schemas.route_reports import (
    CandidateRouteReportsRequest,
    CandidateRouteReportsResult,
)
from app.services.report_data_builder import build_route_report_data
from app.services.report_generator import BaseReportGenerator, TemplateReportGenerator


def generate_candidate_route_reports(
    payload: CandidateRouteReportsRequest,
    *,
    generator: BaseReportGenerator | None = None,
) -> CandidateRouteReportsResult:
    active_generator = generator or TemplateReportGenerator()
    requested_ids = set(payload.route_ids or [])
    route_by_id = {
        str(route.get("route_id")): route
        for route in payload.routes
        if route.get("route_id") is not None
    }
    if requested_ids:
        missing = requested_ids - set(route_by_id)
        if missing:
            raise ValueError(f"보고서 대상 후보 노선을 찾을 수 없습니다: {', '.join(sorted(missing))}")
        route_ids = [
            str(route.get("route_id"))
            for route in payload.routes
            if str(route.get("route_id")) in requested_ids
        ]
    else:
        route_ids = list(route_by_id)

    segments_by_route: dict[str, list[dict]] = {}
    for segment in payload.segments:
        segments_by_route.setdefault(str(segment.get("route_id")), []).append(segment)
    cost_by_route = {
        str(cost.get("route_id")): cost
        for cost in payload.costs
        if cost.get("route_id") is not None
    }
    ranked_by_route = {
        str(route.get("route_id")): route
        for route in payload.ranked_routes
        if route.get("route_id") is not None
    }

    reports = [
        active_generator.generate(
            build_route_report_data(
                route_by_id[route_id],
                segments=segments_by_route.get(route_id, []),
                cost=cost_by_route.get(route_id),
                ranked_route=ranked_by_route.get(route_id),
            )
        )
        for route_id in route_ids
    ]
    return CandidateRouteReportsResult(
        reports=reports,
        report_count=len(reports),
        generator=getattr(active_generator, "generator_name", active_generator.__class__.__name__),
    )
