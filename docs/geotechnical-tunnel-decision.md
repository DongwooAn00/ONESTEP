# Geotechnical Tunnel Decision MVP

## Overview

The previous MVP classified tunnel candidates mainly from DEM slope and local relief. The updated flow keeps that fallback, but adds an explainable decision layer based on overburden, estimated_rock_class, road_grade, and surface-versus-tunnel cost comparison.

This is an MVP-level estimated rock class workflow. 본 암반등급은 수치지질도, DEM, 단층거리, 지질경계거리를 이용한 MVP용 개략 추정값이다. 정밀 설계 단계에서는 시추조사, RQD, 절리 간격, 절리 상태, 지하수 조건, 현장 지질조사 결과를 반영해야 한다.

## Geology Inputs

GeoPandas can read the 1:250K geology layers below:

```python
litho_gdf = gpd.read_file("Geology_250K_Litho.shp")
fault_gdf = gpd.read_file("Geology_250K_Fault.shp")
boundary_gdf = gpd.read_file("Geology_250K_Boudary.shp")
```

All route, DEM, and geology geometry should be transformed to a meter CRS before distance checks. The default target CRS is `EPSG:5179`.

## Overburden

Overburden is calculated from DEM surface elevation and the planned tunnel profile:

```text
overburden_m = surface_elev_m - tunnel_elev_m
```

The planned tunnel elevation is linearly interpolated from segment start profile elevation to segment end profile elevation. Negative overburden is not clamped; it is reported with `negative_overburden_check_dem_or_profile`.

## Estimated Rock Class

The lithology layer is searched for these columns in order:

```text
refrock, ROCK, rock, lithology, LITHO, lithoname
```

Rock names are matched by substring. For example, `흑운모화강암` matches `화강암` and starts from class `II`. Unknown rock names default to class `III` and add `unknown_refrock_default_class_III`.

Distance adjustments:

```text
fault <= 50m: +2 classes
fault <= 200m: +1 class
boundary <= 30m: +1 class
boundary <= 100m: +0.5 class
```

Overburden and slope adjustments:

```text
overburden < 10m: +1 class
overburden > 200m: +1 class
slope >= 35deg: +1 class
slope >= 25deg: +0.5 class
```

The final estimated class is `ceil(base_class + adjustment)`, clamped to `I` through `V`.

## Ground Factors

```text
I: ground_factor 0.75, constructability good
II: ground_factor 0.90, constructability good
III: ground_factor 1.10, constructability normal
IV: ground_factor 1.50, constructability poor
V: ground_factor 2.50, constructability very_poor
unknown: ground_factor 1.30, constructability unknown
```

Legacy ground classes are normalized: `good_rock -> II`, `fair_rock -> III`, `poor_rock -> IV`, and `very_poor_rock -> V`.

## Tunnel Score

```text
tunnel_score = grade_score + overburden_score + rock_score + relief_score - penalty_score
```

Overburden scoring:

```text
None: 0, unknown
< 20m: -40, low_cover
< 50m: 10, shallow_tunnel
>= 50m: 25, normal_tunnel
```

Decision thresholds:

```text
river_crossing: bridge first
score >= 60: tunnel_preferred
30 <= score < 60: tunnel_candidate, compare tunnel cost and surface road cost
score < 30: surface_preferred
```

For candidate ranges, tunnel is allowed when `tunnel_cost <= surface_cost * 1.10`. Low overburden keeps `low_overburden_cut_and_cover_or_surface_preferred` instead of confirming a normal NATM tunnel. Protected-area direct conflicts are flagged as `avoid_or_reroute`.

## Fallback

Fallback order:

```text
1. river_crossing=True -> bridge
2. overburden_m and estimated_rock_class available -> new scoring logic
3. one of them available -> partial scoring with unknown defaults
4. neither available -> existing slope/local relief tunnel fallback
5. protected_area direct conflict -> avoid_or_reroute or existing avoidance cost
```

## JSON Fields

`candidate_route_segments.json` now includes additional explanation fields such as:

```text
original_segment_type, final_segment_type, decision_status, feasibility_flag,
tunnel_score, overburden_m, overburden_condition, estimated_rock_class,
rock_class, rock_ground_factor, rock_constructability, road_grade_percent,
slope_deg, local_relief_m, fault_dist_m, boundary_dist_m,
estimated_surface_cost_eok, estimated_tunnel_cost_eok, decision_reason,
risk_reasons
```

`ranked_candidate_routes.json` summary now includes tunnel totals, counts, length by rock class, high-risk tunnel length, low-overburden tunnel length, very-poor-rock tunnel length, average tunnel score, and maximum ground factor.
