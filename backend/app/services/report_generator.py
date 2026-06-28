from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict

from app.schemas.route_reports import RouteReport, RouteReportMetrics
from app.services.report_data_builder import RouteReportData


def _value(value: float | None, suffix: str = "", digits: int = 2) -> str:
    if value is None:
        return "현재 산정 불가"
    return f"{value:,.{digits}f}{suffix}"


class BaseReportGenerator(ABC):
    @abstractmethod
    def generate(self, report_data: RouteReportData) -> RouteReport:
        raise NotImplementedError


class TemplateReportGenerator(BaseReportGenerator):
    generator_name = "template"

    def generate(self, report_data: RouteReportData) -> RouteReport:
        data = report_data
        endpoints = (
            f"{data.from_node_id}–{data.to_node_id}"
            if data.from_node_id and data.to_node_id
            else "출발지–도착지 정보 보완 필요"
        )
        title = f"후보 노선 {data.route_id} 예비 검토 보고서"
        tunnel_text = (
            f"터널 구간 {_value(data.tunnel_length_km, 'km')}가 포함되었습니다."
            if data.has_tunnel
            else "현재 산정 결과에서는 터널 구간이 확인되지 않았습니다."
        )
        existing_text = (
            f"기존 도로 {_value(data.existing_road_length_km, 'km')}를 접속·보조 구간으로 활용합니다."
            if data.uses_existing_road
            else "기존 도로 활용 구간 없이 신규 선형 중심으로 구성되었습니다."
        )
        summary = (
            f"본 후보 노선은 {endpoints} 구간의 예비 대안으로, 총 연장 "
            f"{_value(data.total_length_km, 'km')}로 산정되었습니다. 일반 도로 구간은 "
            f"{_value(data.road_length_km, 'km')}, 터널 구간은 "
            f"{_value(data.tunnel_length_km, 'km')}입니다. 총사업비는 MVP 기준 "
            f"{_value(data.total_project_cost, '억원')}이며, 경제성 검토용 B/C는 "
            f"{_value(data.benefit_cost_ratio, '', 2)}입니다."
        )
        route_overview = (
            f"노선 유형은 {data.route_type}이며 총 연장은 {_value(data.total_length_km, 'km')}입니다. "
            f"신규 일반도로 {_value(data.new_road_length_km, 'km')}, 접속도로 "
            f"{_value(data.connector_length_km, 'km')}, 기존 도로 "
            f"{_value(data.existing_road_length_km, 'km')}로 구성됩니다. {tunnel_text}"
        )
        cost_analysis = (
            f"예상 도로 건설비는 {_value(data.road_construction_cost, '억원')}, 터널 건설비는 "
            f"{_value(data.tunnel_construction_cost, '억원')}, 토지 보상비는 "
            f"{_value(data.land_compensation_cost, '억원')}입니다. 연간 유지관리비는 공사비 기반 "
            f"MVP 단순 추정으로 {_value(data.annual_maintenance_cost, '억원/년')}이며, 30년 현재가치 "
            f"유지관리비 {_value(data.maintenance_cost, '억원')}를 포함한 총사업비는 "
            f"{_value(data.total_project_cost, '억원')}입니다."
        )
        benefit_analysis = (
            f"예상 연간 편익은 {_value(data.annual_benefit, '억원/년')}, 분석기간 총편익은 "
            f"{_value(data.total_benefit, '억원')}입니다. 기존 도로 기준안 대비 거리 단축은 "
            f"{_value(data.distance_saving_km, 'km')}, 시간 단축은 "
            f"{_value(data.time_saving_minutes, '분')}이며, B/C {_value(data.benefit_cost_ratio, '', 2)}, "
            f"순현재가치 또는 순편익은 {_value(data.net_present_value, '억원')}, 후보 점수는 "
            f"{_value(data.economic_score, '점', 1)}입니다."
        )
        technical_review = (
            f"DEM 기반 1차 경사도 분석에서 평균 경사도는 {_value(data.average_slope, '°')}, "
            f"최대 경사도는 {_value(data.max_slope, '°')}로 집계되었습니다. {tunnel_text} "
            f"{existing_text} 신규 도로 구간 여부와 터널 분류는 예비 비용격자 및 지형 판단 결과이며 "
            f"선형·지질·종단계획의 추후 정밀 검토가 필요합니다."
        )
        if data.source_explanations:
            technical_review += " 주요 산정 근거: " + " ".join(data.source_explanations)

        advantages = []
        if (data.distance_saving_km or 0.0) > 0:
            advantages.append(f"기존 기준안 대비 약 {data.distance_saving_km:.2f}km의 거리 단축 가능성")
        if (data.time_saving_minutes or 0.0) > 0:
            advantages.append(f"약 {data.time_saving_minutes:.2f}분의 통행시간 단축 가능성")
        if (data.benefit_cost_ratio or 0.0) >= 1.0:
            advantages.append("MVP 경제성 검토에서 B/C 1.0 이상")
        if data.uses_existing_road:
            advantages.append("기존 도로를 접속·보조 구간으로 활용")
        if not advantages:
            advantages.append("복수 후보 비교를 위한 DEM 기반 신규 선형 대안 제공")

        limitations = [
            "본 결과는 DEM 및 현재 적재 데이터에 기반한 예비 산정으로 최종 설계값이 아닙니다.",
            "유지관리비는 도로·터널 공사비 비율을 적용한 MVP 단순 추정값입니다.",
        ]
        if data.land_compensation_cost is None or data.land_compensation_cost == 0:
            limitations.append("토지 보상비는 필지·공시지가 데이터 보완 후 재검토가 필요합니다.")
        if data.crossing_review_required:
            limitations.append("하천·계곡 통과 가능 구간은 MVP에서 교량을 반영하지 않아 추가 검토가 필요합니다.")
        if data.unsupported_bridge_count:
            limitations.append(
                f"입력된 교량 segment {data.unsupported_bridge_count}건은 MVP 비용·연장 계산에서 제외했습니다."
            )
        limitations.extend(data.warnings)
        limitations = list(dict.fromkeys(limitations))
        risk_review = " ".join(limitations)

        if data.benefit_cost_ratio is None:
            final_opinion = (
                "현재 B/C 산정 자료가 부족하므로 경제성 결론을 유보합니다. 비용·편익 자료를 보완한 뒤 "
                "후보 간 비교 검토가 필요합니다."
            )
        elif data.benefit_cost_ratio >= 1.0:
            final_opinion = (
                "MVP 기준으로 경제성 검토 가능성이 확인되지만 확정 판단은 아닙니다. 지질조사, 상세 선형, "
                "환경·보상비 검토를 보완한 후 우선 검토 후보로 비교할 수 있습니다."
            )
        else:
            final_opinion = (
                "MVP 기준 B/C가 1.0 미만으로 산정되어 현 조건에서는 비용 부담이 상대적으로 큽니다. "
                "노선 단축, 터널 규모 조정 및 수요·편익 재검토가 필요합니다."
            )

        metrics = RouteReportMetrics(
            total_length_km=data.total_length_km,
            road_length_km=data.road_length_km,
            existing_road_length_km=data.existing_road_length_km,
            connector_length_km=data.connector_length_km,
            new_road_length_km=data.new_road_length_km,
            tunnel_length_km=data.tunnel_length_km,
            road_construction_cost=data.road_construction_cost,
            tunnel_construction_cost=data.tunnel_construction_cost,
            land_compensation_cost=data.land_compensation_cost,
            annual_maintenance_cost=data.annual_maintenance_cost,
            maintenance_cost=data.maintenance_cost,
            construction_cost=data.construction_cost,
            total_project_cost=data.total_project_cost,
            annual_benefit=data.annual_benefit,
            benefit=data.total_benefit,
            benefit_cost_ratio=data.benefit_cost_ratio,
            net_present_value=data.net_present_value,
            economic_score=data.economic_score,
            distance_saving_km=data.distance_saving_km,
            time_saving_minutes=data.time_saving_minutes,
            average_slope=data.average_slope,
            max_slope=data.max_slope,
        )
        markdown = self._markdown(
            title=title,
            summary=summary,
            route_overview=route_overview,
            cost_analysis=cost_analysis,
            benefit_analysis=benefit_analysis,
            technical_review=technical_review,
            risk_review=risk_review,
            final_opinion=final_opinion,
            advantages=advantages,
            limitations=limitations,
            metrics=metrics,
        )
        return RouteReport(
            route_id=data.route_id,
            title=title,
            summary=summary,
            route_overview=route_overview,
            cost_analysis=cost_analysis,
            benefit_analysis=benefit_analysis,
            technical_review=technical_review,
            risk_review=risk_review,
            final_opinion=final_opinion,
            advantages=advantages,
            limitations=limitations,
            warnings=data.warnings,
            metrics=metrics,
            markdown=markdown,
            generator=self.generator_name,
        )

    @staticmethod
    def _markdown(**sections) -> str:
        metrics = sections["metrics"]
        metric_rows = "\n".join(
            f"| {label} | {value} |"
            for label, value in (
                ("총 연장", _value(metrics.total_length_km, "km")),
                ("일반 도로", _value(metrics.road_length_km, "km")),
                ("터널", _value(metrics.tunnel_length_km, "km")),
                ("총사업비", _value(metrics.total_project_cost, "억원")),
                ("총편익", _value(metrics.benefit, "억원")),
                ("B/C", _value(metrics.benefit_cost_ratio)),
                ("경제성 점수", _value(metrics.economic_score, "점", 1)),
            )
        )
        advantages = "\n".join(f"- {item}" for item in sections["advantages"])
        limitations = "\n".join(f"- {item}" for item in sections["limitations"])
        return (
            f"# {sections['title']}\n\n"
            f"> {sections['summary']}\n\n"
            "## 1. 노선 개요\n\n"
            f"{sections['route_overview']}\n\n"
            "## 2. 비용 분석\n\n"
            f"{sections['cost_analysis']}\n\n"
            "## 3. 편익 분석\n\n"
            f"{sections['benefit_analysis']}\n\n"
            "## 4. 기술적 검토\n\n"
            f"{sections['technical_review']}\n\n"
            "### 주요 장점\n\n"
            f"{advantages}\n\n"
            "## 5. 위험요소 및 한계\n\n"
            f"{limitations}\n\n"
            "## 6. 종합 검토 의견\n\n"
            f"{sections['final_opinion']}\n\n"
            "## 주요 지표\n\n"
            "| 항목 | 예비 산정값 |\n|---|---:|\n"
            f"{metric_rows}\n\n"
            "_본 문서는 Gemini API를 사용하지 않은 템플릿 기반 예비 검토 보고서입니다._\n"
        )
