from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

from app.services.geotechnical_model import get_rock_class_factor, get_rock_constructability

# 본 암반등급은 수치지질도, DEM, 단층거리, 지질경계거리를 이용한 MVP용 개략 추정값이다.
# 정밀 설계 단계에서는 시추조사, RQD, 절리 간격, 절리 상태, 지하수 조건, 현장 지질조사 결과를 반영해야 한다.

ROCK_BASE_CLASS = {
    "화강암": 2,
    "화강섬록암": 2,
    "섬록암": 2,
    "반려암": 2,
    "규암": 2,
    "편마암": 2,
    "석회암": 3,
    "대리암": 3,
    "사암": 3,
    "역암": 3,
    "안산암": 3,
    "유문암": 3,
    "현무암": 3,
    "셰일": 4,
    "이암": 4,
    "실트암": 4,
    "응회암": 4,
    "편암": 4,
    "천매암": 4,
    "슬레이트": 4,
    "충적층": 5,
    "모래": 5,
    "자갈": 5,
    "점토": 5,
    "흙": 5,
}

CLASS_LABEL = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}


@dataclass
class EstimatedRockClass:
    estimated_rock_class: str
    estimated_rock_class_num: int
    rock_ground_factor: float
    rock_constructability: str
    risk_reasons: list[str] = field(default_factory=list)


def estimate_base_class_from_refrock(refrock: object | None) -> tuple[int, list[str]]:
    risk_reasons: list[str] = []
    text = str(refrock or "")
    for token, class_num in ROCK_BASE_CLASS.items():
        if token in text:
            return class_num, risk_reasons
    risk_reasons.append("unknown_refrock_default_class_III")
    return 3, risk_reasons


def estimate_rock_class(
    *,
    refrock: object | None = None,
    overburden_m: float | None = None,
    slope_deg: float | None = None,
    fault_dist_m: float | None = None,
    boundary_dist_m: float | None = None,
) -> EstimatedRockClass:
    base_class, risk_reasons = estimate_base_class_from_refrock(refrock)
    class_adjust = 0.0

    if fault_dist_m is not None:
        if fault_dist_m <= 50:
            class_adjust += 2
            risk_reasons.append("fault_within_50m")
        elif fault_dist_m <= 200:
            class_adjust += 1
            risk_reasons.append("fault_within_200m")

    if boundary_dist_m is not None:
        if boundary_dist_m <= 30:
            class_adjust += 1
            risk_reasons.append("geologic_boundary_within_30m")
        elif boundary_dist_m <= 100:
            class_adjust += 0.5
            risk_reasons.append("geologic_boundary_within_100m")

    if overburden_m is None:
        risk_reasons.append("unknown_overburden")
    elif overburden_m < 0:
        risk_reasons.append("negative_overburden_check_dem_or_profile")
    elif overburden_m < 10:
        class_adjust += 1
        risk_reasons.append("very_low_overburden_under_10m")
    elif overburden_m > 200:
        class_adjust += 1
        risk_reasons.append("high_overburden_over_200m")

    if slope_deg is not None:
        if slope_deg >= 35:
            class_adjust += 1
            risk_reasons.append("steep_slope_over_35deg")
        elif slope_deg >= 25:
            class_adjust += 0.5
            risk_reasons.append("moderate_slope_over_25deg")

    class_num = min(5, max(1, ceil(base_class + class_adjust)))
    label = CLASS_LABEL[class_num]
    return EstimatedRockClass(
        estimated_rock_class=label,
        estimated_rock_class_num=class_num,
        rock_ground_factor=get_rock_class_factor(label),
        rock_constructability=get_rock_constructability(label),
        risk_reasons=risk_reasons,
    )
