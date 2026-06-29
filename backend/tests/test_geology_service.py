from dataclasses import dataclass

import pytest

from app.services.geology_service import GeologyDatasets, sample_route_geology


@dataclass(frozen=True)
class Point:
    x: float
    y: float


def test_route_geology_sampling_uses_20m_interval_and_keeps_endpoints():
    samples = sample_route_geology(
        [Point(0.0, 0.0), Point(45.0, 0.0)],
        start_profile_elev_m=100.0,
        end_profile_elev_m=100.0,
        datasets=GeologyDatasets(None, None, None),
        dem_elevation_lookup=lambda x, y: 110.0,
        sample_interval_m=20.0,
    )

    assert [sample["station_m"] for sample in samples] == [0.0, 20.0, 40.0, 45.0]
    assert all(sample["overburden_m"] == 10.0 for sample in samples)
    assert all(sample["estimated_rock_class"] == "unknown" for sample in samples)
    assert all(sample["rock_ground_factor"] == 1.3 for sample in samples)


def test_negative_overburden_is_not_clamped():
    samples = sample_route_geology(
        [Point(0.0, 0.0), Point(20.0, 0.0)],
        start_profile_elev_m=100.0,
        end_profile_elev_m=100.0,
        datasets=GeologyDatasets(None, None, None),
        dem_elevation_lookup=lambda x, y: 90.0,
        sample_interval_m=20.0,
    )

    assert samples[0]["overburden_m"] == -10.0
    assert "negative_overburden_check_dem_or_profile" in samples[0]["risk_reasons"]


def test_non_positive_interval_is_safely_normalized():
    samples = sample_route_geology(
        [Point(0.0, 0.0), Point(1.0, 0.0)],
        start_profile_elev_m=0.0,
        end_profile_elev_m=0.0,
        datasets=GeologyDatasets(None, None, None),
        dem_elevation_lookup=lambda x, y: 0.0,
        sample_interval_m=0.0,
    )

    assert samples[-1]["station_m"] == pytest.approx(1.0)
