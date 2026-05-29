# Route Contract

이 문서는 후보 노선 생성 모듈과 DEM 평가 모듈 사이의 입력/출력 규약을 정의한다.

## 목적

- 후보 노선 생성 알고리즘은 언제든 교체할 수 있다.
- 평가와 비용 산정 로직은 고정된 데이터 형식만 받는다.
- 프론트엔드와 백엔드는 API 응답 형식이 바뀌지 않도록 이 문서를 기준으로 맞춘다.

## 공통 규칙

- 좌표는 WGS84 위도/경도 기준이다.
- `lat`는 위도, `lon`은 경도다.
- 후보 노선은 좌표 배열로 표현한다.
- 경사도와 비용 산정에 필요한 단가/계수는 요청에 포함하거나 서버 기본값을 사용한다.

## `/api/generate-route`

후보 노선 생성 전용 API다. 후보 생성만 하고 평가는 하지 않는다.

### Request

```json
{
  "start_lat": 37.5665,
  "start_lon": 126.9780,
  "end_lat": 37.6542,
  "end_lon": 127.0568,
  "candidate_count": 3,
  "sample_interval_m": 90,
  "rock_factor": 1.15,
  "road_unit_cost_billion_krw_per_km": 12,
  "tunnel_unit_cost_billion_krw_per_km": 80,
  "steep_road_factor": 1.3
}
```

### Response

```json
{
  "candidates": [
    {
      "name": "straight",
      "coordinates": [
        { "lat": 37.5665, "lon": 126.9780 },
        { "lat": 37.6542, "lon": 127.0568 }
      ]
    }
  ]
}
```

## `/api/evaluate-route`

후보 노선 평가 전용 API다. 좌표 배열을 받아 DEM 고도 분석, 경사도 계산, 터널 판정, 비용 산정을 수행한다.

### Request

```json
{
  "name": "candidate_a",
  "coordinates": [
    { "lat": 37.5665, "lon": 126.9780 },
    { "lat": 37.61, "lon": 127.02 },
    { "lat": 37.6542, "lon": 127.0568 }
  ],
  "sample_interval_m": 90,
  "rock_factor": 1.15,
  "road_unit_cost_billion_krw_per_km": 12,
  "tunnel_unit_cost_billion_krw_per_km": 80,
  "steep_road_factor": 1.3
}
```

### Response

```json
{
  "candidate": {
    "name": "candidate_a",
    "total_length_m": 1234.5,
    "road_length_m": 800.0,
    "steep_road_length_m": 200.0,
    "tunnel_length_m": 234.5,
    "max_slope_percent": 18.2,
    "min_elevation_m": 12.3,
    "max_elevation_m": 98.4,
    "estimated_cost_billion_krw": 154.6,
    "segments": [],
    "coordinates": []
  }
}
```

## `/api/route-cost`

임시 MVP API다. 출발지/도착지 기반으로 서버가 후보 노선을 간단히 생성한 뒤 평가한다.

## 변경 금지 항목

- 좌표 키 이름은 `lat`, `lon`을 유지한다.
- 평가 결과의 핵심 필드명은 유지한다.
- 후보 노선은 반드시 좌표 배열로 전달한다.

## 변경 가능 항목

- 후보 노선 생성 알고리즘 내부 로직
- 후보 개수 기본값
- 샘플 간격 기본값
- 단가와 계수의 기본값
- 터널 판정 임계값
