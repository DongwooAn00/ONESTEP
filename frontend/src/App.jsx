import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  BarChart3,
  Bell,
  BookOpen,
  Building2,
  Download,
  FileText,
  FileUp,
  Heart,
  ListPlus,
  MapPin,
  Megaphone,
  MessageSquareText,
  MousePointer2,
  Network,
  Play,
  Plus,
  RotateCcw,
  Save,
  Search,
  Trophy,
  X
} from "lucide-react";

const KAKAO_MAP_JS_KEY = import.meta.env.VITE_KAKAO_MAP_JS_KEY;
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const DEFAULT_CENTER = { lat: 36.35, lng: 127.85 };
const DEFAULT_MAP_LEVEL = 11;
const REGION_OPTIONS = [
  "서울특별시",
  "부산광역시",
  "대구광역시",
  "인천광역시",
  "광주광역시",
  "대전광역시",
  "울산광역시",
  "세종특별자치시",
  "경기도",
  "강원특별자치도",
  "충청북도",
  "충청남도",
  "전북특별자치도",
  "전라남도",
  "경상북도",
  "경상남도",
  "제주특별자치도"
];

let kakaoMapSdkPromise;

function loadKakaoMapSdk() {
  if (window.kakao?.maps) {
    return Promise.resolve(window.kakao);
  }

  if (!KAKAO_MAP_JS_KEY || KAKAO_MAP_JS_KEY.includes("replace_with")) {
    return Promise.reject(new Error("카카오맵 JavaScript 키가 설정되지 않았습니다."));
  }

  if (!kakaoMapSdkPromise) {
    kakaoMapSdkPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${KAKAO_MAP_JS_KEY}&autoload=false&libraries=services`;
      script.async = true;
      script.onload = () => {
        window.kakao.maps.load(() => resolve(window.kakao));
      };
      script.onerror = () => reject(new Error("카카오맵 SDK를 불러오지 못했습니다."));
      document.head.appendChild(script);
    });
  }

  return kakaoMapSdkPromise;
}

const sampleScenarios = [
  {
    id: "scenario-default",
    name: "기존 OD 데이터 시나리오",
    source: "기본 제공",
    createdAt: "2026-06-08",
    ods: [
      {
        id: "od-default-1",
        name: "세종-대전 물류축",
        start: { lat: 36.4801, lng: 127.289, label: "세종시청" },
        end: { lat: 36.3504, lng: 127.3845, label: "대전역" },
        freight: 3500000,
        traffic: 18500
      },
      {
        id: "od-default-2",
        name: "청주-천안 산업축",
        start: { lat: 36.6424, lng: 127.489, label: "청주산단" },
        end: { lat: 36.8151, lng: 127.1139, label: "천안역" },
        freight: 2140000,
        traffic: 12600
      }
    ]
  }
];

const candidateTemplates = [
  {
    id: 1,
    name: "후보 1",
    kind: "기존 도로 개선",
    score: 86.7,
    time: "34분",
    cost: "2,350억원",
    type: "도로",
    color: "#0b7ff3",
    description: "기존 도로망을 활용해 공사비를 낮추고 단기 실행 가능성을 높인 대안입니다."
  },
  {
    id: 2,
    name: "후보 2",
    kind: "터널 신설",
    score: 72.1,
    time: "41분",
    cost: "4,980억원",
    type: "터널",
    color: "#7f57d9",
    description: "직선화된 터널 구간으로 시간 단축 효과는 크지만 초기 공사비가 높은 대안입니다."
  },
  {
    id: 3,
    name: "후보 3",
    kind: "우회 도로",
    score: 61.3,
    time: "22분",
    cost: "1,820억원",
    type: "도로",
    color: "#14a8b5",
    description: "교통량 분산과 비용 절감에 초점을 둔 보완형 대안입니다."
  }
];

const announcementPosts = [
  {
    id: "notice-1",
    type: "정부",
    title: "2026 광역교통망 개선사업 사전 수요조사",
    body: "국토교통부 주관 광역 교통 인프라 개선 수요조사가 진행 중입니다.",
    date: "2026-06-08"
  },
  {
    id: "notice-2",
    type: "기업",
    title: "스마트 물류 거점 공동 실증 파트너 모집",
    body: "민간 물류기업과 지자체가 함께 참여하는 OD 데이터 기반 실증 공고입니다.",
    date: "2026-06-05"
  }
];

const initialCommunityPosts = [
  {
    id: "post-1",
    title: "세종-대전 구간은 출퇴근 수요도 함께 봐야 합니다",
    body: "물동량만 보면 낮아 보이지만 첨두시간 교통량까지 반영하면 우선순위가 달라질 수 있습니다.",
    author: "교통분석가",
    likes: 24,
    createdAt: "2026-06-08"
  },
  {
    id: "post-2",
    title: "터널 후보지는 유지관리 비용 항목이 필요해 보여요",
    body: "초기 공사비 외에도 환기, 방재, 유지관리 지표가 비교표에 들어가면 좋겠습니다.",
    author: "인프라PM",
    likes: 12,
    createdAt: "2026-06-07"
  }
];

function formatNumber(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number.toLocaleString() : "0";
}

function formatMoneyEok(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? `${number.toLocaleString(undefined, { maximumFractionDigits: 1 })} 억원` : "0 억원";
}

function downloadJson(filename, payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function downloadText(filename, content, type = "text/markdown;charset=utf-8") {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function buildScenarioOdCsv(scenarios) {
  const headers = [
    "od_name",
    "origin_latitude",
    "origin_longitude",
    "destination_latitude",
    "destination_longitude",
    "passenger_car",
    "freight",
  ];
  const rows = scenarios.flatMap((scenario) =>
    (scenario?.ods || [])
      .filter((od) => od.start && od.end)
      .map((od) => [
        `${scenario.name} / ${od.name}`,
        od.start.lat,
        od.start.lng,
        od.end.lat,
        od.end.lng,
        Number(od.traffic || 0),
        Number(od.freight || 0),
      ])
  );

  return [headers, ...rows].map((row) => row.map(csvCell).join(",")).join("\n");
}

function formatPoint(point) {
  if (!point) {
    return "선택 안 됨";
  }

  if (point.label) {
    return point.label;
  }

  return `${point.lat.toFixed(5)}, ${point.lng.toFixed(5)}`;
}

function getStraightDistanceMeters(startPoint, endPoint) {
  if (!startPoint || !endPoint) {
    return null;
  }

  const earthRadiusMeters = 6371000;
  const toRadians = (degrees) => (degrees * Math.PI) / 180;
  const startLat = toRadians(startPoint.lat);
  const endLat = toRadians(endPoint.lat);
  const deltaLat = toRadians(endPoint.lat - startPoint.lat);
  const deltaLng = toRadians(endPoint.lng - startPoint.lng);
  const haversine =
    Math.sin(deltaLat / 2) ** 2 +
    Math.cos(startLat) * Math.cos(endLat) * Math.sin(deltaLng / 2) ** 2;

  return earthRadiusMeters * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));
}

function formatDistance(distanceMeters) {
  if (distanceMeters === null) {
    return "-";
  }

  if (distanceMeters >= 1000) {
    return `${(distanceMeters / 1000).toFixed(2)} km`;
  }

  return `${Math.round(distanceMeters).toLocaleString()} m`;
}

function normalizePoint(rawPoint) {
  if (!rawPoint) {
    return null;
  }

  const lat = Number(rawPoint.lat ?? rawPoint.latitude ?? rawPoint.y);
  const lng = Number(rawPoint.lng ?? rawPoint.longitude ?? rawPoint.x);

  if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
    return null;
  }

  return {
    lat,
    lng,
    label: rawPoint.label || rawPoint.name || `${lat.toFixed(5)}, ${lng.toFixed(5)}`
  };
}

function normalizeScenario(fileName, payload) {
  const data = Array.isArray(payload) ? { name: fileName, ods: payload } : payload;
  const ods = (data.ods || data.odData || data.routes || [])
    .map((od, index) => {
      const start = normalizePoint(od.start || od.origin || od.from);
      const end = normalizePoint(od.end || od.destination || od.to);

      if (!start || !end) {
        return null;
      }

      return {
        id: od.id || `od-imported-${Date.now()}-${index}`,
        name: od.name || od.label || `OD ${index + 1}`,
        start,
        end,
        freight: Number(od.freight ?? od.freightVolume ?? od.cargo ?? 0),
        traffic: Number(od.traffic ?? od.trafficVolume ?? od.volume ?? 0)
      };
    })
    .filter(Boolean);

  if (!ods.length) {
    throw new Error("파일에서 OD 데이터를 찾지 못했습니다.");
  }

  return {
    id: `scenario-imported-${Date.now()}`,
    name: data.name || data.title || fileName,
    source: "파일 가져오기",
    createdAt: new Date().toISOString().slice(0, 10),
    ods
  };
}

function getScenarioTotals(scenario) {
  return scenario.ods.reduce(
    (totals, od) => ({
      freight: totals.freight + Number(od.freight || 0),
      traffic: totals.traffic + Number(od.traffic || 0),
      distance:
        totals.distance +
        Number(getStraightDistanceMeters(od.start, od.end) || 0)
    }),
    { freight: 0, traffic: 0, distance: 0 }
  );
}

function RouteMap({
  routes,
  draftRoute,
  onSelectPoint,
  helperText,
  compact = false,
  candidateNodes = [],
  candidateEdges = [],
  candidateRoutes = [],
  candidateRouteSegments = [],
  focusedCandidate = null
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const clickHandlerRef = useRef(null);
  const onSelectPointRef = useRef(onSelectPoint);
  const markersRef = useRef([]);
  const linesRef = useRef([]);
  const overlaysRef = useRef([]);
  const focusRequestRef = useRef(0);
  const [loadError, setLoadError] = useState("");
  const [renderError, setRenderError] = useState("");
  const [mapReady, setMapReady] = useState(false);

  useEffect(() => {
    onSelectPointRef.current = onSelectPoint;
  }, [onSelectPoint]);

  useEffect(() => {
    let cancelled = false;

    loadKakaoMapSdk()
      .then((kakao) => {
        if (cancelled || !containerRef.current) {
          return;
        }

        const map = new kakao.maps.Map(containerRef.current, {
          center: new kakao.maps.LatLng(DEFAULT_CENTER.lat, DEFAULT_CENTER.lng),
          level: DEFAULT_MAP_LEVEL
        });

        map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);
        map.addControl(new kakao.maps.MapTypeControl(), kakao.maps.ControlPosition.TOPRIGHT);

        const clickHandler = (mouseEvent) => {
          if (!onSelectPointRef.current) {
            return;
          }

          const latLng = mouseEvent.latLng;
          onSelectPointRef.current({ lat: latLng.getLat(), lng: latLng.getLng() });
        };

        kakao.maps.event.addListener(map, "click", clickHandler);
        mapRef.current = map;
        clickHandlerRef.current = clickHandler;
        setMapReady(true);

        window.setTimeout(() => map.relayout(), 80);
      })
      .catch((error) => {
        if (!cancelled) {
          setLoadError(error.message);
        }
      });

    return () => {
      cancelled = true;

      if (window.kakao?.maps && mapRef.current && clickHandlerRef.current) {
        window.kakao.maps.event.removeListener(mapRef.current, "click", clickHandlerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!mapReady || !window.kakao?.maps || !mapRef.current) {
      return;
    }

    const kakao = window.kakao;
    const map = mapRef.current;
    const allRoutes = [...routes, ...(draftRoute ? [draftRoute] : [])];
    const bounds = new kakao.maps.LatLngBounds();
    let hasBounds = false;
    const viewCoordinates = [];

    const toFiniteNumber = (value) => {
      const number = Number(value);
      return Number.isFinite(number) ? number : null;
    };

    const toLatLng = (latValue, lonValue) => {
      const lat = toFiniteNumber(latValue);
      const lon = toFiniteNumber(lonValue);
      if (lat === null || lon === null || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
        return null;
      }
      return new kakao.maps.LatLng(lat, lon);
    };

    const includeInView = (position) => {
      bounds.extend(position);
      viewCoordinates.push({ lat: position.getLat(), lon: position.getLng() });
      hasBounds = true;
    };

    const fitMapToView = () => {
      if (!viewCoordinates.length) {
        map.setCenter(new kakao.maps.LatLng(DEFAULT_CENTER.lat, DEFAULT_CENTER.lng));
        map.setLevel(DEFAULT_MAP_LEVEL);
        return;
      }

      const minLat = Math.min(...viewCoordinates.map((point) => point.lat));
      const maxLat = Math.max(...viewCoordinates.map((point) => point.lat));
      const minLon = Math.min(...viewCoordinates.map((point) => point.lon));
      const maxLon = Math.max(...viewCoordinates.map((point) => point.lon));
      const latSpan = maxLat - minLat;
      const lonSpan = maxLon - minLon;
      const maxSpan = Math.max(latSpan, lonSpan);
      const centerLat = (minLat + maxLat) / 2;
      const centerLon = (minLon + maxLon) / 2;
      const level = maxSpan > 2.5 ? 11 : maxSpan > 1.2 ? 10 : maxSpan > 0.55 ? 9 : maxSpan > 0.22 ? 8 : 6;

      map.setCenter(new kakao.maps.LatLng(centerLat, centerLon));
      map.setLevel(level);
    };

    const fitPositions = (positions, preferredLevel = 7) => {
      const coordinates = positions
        .filter(Boolean)
        .map((position) => ({ lat: position.getLat(), lon: position.getLng() }));
      if (!coordinates.length) {
        return false;
      }

      const minLat = Math.min(...coordinates.map((point) => point.lat));
      const maxLat = Math.max(...coordinates.map((point) => point.lat));
      const minLon = Math.min(...coordinates.map((point) => point.lon));
      const maxLon = Math.max(...coordinates.map((point) => point.lon));
      const centerLat = (minLat + maxLat) / 2;
      const centerLon = (minLon + maxLon) / 2;
      const maxSpan = Math.max(maxLat - minLat, maxLon - minLon);
      const level = Math.min(10, Math.max(5, maxSpan > 0.8 ? 9 : maxSpan > 0.35 ? 8 : preferredLevel));

      map.setLevel(level);
      // Zooming can adjust the Kakao Maps viewport, so apply the exact
      // connection-pair midpoint after the level change.
      map.setCenter(new kakao.maps.LatLng(centerLat, centerLon));
      return true;
    };

    const clearMapItems = () => {
      markersRef.current.forEach((marker) => marker.setMap(null));
      linesRef.current.forEach((line) => line.setMap(null));
      overlaysRef.current.forEach((overlay) => overlay.setMap(null));
      markersRef.current = [];
      linesRef.current = [];
      overlaysRef.current = [];
    };

    clearMapItems();
    setRenderError("");
    let focusTimer = null;

    try {
    allRoutes.forEach((route, index) => {
      const color = route.color || candidateTemplates[index % candidateTemplates.length].color;
      const markerPoints = [
        { key: "start", point: route.start, title: `${route.name || "OD"} 출발` },
        { key: "end", point: route.end, title: `${route.name || "OD"} 도착` }
      ];

      markerPoints.forEach(({ point, title }) => {
        if (!point) {
          return;
        }

        const position = toLatLng(point.lat, point.lng);
        if (!position) {
          return;
        }
        includeInView(position);

        const marker = new kakao.maps.Marker({ map, position, title });
        markersRef.current.push(marker);
      });

      if (route.start && route.end) {
        const startPosition = toLatLng(route.start.lat, route.start.lng);
        const endPosition = toLatLng(route.end.lat, route.end.lng);
        if (!startPosition || !endPosition) {
          return;
        }
        const path = [
          startPosition,
          endPosition
        ];
        const distance = getStraightDistanceMeters(route.start, route.end);

        const line = new kakao.maps.Polyline({
          map,
          path,
          strokeWeight: route.draft ? 6 : 7,
          strokeColor: color,
          strokeOpacity: route.draft ? 0.72 : 0.95,
          strokeStyle: route.draft ? "shortdash" : "solid"
        });
        linesRef.current.push(line);

        const label = document.createElement("div");
        label.className = "map-distance-overlay";
        label.textContent = `${route.name || `OD ${index + 1}`} ${formatDistance(distance)}`;

        const overlay = new kakao.maps.CustomOverlay({
          map,
          position: toLatLng(
            (route.start.lat + route.end.lat) / 2,
            (route.start.lng + route.end.lng) / 2
          ) || startPosition,
          content: label,
          yAnchor: 1.4
        });
        overlaysRef.current.push(overlay);
      }
    });

    const nodeById = new Map(candidateNodes.map((node) => [node.node_id, node]));

    candidateRouteSegments.forEach((segment) => {
      const coordinates = segment.segment_geometry || [];
      if (coordinates.length < 2) {
        return;
      }

      const isFocusedRoute = focusedCandidate?.type === "route" && focusedCandidate.id === segment.route_id;
      const segmentStyle = {
        surface_road: { color: "#f59e0b", weight: 6, opacity: 0.9, style: "solid" },
        new_surface_road: { color: "#f59e0b", weight: 6, opacity: 0.9, style: "solid" },
        connector: { color: "#eab308", weight: 5, opacity: 0.88, style: "shortdash" },
        existing_road: { color: "#1f9d55", weight: 4, opacity: 0.78, style: "solid" },
        tunnel: { color: "#7f57d9", weight: 6, opacity: 0.9, style: "shortdash" }
      }[segment.segment_type] || { color: "#0b7ff3", weight: 5, opacity: 0.82, style: "solid" };

      const path = coordinates
        .map((point) => toLatLng(point.lat, point.lon ?? point.lng ?? point.longitude))
        .filter(Boolean);
      if (path.length < 2) {
        return;
      }
      path.forEach((point) => {
        includeInView(point);
      });

      const line = new kakao.maps.Polyline({
        map,
        path,
        strokeWeight: isFocusedRoute ? segmentStyle.weight + 3 : segmentStyle.weight,
        strokeColor: segmentStyle.color,
        strokeOpacity: isFocusedRoute ? 1 : segmentStyle.opacity,
        strokeStyle: segmentStyle.style
      });
      linesRef.current.push(line);
    });

    if (!candidateRouteSegments.length) {
      const maxEdgeFlow = Math.max(...candidateEdges.map((edge) => Number(edge.estimated_flow) || 0), 1);
      candidateEdges.forEach((edge) => {
        const fromNode = nodeById.get(edge.from_node_id);
        const toNode = nodeById.get(edge.to_node_id);
        if (!fromNode || !toNode) {
          return;
        }

        const fromPosition = toLatLng(fromNode.latitude, fromNode.longitude);
        const toPosition = toLatLng(toNode.latitude, toNode.longitude);
        if (!fromPosition || !toPosition) {
          return;
        }
        const path = [fromPosition, toPosition];
        const isFocusedEdge = focusedCandidate?.type === "edge" && focusedCandidate.id === edge.edge_id;
        const line = new kakao.maps.Polyline({
          map,
          path,
          strokeWeight: isFocusedEdge ? 12 : Math.max(3, Math.min(11, 3 + ((Number(edge.estimated_flow) || 0) / maxEdgeFlow) * 8)),
          strokeColor: isFocusedEdge ? "#0b7ff3" : "#e5484d",
          strokeOpacity: isFocusedEdge ? 1 : edge.rank <= 5 ? 0.92 : 0.62,
          strokeStyle: "solid"
        });
        linesRef.current.push(line);

        const label = document.createElement("div");
        label.className = "map-distance-overlay candidate-edge-label";
        label.textContent = `#${edge.rank} ${edge.straight_distance_km.toFixed(1)} km / ${formatNumber(edge.estimated_flow)}`;
        const overlay = new kakao.maps.CustomOverlay({
          map,
          position: toLatLng(
            (fromNode.latitude + toNode.latitude) / 2,
            (fromNode.longitude + toNode.longitude) / 2
          ) || fromPosition,
          content: label,
          yAnchor: 1.4
        });
        overlaysRef.current.push(overlay);
      });
    }

    candidateNodes.forEach((node) => {
      const position = toLatLng(node.latitude, node.longitude);
      if (!position) {
        return;
      }
      includeInView(position);

      const marker = new kakao.maps.Marker({
        map,
        position,
        title: `${node.node_id} flow ${formatNumber(node.cluster_total_flow)}`
      });
      markersRef.current.push(marker);

      const label = document.createElement("div");
      label.className = "candidate-node-overlay";
      label.textContent = node.node_id;
      const overlay = new kakao.maps.CustomOverlay({
        map,
        position,
        content: label,
        yAnchor: 2.2
      });
      overlaysRef.current.push(overlay);
    });

    focusTimer = window.setTimeout(() => {
      try {
        map.relayout();
        let focused = false;
        const selectedEndpointPositions = (focusedCandidate?.endpoints || [])
          .map((point) => toLatLng(point.lat, point.lng))
          .filter(Boolean);
        if (selectedEndpointPositions.length === 2) {
          focused = fitPositions(selectedEndpointPositions, 7);
        }
        if (focusedCandidate?.type === "edge") {
          if (!focused) {
            const edge = candidateEdges.find((item) => item.edge_id === focusedCandidate.id);
            const fromNode = edge ? nodeById.get(edge.from_node_id) : null;
            const toNode = edge ? nodeById.get(edge.to_node_id) : null;
            const endpointPositions = [
              fromNode ? toLatLng(fromNode.latitude, fromNode.longitude) : null,
              toNode ? toLatLng(toNode.latitude, toNode.longitude) : null
            ].filter(Boolean);
            focused = endpointPositions.length === 2 && fitPositions(endpointPositions, 7);
          }
        }
        if (focusedCandidate?.type === "route") {
          const route = candidateRoutes.find((item) => item.route_id === focusedCandidate.id);
          let positions = selectedEndpointPositions;
          if (!focused) {
            const fromNode = route ? nodeById.get(route.from_node_id) : null;
            const toNode = route ? nodeById.get(route.to_node_id) : null;
            positions = [
              fromNode ? toLatLng(fromNode.latitude, fromNode.longitude) : null,
              toNode ? toLatLng(toNode.latitude, toNode.longitude) : null
            ].filter(Boolean);
          }

          // A ranking row is still a connection pair. Its endpoints determine
          // the viewport; route geometry is only a fallback for incomplete data.
          if (!focused && positions.length < 2) {
            positions = candidateRouteSegments
              .filter((segment) => segment.route_id === focusedCandidate.id)
              .flatMap((segment) => segment.segment_geometry || [])
              .map((point) => toLatLng(point.lat, point.lon ?? point.lng ?? point.longitude));
          }
          if (!focused && !positions.length) {
            positions = (route?.route_geometry || [])
              .map((point) => toLatLng(point.lat, point.lon ?? point.lng ?? point.longitude));
          }
          if (!focused) {
            focused = fitPositions(positions, 7);
          }
        }
        if (!focused && hasBounds) {
          fitMapToView();
          window.setTimeout(() => map.relayout(), 120);
        }
      } catch (error) {
        setRenderError(error.message || "지도 범위를 적용하는 중 오류가 발생했습니다.");
      }
    }, 80);
    } catch (error) {
      clearMapItems();
      setRenderError(error.message || "지도 결과를 그리는 중 오류가 발생했습니다.");
      window.setTimeout(() => map.relayout(), 80);
    }
    return () => {
      if (focusTimer !== null) {
        window.clearTimeout(focusTimer);
      }
    };
  }, [mapReady, routes, draftRoute, candidateNodes, candidateEdges, candidateRoutes, candidateRouteSegments, focusedCandidate]);

  useEffect(() => {
    if (!mapReady || !mapRef.current || !containerRef.current) {
      return;
    }

    const map = mapRef.current;
    const relayout = () => {
      window.setTimeout(() => map.relayout(), 0);
      window.setTimeout(() => map.relayout(), 120);
      window.setTimeout(() => map.relayout(), 320);
    };

    relayout();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", relayout);
      return () => window.removeEventListener("resize", relayout);
    }

    const observer = new ResizeObserver(relayout);
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [mapReady]);

  useEffect(() => {
    if (!mapReady || !window.kakao?.maps || !mapRef.current) {
      return;
    }
    const endpoints = (focusedCandidate?.endpoints || [])
      .map((point) => ({ lat: Number(point.lat), lng: Number(point.lng) }))
      .filter((point) =>
        Number.isFinite(point.lat)
        && Number.isFinite(point.lng)
        && point.lat >= -90
        && point.lat <= 90
        && point.lng >= -180
        && point.lng <= 180
      );
    if (endpoints.length !== 2) {
      return;
    }

    const requestId = focusRequestRef.current + 1;
    focusRequestRef.current = requestId;
    const map = mapRef.current;
    const kakao = window.kakao;
    const centerLat = (endpoints[0].lat + endpoints[1].lat) / 2;
    const centerLng = (endpoints[0].lng + endpoints[1].lng) / 2;
    const maxSpan = Math.max(
      Math.abs(endpoints[0].lat - endpoints[1].lat),
      Math.abs(endpoints[0].lng - endpoints[1].lng)
    );
    const level = maxSpan > 0.8 ? 9 : maxSpan > 0.35 ? 8 : 7;
    const center = new kakao.maps.LatLng(centerLat, centerLng);

    const applySelectedCenter = () => {
      if (focusRequestRef.current !== requestId || mapRef.current !== map) {
        return;
      }
      map.relayout();
      map.setLevel(level);
      map.setCenter(center);
    };

    applySelectedCenter();
    const timers = [
      window.setTimeout(applySelectedCenter, 120),
      window.setTimeout(applySelectedCenter, 360)
    ];
    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [mapReady, focusedCandidate]);

  return (
    <div className={`live-map-wrap ${compact ? "compact-map" : ""}`}>
      <div ref={containerRef} className="live-map" />
      {loadError && (
        <div className="map-error">
          <strong>지도를 불러올 수 없습니다.</strong>
          <span>{loadError}</span>
        </div>
      )}
      {renderError && (
        <div className="map-render-warning">
          <strong>지도 결과 표시 오류</strong>
          <span>{renderError}</span>
        </div>
      )}
      {helperText && (
        <div className="map-selection-card">
          <MousePointer2 size={17} />
          <strong>{helperText.title}</strong>
          <span>{helperText.body}</span>
        </div>
      )}
    </div>
  );
}

function Header({ activePage, onPageChange, onShowGuide }) {
  const pages = [
    { id: "analysis", label: "도로/터널 후보군 생성", icon: Network },
    { id: "create", label: "시나리오 생성", icon: ListPlus }
  ];

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">1</span>
        <div>
          <strong>ONESTEP</strong>
          <p className="brand-subtitle">교통 수요 기반 도로·터널 후보 노선 분석</p>
          <p>OD 시나리오 기반 도로·터널 후보지 경제성 분석</p>
        </div>
      </div>

      <nav className="top-actions" aria-label="주요 화면">
        {pages.map((page) => {
          const Icon = page.icon;
          return (
            <button
              className={activePage === page.id ? "active" : ""}
              key={page.id}
              type="button"
              onClick={() => onPageChange(page.id)}
            >
              <Icon size={18} />
              {page.label}
            </button>
          );
        })}
        <button type="button" onClick={onShowGuide}>
          <BookOpen size={18} />
          가이드
        </button>
      </nav>
    </header>
  );
}

function GuideDialog({ onClose }) {
  return (
    <div className="guide-overlay" role="dialog" aria-modal="true" aria-labelledby="guide-title">
      <section className="guide-panel">
        <div className="guide-head">
          <div>
            <BookOpen size={20} />
            <h2 id="guide-title">사용 흐름</h2>
          </div>
          <button className="guide-close" type="button" aria-label="가이드 닫기" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <ol className="guide-steps">
          <li>
            <strong>시나리오 선택</strong>
            <span>기존 페이지에서 파일로 가져온 시나리오나 기본 OD 데이터를 선택합니다.</span>
          </li>
          <li>
            <strong>시나리오 생성</strong>
            <span>지도에서 출발지와 도착지를 클릭하고 물동량, 교통량을 입력해 여러 OD를 묶습니다.</span>
          </li>
          <li>
            <strong>분석 실행</strong>
            <span>선택된 시나리오의 OD 묶음을 기준으로 후보 대안을 비교합니다.</span>
          </li>
          <li>
            <strong>커뮤니티 공유</strong>
            <span>일반 게시판의 글이 좋아요 20개 이상이면 인기 게시판에 자동으로 표시됩니다.</span>
          </li>
        </ol>
      </section>
    </div>
  );
}

function RouteReportDialog({ state, onClose }) {
  const report = state?.report;
  return (
    <div className="guide-overlay report-overlay" role="dialog" aria-modal="true" aria-labelledby="report-title">
      <section className="report-panel">
        <div className="guide-head report-head">
          <div>
            <FileText size={20} />
            <h2 id="report-title">{report?.title || "예비 후보 노선 검토 보고서"}</h2>
          </div>
          <button className="guide-close" type="button" aria-label="보고서 닫기" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        {state.status === "loading" && (
          <div className="report-message">
            <FileText size={22} />
            <strong>보고서 생성 중</strong>
            <span>계산된 후보 노선 데이터를 보고서 형식으로 정리하고 있습니다.</span>
          </div>
        )}
        {state.status === "error" && (
          <div className="report-message error-state">
            <AlertCircle size={22} />
            <strong>보고서를 생성하지 못했습니다.</strong>
            <span>{state.error}</span>
          </div>
        )}
        {state.status === "success" && report && (
          <>
            <div className="report-content">
              <p className="report-summary">{report.summary}</p>
              <div className="report-metrics">
                <span>총 연장<strong>{report.metrics.total_length_km == null ? "현재 산정 불가" : `${report.metrics.total_length_km.toFixed(2)} km`}</strong></span>
                <span>총사업비<strong>{report.metrics.total_project_cost == null ? "현재 산정 불가" : formatMoneyEok(report.metrics.total_project_cost)}</strong></span>
                <span>총편익<strong>{report.metrics.benefit == null ? "현재 산정 불가" : formatMoneyEok(report.metrics.benefit)}</strong></span>
                <span>B/C<strong>{report.metrics.benefit_cost_ratio == null ? "현재 산정 불가" : report.metrics.benefit_cost_ratio.toFixed(2)}</strong></span>
              </div>

              {[
                ["1. 노선 개요", report.route_overview],
                ["2. 비용 분석", report.cost_analysis],
                ["3. 편익 분석", report.benefit_analysis],
                ["4. 기술적 검토", report.technical_review]
              ].map(([title, body]) => (
                <section className="report-section" key={title}>
                  <h3>{title}</h3>
                  <p>{body}</p>
                  {title.startsWith("4.") && report.advantages?.length > 0 && (
                    <>
                      <h4>주요 장점</h4>
                      <ul>{report.advantages.map((item) => <li key={item}>{item}</li>)}</ul>
                    </>
                  )}
                </section>
              ))}

              <section className="report-section">
                <h3>5. 위험요소 및 한계</h3>
                <p>{report.risk_review}</p>
                {report.limitations?.length > 0 && (
                  <ul>{report.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
                )}
                <p className="report-scope-note">교량 분석은 이번 MVP 범위에서 제외됩니다.</p>
              </section>
              <section className="report-section">
                <h3>6. 종합 검토 의견</h3>
                <p>{report.final_opinion}</p>
              </section>
            </div>
            <div className="report-actions">
              <button
                type="button"
                onClick={() => downloadText(`${report.route_id}_preliminary_report.md`, report.markdown)}
              >
                <Download size={17} />
                Markdown 저장
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function LocationSearchField({
  label,
  point,
  query,
  results,
  message,
  placeholder,
  onQueryChange,
  onSearch,
  onSelectResult
}) {
  return (
    <form className="location-search-field" onSubmit={onSearch}>
      <label>{label}</label>
      <div className="location-search-control">
        <Search size={17} />
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={point ? formatPoint(point) : placeholder}
        />
        <button type="submit">검색</button>
      </div>
      {message && <p>{message}</p>}
      {results.length > 0 && (
        <ul>
          {results.map((result) => (
            <li key={result.id}>
              <button type="button" onClick={() => onSelectResult(result)}>
                <strong>{result.place_name}</strong>
                <span>{result.road_address_name || result.address_name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}

function ScenarioSelector({ scenarios, selectedScenarioId, onSelectScenario, onImportScenario, onGoCreate }) {
  const [importMessage, setImportMessage] = useState("");

  const handleImport = (event) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      try {
        const payload = JSON.parse(String(reader.result));
        const scenario = normalizeScenario(file.name.replace(/\.[^.]+$/, ""), payload);
        onImportScenario(scenario);
        setImportMessage(`${scenario.name} 시나리오를 불러왔습니다.`);
      } catch (error) {
        setImportMessage(error.message);
      }
    };
    reader.readAsText(file);
    event.target.value = "";
  };

  return (
    <aside className="input-panel scenario-panel">
      <h2>
        <FileUp size={18} />
        시나리오 선택
      </h2>

      <label className="file-drop">
        <FileUp size={19} />
        <span>OD 시나리오 파일 선택</span>
        <small>JSON 파일을 불러와 분석 대상으로 추가합니다.</small>
        <input type="file" accept="application/json,.json" onChange={handleImport} />
      </label>
      {importMessage && <p className="status-text">{importMessage}</p>}

      <div className="scenario-list">
        {scenarios.map((scenario) => {
          const totals = getScenarioTotals(scenario);
          return (
            <button
              className={selectedScenarioId === scenario.id ? "active" : ""}
              key={scenario.id}
              type="button"
              onClick={() => onSelectScenario(scenario.id)}
            >
              <strong>{scenario.name}</strong>
              <span>{scenario.ods.length}개 OD · 물동량 {formatNumber(totals.freight)}</span>
              <small>{scenario.source} · {scenario.createdAt}</small>
            </button>
          );
        })}
      </div>

      <button className="primary-action" type="button" onClick={onGoCreate}>
        <Plus size={18} />
        새 시나리오 생성
      </button>
    </aside>
  );
}

function CandidateCard({ candidate, active }) {
  return (
    <article className={`candidate-card ${active ? "active" : ""}`}>
      <header className="candidate-head">
        <div>
          <span className="candidate-index" style={{ backgroundColor: candidate.color }}>
            {candidate.id}
          </span>
          <strong>{candidate.name}</strong>
          <small>{candidate.kind}</small>
        </div>
        {active && <Trophy size={22} aria-hidden="true" />}
      </header>

      <div className="candidate-stats">
        <span>
          경제성 점수
          <strong>{candidate.score}<small>/100</small></strong>
        </span>
        <span>
          예상 단축
          <strong>{candidate.time}</strong>
        </span>
        <span>
          추정 비용
          <strong>{candidate.cost}</strong>
        </span>
        <span>
          유형
          <strong>{candidate.type}</strong>
        </span>
      </div>
      <p>{candidate.description}</p>
    </article>
  );
}

function AnalysisPage({
  scenarios,
  selectedScenario,
  selectedScenarioId,
  onSelectScenario,
  onImportScenario,
  onGoCreate
}) {
  const [analysisStatus, setAnalysisStatus] = useState("idle");
  const [selectedOdId, setSelectedOdId] = useState(selectedScenario?.ods[0]?.id);

  useEffect(() => {
    setSelectedOdId(selectedScenario?.ods[0]?.id);
    setAnalysisStatus("idle");
  }, [selectedScenario?.id]);

  const selectedOd = selectedScenario?.ods.find((od) => od.id === selectedOdId) || selectedScenario?.ods[0];
  const totals = selectedScenario ? getScenarioTotals(selectedScenario) : null;
  const mapRoutes = selectedScenario
    ? selectedScenario.ods.map((od, index) => ({
        ...od,
        color: candidateTemplates[index % candidateTemplates.length].color
      }))
    : [];

  return (
    <section className={`dashboard ${analysisStatus === "success" ? "dashboard-analyzed" : "dashboard-idle"}`}>
      <ScenarioSelector
        scenarios={scenarios}
        selectedScenarioId={selectedScenarioId}
        onSelectScenario={onSelectScenario}
        onImportScenario={onImportScenario}
        onGoCreate={onGoCreate}
      />

      <section className="main-panel">
        <section className="map-card" aria-label="선택된 시나리오 지도">
          <div className="map-toolbar">
            <span className="legend candidate" />
            선택 시나리오 OD
            <span className="legend tunnel" />
            분석 후보
          </div>
          <RouteMap
            routes={mapRoutes}
            helperText={{
              title: selectedScenario?.name || "시나리오 없음",
              body: selectedScenario
                ? "좌측에서 파일 또는 기본 시나리오를 선택하고 분석을 시작하세요."
                : "분석할 시나리오를 선택하세요."
            }}
          />
        </section>

        <section className="scenario-detail-band">
          <div>
            <h2>{selectedScenario?.name}</h2>
            <p>
              {selectedScenario?.ods.length || 0}개 OD · 총 물동량 {formatNumber(totals?.freight)} · 총 교통량{" "}
              {formatNumber(totals?.traffic)}
            </p>
          </div>
          <button className="primary-action inline-action" type="button" onClick={() => setAnalysisStatus("success")}>
            <Play size={18} fill="currentColor" />
            후보 분석 시작
          </button>
        </section>

        <section className="od-table-card">
          <div className="section-head">
            <h3>OD 데이터 목록</h3>
            <span>직선거리 합계 {formatDistance(totals?.distance ?? null)}</span>
          </div>
          <div className="od-list">
            {selectedScenario?.ods.map((od) => (
              <button
                className={selectedOd?.id === od.id ? "active" : ""}
                key={od.id}
                type="button"
                onClick={() => setSelectedOdId(od.id)}
              >
                <strong>{od.name}</strong>
                <span>{formatPoint(od.start)} → {formatPoint(od.end)}</span>
                <small>
                  물동량 {formatNumber(od.freight)} · 교통량 {formatNumber(od.traffic)} ·{" "}
                  {formatDistance(getStraightDistanceMeters(od.start, od.end))}
                </small>
              </button>
            ))}
          </div>
        </section>
      </section>

      {analysisStatus !== "idle" && (
      <aside className="result-panel">
        {analysisStatus === "idle" ? (
          <div className="result-empty">
            <span>
              <BarChart3 size={20} />
            </span>
            <h2>분석 전 상태</h2>
            <p>선택된 시나리오의 OD 묶음을 확인한 뒤 후보 분석을 시작하면 추천 결과가 표시됩니다.</p>
          </div>
        ) : (
          <>
            <div className="panel-title">
              <h2>
                <BarChart3 size={19} />
                분석 결과
              </h2>
            </div>
            {candidateTemplates.map((candidate, index) => (
              <CandidateCard candidate={candidate} active={index === 0} key={candidate.id} />
            ))}
            <article className="ai-summary">
              <h3>AI 종합 의견</h3>
              <p>
                선택된 시나리오는 총 {selectedScenario?.ods.length}개 OD를 포함합니다. 물동량과 교통량이 높은 축을
                우선 반영하면 기존 도로 개선안의 B/C가 가장 안정적으로 나타납니다.
              </p>
            </article>
          </>
        )}
      </aside>
      )}
    </section>
  );
}

function ScenarioCreatePage({ onSaveScenario }) {
  const [scenarioName, setScenarioName] = useState("새 OD 시나리오");
  const [createPanelWidth, setCreatePanelWidth] = useState(520);
  const [draftOds, setDraftOds] = useState([]);
  const [draftPointStep, setDraftPointStep] = useState("start");
  const [draftStart, setDraftStart] = useState(null);
  const [draftEnd, setDraftEnd] = useState(null);
  const [draftData, setDraftData] = useState({ name: "", freight: "1000000", traffic: "5000" });
  const [locationSearch, setLocationSearch] = useState({
    start: { query: "", results: [], message: "" },
    end: { query: "", results: [], message: "" }
  });
  const [message, setMessage] = useState("");

  const startCreatePanelResize = useCallback((event) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = createPanelWidth;

    const handlePointerMove = (moveEvent) => {
      const nextWidth = Math.min(560, Math.max(300, startWidth + moveEvent.clientX - startX));
      setCreatePanelWidth(nextWidth);
    };

    const handlePointerUp = () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      document.body.classList.remove("column-resizing");
    };

    document.body.classList.add("column-resizing");
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
  }, [createPanelWidth]);

  const handleSelectPoint = useCallback(
    (point) => {
      if (draftPointStep === "start") {
        setDraftStart(point);
        setDraftEnd(null);
        setDraftPointStep("end");
        setMessage("종료지점을 지도에서 선택하세요.");
        return;
      }

      setDraftEnd(point);
      setDraftPointStep("start");
      setMessage("OD 정보를 입력한 뒤 시나리오 추가 버튼을 누르세요.");
    },
    [draftPointStep]
  );

  const resetDraftRoute = () => {
    setDraftStart(null);
    setDraftEnd(null);
    setDraftPointStep("start");
    setDraftData((current) => ({ ...current, name: "" }));
    setLocationSearch({
      start: { query: "", results: [], message: "" },
      end: { query: "", results: [], message: "" }
    });
    setMessage("시작지점을 지도에서 선택하세요.");
  };

  const handleLocationQueryChange = useCallback((target, query) => {
    setLocationSearch((current) => ({
      ...current,
      [target]: {
        ...current[target],
        query,
        message: "",
        results: query.trim() ? current[target].results : []
      }
    }));
  }, []);

  const handleLocationSearch = useCallback((target, event) => {
    event.preventDefault();

    const keyword = locationSearch[target].query.trim();
    if (!keyword) {
      setLocationSearch((current) => ({
        ...current,
        [target]: { ...current[target], results: [], message: "검색어를 입력하세요." }
      }));
      return;
    }

    setLocationSearch((current) => ({
      ...current,
      [target]: { ...current[target], results: [], message: "검색 중입니다." }
    }));

    loadKakaoMapSdk()
      .then((kakao) => {
        const places = new kakao.maps.services.Places();

        places.keywordSearch(keyword, (results, status) => {
          if (status === kakao.maps.services.Status.OK) {
            setLocationSearch((current) => ({
              ...current,
              [target]: {
                ...current[target],
                results: results.slice(0, 5),
                message: `${results.length}개 결과가 검색되었습니다.`
              }
            }));
            return;
          }

          if (status === kakao.maps.services.Status.ZERO_RESULT) {
            setLocationSearch((current) => ({
              ...current,
              [target]: { ...current[target], results: [], message: "검색 결과가 없습니다." }
            }));
            return;
          }

          setLocationSearch((current) => ({
            ...current,
            [target]: { ...current[target], results: [], message: "검색 중 오류가 발생했습니다." }
          }));
        });
      })
      .catch((error) => {
        setLocationSearch((current) => ({
          ...current,
          [target]: { ...current[target], results: [], message: error.message }
        }));
      });
  }, [locationSearch]);

  const handleSelectLocationResult = useCallback((target, result) => {
    const point = {
      lat: Number(result.y),
      lng: Number(result.x),
      label: result.place_name
    };

    if (target === "start") {
      setDraftStart(point);
      setDraftEnd(null);
      setDraftPointStep("end");
      setMessage("종료지점을 지도 클릭 또는 검색으로 선택하세요.");
    } else {
      setDraftEnd(point);
      setDraftPointStep("start");
      setMessage("OD 정보를 입력한 뒤 시나리오 추가 버튼을 누르세요.");
    }

    setLocationSearch((current) => ({
      ...current,
      [target]: {
        query: result.place_name,
        results: [],
        message: `${result.place_name} 선택됨`
      },
      ...(target === "start" ? { end: { query: "", results: [], message: "" } } : {})
    }));
  }, []);

  const addOd = () => {
    if (!draftStart || !draftEnd) {
      setMessage("시작지점과 종료지점을 모두 선택해야 합니다.");
      return;
    }

    const newOd = {
      id: `od-created-${Date.now()}`,
      name: draftData.name || `OD ${draftOds.length + 1}`,
      start: draftStart,
      end: draftEnd,
      freight: Number(draftData.freight || 0),
      traffic: Number(draftData.traffic || 0)
    };

    setDraftOds((current) => [...current, newOd]);
    resetDraftRoute();
  };

  const finishScenario = () => {
    if (!draftOds.length) {
      setMessage("하나 이상의 OD 데이터를 추가해야 시나리오를 종료할 수 있습니다.");
      return;
    }

    const scenario = {
      id: `scenario-created-${Date.now()}`,
      name: scenarioName.trim() || `생성 시나리오 ${Date.now()}`,
      source: "사용자 생성",
      createdAt: new Date().toISOString().slice(0, 10),
      ods: draftOds
    };

    onSaveScenario(scenario);
    setScenarioName("새 OD 시나리오");
    setDraftOds([]);
    resetDraftRoute();
    setMessage("시나리오가 저장되었습니다. 기존 페이지에서 선택할 수 있습니다.");
  };

  const draftRoute = draftStart || draftEnd
    ? {
        id: "draft-route",
        name: "작성 중",
        start: draftStart,
        end: draftEnd,
        draft: true,
        color: "#e5484d"
      }
    : null;

  const savedRoutes = draftOds.map((od, index) => ({
    ...od,
    color: candidateTemplates[index % candidateTemplates.length].color
  }));

  return (
    <section
      className="create-page"
      style={{ "--create-panel-width": `${createPanelWidth}px` }}
    >
      <aside className="creator-panel">
        <h2>
          <ListPlus size={19} />
          시나리오 생성
        </h2>
        <label className="plain-field">
          <span>시나리오 이름</span>
          <input value={scenarioName} onChange={(event) => setScenarioName(event.target.value)} />
        </label>

        <div className="point-state">
          <div>
            <span>시작지점</span>
            <strong>{formatPoint(draftStart)}</strong>
          </div>
          <div>
            <span>종료지점</span>
            <strong>{formatPoint(draftEnd)}</strong>
          </div>
        </div>

        <div className="search-block">
          <LocationSearchField
            label="시작지점 검색"
            point={draftStart}
            query={locationSearch.start.query}
            results={locationSearch.start.results}
            message={locationSearch.start.message}
            placeholder="지명 또는 건물명 검색"
            onQueryChange={(query) => handleLocationQueryChange("start", query)}
            onSearch={(event) => handleLocationSearch("start", event)}
            onSelectResult={(result) => handleSelectLocationResult("start", result)}
          />
          <LocationSearchField
            label="종료지점 검색"
            point={draftEnd}
            query={locationSearch.end.query}
            results={locationSearch.end.results}
            message={locationSearch.end.message}
            placeholder="지명 또는 건물명 검색"
            onQueryChange={(query) => handleLocationQueryChange("end", query)}
            onSearch={(event) => handleLocationSearch("end", event)}
            onSelectResult={(result) => handleSelectLocationResult("end", result)}
          />
        </div>

        <label className="plain-field">
          <span>OD 이름</span>
          <input
            value={draftData.name}
            placeholder={`OD ${draftOds.length + 1}`}
            onChange={(event) => setDraftData((current) => ({ ...current, name: event.target.value }))}
          />
        </label>
        <label className="plain-field">
          <span>물동량</span>
          <input
            inputMode="numeric"
            value={draftData.freight}
            onChange={(event) => setDraftData((current) => ({ ...current, freight: event.target.value }))}
          />
        </label>
        <label className="plain-field">
          <span>교통량</span>
          <input
            inputMode="numeric"
            value={draftData.traffic}
            onChange={(event) => setDraftData((current) => ({ ...current, traffic: event.target.value }))}
          />
        </label>

        <button className="primary-action" type="button" onClick={addOd}>
          <Plus size={18} />
          시나리오 추가
        </button>
        <button className="secondary-action" type="button" onClick={resetDraftRoute}>
          <RotateCcw size={17} />
          현재 OD 초기화
        </button>
        <button className="finish-action" type="button" onClick={finishScenario}>
          <Save size={18} />
          시나리오 저장
        </button>

        {message && <p className="status-text">{message}</p>}

        <div className="created-od-list">
          <div className="section-head">
            <h3>생성된 OD</h3>
            <span>{draftOds.length}개</span>
          </div>
          {draftOds.length === 0 ? (
            <p>아직 추가된 OD가 없습니다.</p>
          ) : (
            draftOds.map((od) => (
              <article key={od.id}>
                <strong>{od.name}</strong>
                <span>{formatPoint(od.start)} → {formatPoint(od.end)}</span>
                <small>물동량 {formatNumber(od.freight)} · 교통량 {formatNumber(od.traffic)}</small>
              </article>
            ))
          )}
        </div>
      </aside>

      <div
        className="column-resizer column-resizer-create"
        role="separator"
        aria-label="시나리오 생성 패널 너비 조절"
        aria-orientation="vertical"
        onPointerDown={startCreatePanelResize}
      />

      <section className="creator-map" aria-label="시나리오 생성 지도">
        <RouteMap
          routes={savedRoutes}
          draftRoute={draftRoute}
          onSelectPoint={handleSelectPoint}
          helperText={{
            title: draftPointStep === "start" ? "시작지점 선택" : "종료지점 선택",
            body: "지도를 클릭해 OD의 시작과 종료 좌표를 지정합니다."
          }}
        />
      </section>
    </section>
  );
}
function CommunityPage({ posts, onCreatePost, onLikePost }) {
  const [activeBoard, setActiveBoard] = useState("general");
  const [form, setForm] = useState({ title: "", body: "", author: "" });
  const popularPosts = useMemo(
    () => posts.filter((post) => post.likes >= 20).sort((a, b) => b.likes - a.likes),
    [posts]
  );

  const submitPost = (event) => {
    event.preventDefault();
    const title = form.title.trim();
    const body = form.body.trim();

    if (!title || !body) {
      return;
    }

    onCreatePost({
      id: `post-${Date.now()}`,
      title,
      body,
      author: form.author.trim() || "익명",
      likes: 0,
      createdAt: new Date().toISOString().slice(0, 10)
    });
    setForm({ title: "", body: "", author: "" });
  };

  return (
    <section className="community-page">
      <aside className="community-tabs" aria-label="커뮤니티 게시판">
        <button className={activeBoard === "notice" ? "active" : ""} type="button" onClick={() => setActiveBoard("notice")}>
          <Megaphone size={18} />
          공고 게시판
        </button>
        <button className={activeBoard === "popular" ? "active" : ""} type="button" onClick={() => setActiveBoard("popular")}>
          <Trophy size={18} />
          인기 게시판
        </button>
        <button className={activeBoard === "general" ? "active" : ""} type="button" onClick={() => setActiveBoard("general")}>
          <MessageSquareText size={18} />
          일반 게시판
        </button>
      </aside>

      <section className="board-panel">
        {activeBoard === "notice" && (
          <>
            <div className="section-head">
              <h2>공고 게시판</h2>
              <span>정부 · 기업</span>
            </div>
            <div className="post-list">
              {announcementPosts.map((post) => (
                <article className="notice-post" key={post.id}>
                  <span className={post.type === "정부" ? "notice-type government" : "notice-type company"}>
                    {post.type === "정부" ? <Building2 size={15} /> : <Bell size={15} />}
                    {post.type}
                  </span>
                  <h3>{post.title}</h3>
                  <p>{post.body}</p>
                  <small>{post.date}</small>
                </article>
              ))}
            </div>
          </>
        )}

        {activeBoard === "popular" && (
          <>
            <div className="section-head">
              <h2>인기 게시판</h2>
              <span>좋아요 20개 이상 · 좋아요 순</span>
            </div>
            <PostList posts={popularPosts} onLikePost={onLikePost} />
          </>
        )}

        {activeBoard === "general" && (
          <>
            <div className="section-head">
              <h2>일반 게시판</h2>
              <span>좋아요 20개 이상이면 인기 게시판에 자동 반영</span>
            </div>
            <form className="post-form" onSubmit={submitPost}>
              <input
                value={form.title}
                placeholder="제목"
                onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
              />
              <textarea
                value={form.body}
                placeholder="내용"
                onChange={(event) => setForm((current) => ({ ...current, body: event.target.value }))}
              />
              <div>
                <input
                  value={form.author}
                  placeholder="작성자"
                  onChange={(event) => setForm((current) => ({ ...current, author: event.target.value }))}
                />
                <button type="submit">
                  <Plus size={17} />
                  글 생성
                </button>
              </div>
            </form>
            <PostList posts={posts} onLikePost={onLikePost} />
          </>
        )}
      </section>
    </section>
  );
}

function PostList({ posts, onLikePost }) {
  if (!posts.length) {
    return (
      <div className="empty-board">
        <Search size={22} />
        <strong>표시할 글이 없습니다.</strong>
      </div>
    );
  }

  return (
    <div className="post-list">
      {posts.map((post) => (
        <article className="community-post" key={post.id}>
          <header>
            <div>
              <h3>{post.title}</h3>
              <small>{post.author} · {post.createdAt}</small>
            </div>
            <button type="button" onClick={() => onLikePost(post.id)}>
              <Heart size={17} fill={post.likes >= 20 ? "currentColor" : "none"} />
              {post.likes}
            </button>
          </header>
          <p>{post.body}</p>
        </article>
      ))}
    </div>
  );
}

function AnalysisMvpPage({ scenarios = [], selectedScenarioId }) {
  const [analysisStatus, setAnalysisStatus] = useState("idle");
  const [routeStatus, setRouteStatus] = useState("idle");
  const [columnWidths, setColumnWidths] = useState({ left: 520, right: 380 });
  const [uploadedFile, setUploadedFile] = useState(null);
  const [includeBaseOd, setIncludeBaseOd] = useState(true);
  const [selectedScenarioIds, setSelectedScenarioIds] = useState(
    selectedScenarioId ? [selectedScenarioId] : []
  );
  const [candidateResult, setCandidateResult] = useState(null);
  const [candidateRouteResult, setCandidateRouteResult] = useState(null);
  const [routeLimit, setRouteLimit] = useState(20);
  const [flowFilterPercent, setFlowFilterPercent] = useState("");
  const [lowImpactPrunePercent, setLowImpactPrunePercent] = useState("20");
  const [edgeLimit, setEdgeLimit] = useState(50);
  const [sampleSize, setSampleSize] = useState("");
  const [useAllRegions, setUseAllRegions] = useState(false);
  const [selectedRegions, setSelectedRegions] = useState([]);
  const [regionBufferKm, setRegionBufferKm] = useState(10);
  const [errorMessage, setErrorMessage] = useState("");
  const [routeErrorMessage, setRouteErrorMessage] = useState("");
  const [focusedCandidate, setFocusedCandidate] = useState(null);
  const [reportDialog, setReportDialog] = useState(null);
  const selectedSupplementalScenarios = useMemo(
    () => scenarios.filter((scenario) => selectedScenarioIds.includes(scenario.id)),
    [scenarios, selectedScenarioIds]
  );
  const supplementalOdCount = selectedSupplementalScenarios.reduce(
    (total, scenario) => total + (scenario.ods?.length || 0),
    0
  );
  const hasSelectedOdSource = includeBaseOd || supplementalOdCount > 0;
  const useRegionFilter = !useAllRegions && selectedRegions.length > 0;
  const clampColumnWidth = (value, min, max) => Math.min(max, Math.max(min, value));

  const startColumnResize = useCallback(
    (side) => (event) => {
      event.preventDefault();
      const startX = event.clientX;
      const startWidths = columnWidths;

      const handlePointerMove = (moveEvent) => {
        const deltaX = moveEvent.clientX - startX;
        setColumnWidths({
          left:
            side === "left"
              ? clampColumnWidth(startWidths.left + deltaX, 280, 520)
              : startWidths.left,
          right:
            side === "right"
              ? clampColumnWidth(startWidths.right - deltaX, 300, 560)
              : startWidths.right,
        });
      };

      const handlePointerUp = () => {
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", handlePointerUp);
        document.body.classList.remove("column-resizing");
      };

      document.body.classList.add("column-resizing");
      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", handlePointerUp);
    },
    [columnWidths]
  );

  useEffect(() => {
    if (selectedScenarioId) {
      setSelectedScenarioIds((current) => (current.length ? current : [selectedScenarioId]));
    }
  }, [selectedScenarioId]);

  const toggleScenarioSelection = useCallback((scenarioId) => {
    setSelectedScenarioIds((current) =>
      current.includes(scenarioId)
        ? current.filter((id) => id !== scenarioId)
        : [...current, scenarioId]
    );
  }, []);

  const toggleRegionSelection = useCallback((regionName) => {
    setSelectedRegions((current) =>
      current.includes(regionName)
        ? current.filter((name) => name !== regionName)
        : [...current, regionName]
    );
  }, []);

  const runCandidateGeneration = async () => {
    setAnalysisStatus("loading");
    setRouteStatus("idle");
    setErrorMessage("");
    setRouteErrorMessage("");
    setCandidateResult(null);
    setCandidateRouteResult(null);
    setFocusedCandidate(null);
    setReportDialog(null);

    const formData = new FormData();
    formData.append("top_node_limit", "100");
    formData.append("edge_limit", String(edgeLimit));
    formData.append("include_base_od", includeBaseOd ? "true" : "false");
    formData.append("use_region_filter", useRegionFilter ? "true" : "false");
    formData.append("region_buffer_km", String(regionBufferKm));
    if (useRegionFilter) {
      selectedRegions.forEach((regionName) => {
        formData.append("selected_regions", regionName);
      });
    }
    if (flowFilterPercent) {
      formData.append("flow_filter_percent", flowFilterPercent);
    }
    if (lowImpactPrunePercent !== "") {
      formData.append("low_impact_prune_percent", lowImpactPrunePercent);
    }
    if (sampleSize) {
      formData.append("sample_size", sampleSize);
    }
    if (uploadedFile) {
      formData.append("file", uploadedFile);
    }
    if (selectedSupplementalScenarios.length && supplementalOdCount > 0) {
      const scenarioCsv = buildScenarioOdCsv(selectedSupplementalScenarios);
      const scenarioFile = new File([scenarioCsv], "scenario_od.csv", { type: "text/csv" });
      formData.append("supplemental_file", scenarioFile);
    }

    try {
      const response = await fetch(`${API_BASE_URL}/api/od-candidates`, {
        method: "POST",
        body: formData
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "OD 후보 생성에 실패했습니다.");
      }
      setCandidateResult(payload);
      setAnalysisStatus("success");
    } catch (error) {
      setErrorMessage(error.message);
      setAnalysisStatus("error");
    }
  };

  const runCandidateRouteAnalysis = async () => {
    if (!candidateResult?.nodes?.length || !candidateResult?.edges?.length) {
      setRouteErrorMessage("먼저 OD 기반 후보 연결쌍을 생성해주세요.");
      setRouteStatus("error");
      return;
    }

    setRouteStatus("loading");
    setRouteErrorMessage("");
    setCandidateRouteResult(null);
    setFocusedCandidate(null);
    setReportDialog(null);

    try {
      const appliedRegion = candidateResult?.stats?.region_filter_summary;
      const response = await fetch(`${API_BASE_URL}/api/candidate-routes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          nodes: candidateResult.nodes,
          edges: candidateResult.edges,
          route_limit: routeLimit,
          selected_regions: appliedRegion?.selected_regions || [],
          use_region_filter: Boolean(appliedRegion?.enabled),
          region_buffer_km: appliedRegion?.buffer_km ?? regionBufferKm
        })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "MVP 예비 후보 노선 산정에 실패했습니다.");
      }
      setCandidateRouteResult(payload);
      setRouteStatus("success");
    } catch (error) {
      setRouteErrorMessage(error.message);
      setRouteStatus("error");
    }
  };

  const nodes = candidateResult?.nodes || [];
  const edges = candidateResult?.edges || [];
  const stats = candidateResult?.stats;
  const candidateRoutes = candidateRouteResult?.routes || [];
  const routeSegments = candidateRouteResult?.segments || [];
  const rankedRoutes = candidateRouteResult?.ranked_routes || [];
  const routeCosts = candidateRouteResult?.costs || [];
  const costByRouteId = new Map(routeCosts.map((cost) => [cost.route_id, cost]));
  const nodeById = new Map(nodes.map((node) => [node.node_id, node]));

  const focusConnectionPair = useCallback((type, id, fromNodeId, toNodeId) => {
    const fromNode = nodeById.get(fromNodeId);
    const toNode = nodeById.get(toNodeId);
    const endpoints = fromNode && toNode
      ? [
          { lat: Number(fromNode.latitude), lng: Number(fromNode.longitude) },
          { lat: Number(toNode.latitude), lng: Number(toNode.longitude) }
        ]
      : [];
    setFocusedCandidate({
      type,
      id,
      fromNodeId,
      toNodeId,
      endpoints
    });
  }, [nodes]);

  const openRouteReport = useCallback(async (event, routeId) => {
    event.stopPropagation();
    setReportDialog({ status: "loading", routeId, report: null, error: "" });
    try {
      const response = await fetch(`${API_BASE_URL}/api/candidate-routes/reports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          routes: candidateRoutes,
          segments: routeSegments,
          costs: routeCosts,
          ranked_routes: rankedRoutes,
          route_ids: [routeId]
        })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "예비 후보 노선 보고서 생성에 실패했습니다.");
      }
      if (!payload.reports?.[0]) {
        throw new Error("선택한 후보 노선의 보고서 데이터가 없습니다.");
      }
      setReportDialog({
        status: "success",
        routeId,
        report: payload.reports[0],
        error: ""
      });
    } catch (error) {
      setReportDialog({
        status: "error",
        routeId,
        report: null,
        error: error.message
      });
    }
  }, [candidateRoutes, routeSegments, routeCosts, rankedRoutes]);

  return (
    <>
    {reportDialog && (
      <RouteReportDialog state={reportDialog} onClose={() => setReportDialog(null)} />
    )}
    <section
      className={`dashboard od-mvp-dashboard ${analysisStatus === "idle" ? "dashboard-idle" : "dashboard-analyzed"}`}
      style={{
        "--left-panel-width": `${columnWidths.left}px`,
        "--right-panel-width": `${columnWidths.right}px`,
      }}
    >
      <aside className="input-panel scenario-panel">
        <h2>
          <Network size={18} />
          OD 후보 생성 MVP
        </h2>

        <label className="file-drop">
          <FileUp size={19} />
          <span>{uploadedFile ? uploadedFile.name : "CSV 미업로드 시 기본 OD 데이터 사용"}</span>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => setUploadedFile(event.target.files?.[0] || null)}
          />
        </label>

        <div className="analysis-options candidate-options">
          <div className="od-folder-tree">
            <div className="tree-root">
              <Network size={15} />
              <div className="tree-root-copy">
                <strong>OD 데이터 선택</strong>
                <small>후보군 생성에 사용할 OD 소스를 선택하세요</small>
              </div>
            </div>
            <label className={`tree-node ${includeBaseOd ? "selected" : ""}`}>
              <input
                type="checkbox"
                checked={includeBaseOd}
                onChange={(event) => setIncludeBaseOd(event.target.checked)}
              />
              <span className="tree-node-icon">B</span>
              <span className="tree-node-readable">
                <strong>기본 OD</strong>
                <small>{uploadedFile ? uploadedFile.name : "프로젝트 기본 OD CSV"}</small>
              </span>
              <span className="tree-badge">{includeBaseOd ? "포함" : "제외"}</span>
            </label>
            <div className="tree-group">
              <div className="tree-group-label">
                <span className="tree-branch" />
                <span>OD 시나리오</span>
              </div>
              {scenarios.map((scenario) => (
                <label
                  className={`tree-node child ${selectedScenarioIds.includes(scenario.id) ? "selected" : ""}`}
                  key={scenario.id}
                >
                  <input
                    type="checkbox"
                    checked={selectedScenarioIds.includes(scenario.id)}
                    onChange={() => toggleScenarioSelection(scenario.id)}
                  />
                  <span className="tree-node-icon">OD</span>
                  <span className="tree-node-readable">
                    <strong>{scenario.name}</strong>
                    <small>{scenario.source || "사용자 생성"} · {formatNumber(scenario.ods?.length || 0)}개 OD</small>
                  </span>
                  <span className="tree-badge">{selectedScenarioIds.includes(scenario.id) ? "선택됨" : "미선택"}</span>
                </label>
              ))}
            </div>
            <p className="tree-summary-readable">
              기본 OD {includeBaseOd ? "포함" : "제외"} · 추가 OD {formatNumber(supplementalOdCount)}개 선택
            </p>
          </div>
        </div>

        <div className="analysis-options region-filter-options">
          <div className="region-filter-heading">
            <div>
              <strong>
                <MapPin size={16} />
                계산 구역 선택
              </strong>
              <small>구역을 선택하지 않으면 전체 범위로 계산합니다.</small>
            </div>
            <label className="region-all-toggle">
              <input
                type="checkbox"
                checked={useAllRegions}
                onChange={(event) => setUseAllRegions(event.target.checked)}
              />
              전체 사용
            </label>
          </div>
          <div className={`region-checkbox-grid ${useAllRegions ? "disabled" : ""}`}>
            {REGION_OPTIONS.map((regionName) => (
              <label
                className={selectedRegions.includes(regionName) ? "selected" : ""}
                key={regionName}
              >
                <input
                  type="checkbox"
                  checked={selectedRegions.includes(regionName)}
                  disabled={useAllRegions}
                  onChange={() => toggleRegionSelection(regionName)}
                />
                {regionName}
              </label>
            ))}
          </div>
          <label className="plain-field region-buffer-field">
            <span>경계 여유 거리</span>
            <div>
              <input
                type="number"
                min="0"
                max="100"
                step="1"
                value={regionBufferKm}
                disabled={useAllRegions}
                onChange={(event) => setRegionBufferKm(Number(event.target.value))}
              />
              <small>km</small>
            </div>
          </label>
        </div>

        <div className="analysis-options candidate-options">
          <label className="plain-field">
            <span>OD 필터</span>
            <select value={flowFilterPercent} onChange={(event) => setFlowFilterPercent(event.target.value)}>
              <option value="">전체 OD</option>
              <option value="5">상위 5%</option>
              <option value="10">상위 10%</option>
              <option value="20">상위 20%</option>
            </select>
          </label>
          <label className="plain-field">
            <span>하위 정점 제거</span>
            <select value={lowImpactPrunePercent} onChange={(event) => setLowImpactPrunePercent(event.target.value)}>
              <option value="20">하위 20%</option>
              <option value="30">하위 30%</option>
              <option value="">제거 없음</option>
            </select>
          </label>
          <label className="plain-field">
            <span>후보 연결쌍</span>
            <select value={edgeLimit} onChange={(event) => setEdgeLimit(Number(event.target.value))}>
              <option value={20}>상위 20개</option>
              <option value={50}>상위 50개</option>
              <option value={100}>상위 100개</option>
            </select>
          </label>
          <label className="plain-field">
            <span>샘플링</span>
            <select value={sampleSize} onChange={(event) => setSampleSize(event.target.value)}>
              <option value="">사용 안 함</option>
              <option value="5000">5,000행</option>
              <option value="20000">20,000행</option>
              <option value="50000">50,000행</option>
            </select>
          </label>
        </div>

        <button
          className="primary-action"
          type="button"
          onClick={runCandidateGeneration}
          disabled={analysisStatus === "loading" || !hasSelectedOdSource}
        >
          <Play size={18} fill="currentColor" />
          {analysisStatus === "loading" ? "후보 생성 중" : "후보 생성 실행"}
        </button>

        <p className="status-text">
          {useRegionFilter
            ? `${selectedRegions.join(", ")} 및 경계 ${regionBufferKm}km 범위의 OD만 사용합니다.`
            : "전체 OD의 total_flow를 sample_weight로 사용해 후보 정점을 만들고, 전체 OD 기반 estimated_flow로 초기 후보 연결쌍을 정렬합니다."}
        </p>

        <div className="analysis-options">
          <label className="plain-field">
            <span>노선 탐색 후보 수</span>
            <select value={routeLimit} onChange={(event) => setRouteLimit(Number(event.target.value))}>
              <option value={5}>상위 5개</option>
              <option value={10}>상위 10개</option>
              <option value={15}>상위 15개</option>
              <option value={20}>상위 20개</option>
              <option value={30}>상위 30개</option>
              <option value={50}>상위 50개</option>
            </select>
          </label>
          <button
            className="secondary-action"
            type="button"
            onClick={runCandidateRouteAnalysis}
            disabled={analysisStatus !== "success" || routeStatus === "loading"}
          >
            <Play size={18} fill="currentColor" />
            {routeStatus === "loading" ? "예비 노선 산정 중" : "MVP 예비 후보 노선 산정"}
          </button>
          {routeErrorMessage && <p className="status-text error-copy">{routeErrorMessage}</p>}
        </div>
      </aside>

      <div
        className="column-resizer column-resizer-left"
        role="separator"
        aria-label="왼쪽 패널 너비 조절"
        aria-orientation="vertical"
        onPointerDown={startColumnResize("left")}
      />

      <section className="main-panel">
        <section className="map-card" aria-label="OD 기반 후보 정점과 후보 연결쌍 지도">
          <div className="map-toolbar">
            <span className="legend candidate" />
            {stats?.region_filter_summary?.enabled ? "선택 구역 OD" : "전체 OD"} 가중치 기반 후보 정점
            <span className="legend existing-road" />
            기존도로
            <span className="legend new-road" />
            신설도로
            <span className="legend tunnel" />
            터널
          </div>
          <RouteMap
            routes={[]}
            candidateNodes={nodes}
            candidateEdges={edges}
            candidateRoutes={candidateRoutes}
            candidateRouteSegments={routeSegments}
            focusedCandidate={focusedCandidate}
            helperText={{
              title: stats?.source_name || "OD CSV를 선택하세요",
              body: edges.length
                ? "이 결과는 실제 도로 노선이 아니라 DEM·하천·기존도로망 기반 경로 탐색 전의 수요 기반 초기 후보 연결쌍입니다."
                : "기본 CSV 또는 업로드 CSV로 후보 생성을 실행하세요."
            }}
          />
        </section>

        {candidateRouteResult && (
          <section className="od-table-card">
            <div className="section-head">
              <h3>MVP 예비 후보 노선 산정 결과</h3>
              <span>{formatNumber(rankedRoutes.length)}개 후보</span>
            </div>
            <div className="stats-grid">
              <span>
                신규 후보
                <strong>{formatNumber(rankedRoutes.length)}</strong>
              </span>
              <span>
                기준 경로
                <strong>{formatNumber(candidateRouteResult.routes.filter((route) => route.route_type === "existing_baseline").length)}</strong>
              </span>
              <span>
                터널 구간
                <strong>{formatNumber(routeSegments.filter((segment) => segment.segment_type === "tunnel").length)}</strong>
              </span>
              <span>
                실패
                <strong>{formatNumber(candidateRouteResult.routes.filter((route) => route.status === "failed").length)}</strong>
              </span>
            </div>
            {candidateRouteResult.region_filter_summary && (
              <p className="status-text">
                계산 범위: {candidateRouteResult.region_filter_summary.enabled
                  ? candidateRouteResult.region_filter_summary.selected_regions.join(", ")
                  : "전체"} · A* {formatNumber(candidateRouteResult.region_filter_summary.a_star_calls)}회 ·
                격자 {formatNumber(candidateRouteResult.region_filter_summary.cost_grid_cells)}셀 ·
                {Number(candidateRouteResult.region_filter_summary.elapsed_seconds || 0).toFixed(2)}초
              </p>
            )}
            {candidateRouteResult.warnings.map((warning) => (
              <p className="status-text" key={warning}>{warning}</p>
            ))}
          </section>
        )}

        {stats && (
          <section className="od-table-card">
            <div className="section-head">
              <h3>처리 로그</h3>
              <span>좌표 제외 {formatNumber(stats.coordinate_excluded_rows)}개</span>
            </div>
            <div className="stats-grid">
              <span>
                신규 정점
                <strong>{formatNumber(nodes.length)}</strong>
              </span>
              <span>
                후보 연결쌍
                <strong>{formatNumber(edges.length)}</strong>
              </span>
              <span>
                클러스터링 OD
                <strong>{formatNumber(stats.clustered_od_rows)}</strong>
              </span>
              <span>
                사용 클러스터
                <strong>{stats.cluster_count_used}/{stats.cluster_count_requested}</strong>
              </span>
            </div>
            {stats.region_filter_summary && (
              <p className="status-text">
                구역 필터: {stats.region_filter_summary.enabled
                  ? stats.region_filter_summary.selected_regions.join(", ")
                  : "전체"} · OD {formatNumber(stats.region_filter_summary.od_rows_before)} →{" "}
                {formatNumber(stats.region_filter_summary.od_rows_after)} · 좌표{" "}
                {formatNumber(stats.region_filter_summary.candidate_coordinates_before)} →{" "}
                {formatNumber(stats.region_filter_summary.candidate_coordinates_after)}
              </p>
            )}
            <div className="stats-grid iterative-stats">
              <span>
                원시 중심점
                <strong>{formatNumber(stats.pre_merge_node_count)}</strong>
              </span>
              <span>
                3km 병합 후
                <strong>{formatNumber(stats.merged_node_count)}</strong>
              </span>
              <span>
                반복 K
                <strong>{stats.iterative_cluster_counts?.join(", ")}</strong>
              </span>
              <span>
                유지 상한
                <strong>{formatNumber(stats.top_node_limit)}</strong>
              </span>
            </div>
            <div className="stats-grid iterative-stats">
              <span>
                제거 정점
                <strong>{formatNumber(stats.pruned_node_count)}</strong>
              </span>
              <span>
                edge 상위 제한
                <strong>{formatNumber(stats.edge_limit)}</strong>
              </span>
              <span>
                0 이하 flow 제외
                <strong>{formatNumber(stats.non_positive_flow_excluded_rows)}</strong>
              </span>
              <span>
                정점 제거율
                <strong>{stats.low_impact_prune_percent === null ? "없음" : `${stats.low_impact_prune_percent}%`}</strong>
              </span>
            </div>
            <p className="status-text">
              실제 도로·터널 후보 노선은 다음 단계에서 비용지도와 최저비용 경로 탐색을 통해 산정됩니다.
            </p>
            {stats.warnings.map((warning) => (
              <p className="status-text" key={warning}>{warning}</p>
            ))}
          </section>
        )}
      </section>

      {analysisStatus !== "idle" && (
      <>
      <div
        className="column-resizer column-resizer-right"
        role="separator"
        aria-label="오른쪽 패널 너비 조절"
        aria-orientation="vertical"
        onPointerDown={startColumnResize("right")}
      />
      <aside className="result-panel">
        {analysisStatus === "idle" && (
          <div className="result-empty">
            <span>
              <BarChart3 size={20} />
            </span>
            <h2>분석 전 상태</h2>
            <p>전체 OD 기반 분석을 실행하려면 기본 CSV에 대응하는 행정동 좌표 lookup 또는 좌표 포함 업로드 CSV가 필요합니다.</p>
          </div>
        )}

        {analysisStatus === "loading" && (
          <div className="result-empty">
            <span>
              <Network size={20} />
            </span>
            <h2>후보 생성 중</h2>
            <p>전체 OD를 출발·도착 weighted point로 변환하고 sample_weight 기반 K-Means로 수요 중심 정점을 계산하고 있습니다.</p>
          </div>
        )}

        {analysisStatus === "error" && (
          <div className="result-empty error-state">
            <span>
              <AlertCircle size={20} />
            </span>
            <h2>후보 생성 불가</h2>
            <p>{errorMessage}</p>
          </div>
        )}

        {analysisStatus === "success" && (
          <>
            <div className="panel-title">
              <h2>
                <MapPin size={19} />
                {candidateRouteResult ? "후보 노선 순위" : "후보 연결쌍"}
              </h2>
              <span>{candidateRouteResult ? `${formatNumber(rankedRoutes.length)}개` : `${formatNumber(edges.length)}개`}</span>
            </div>
            <div className="edge-list">
              {candidateRouteResult ? rankedRoutes.map((route) => {
                const cost = costByRouteId.get(route.route_id);
                return (
                  <article
                    className={`edge-card ranked-route-card ${
                      focusedCandidate?.type === "route" && focusedCandidate.id === route.route_id ? "active" : ""
                    }`}
                    key={route.route_id}
                    role="button"
                    tabIndex={0}
                    onClick={() => focusConnectionPair(
                      "route",
                      route.route_id,
                      route.from_node_id,
                      route.to_node_id
                    )}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        focusConnectionPair(
                          "route",
                          route.route_id,
                          route.from_node_id,
                          route.to_node_id
                        );
                      }
                    }}
                  >
                    <header>
                      <strong>#{route.rank} {route.from_node_id} → {route.to_node_id}</strong>
                      <small>{route.summary.status}</small>
                    </header>
                    <div>
                      <span>총 노선 길이 <strong>{route.summary.route_length_km.toFixed(2)} km</strong></span>
                      <span>기존 도로 접근 <strong>{Number(route.summary.existing_road_access_percent || 0).toFixed(1)}%</strong></span>
                      <span>예상 수요 <strong>{formatNumber(route.estimated_flow)}</strong></span>
                      <span>거리 절감 <strong>{Number(route.summary.distance_saving_km || route.distance_saving_km || 0).toFixed(2)} km</strong></span>
                      <span>기존도로 <strong>{Number(route.summary.existing_road_length_km || 0).toFixed(2)} km</strong></span>
                      <span>신설 지상도로 <strong>{Number(route.summary.new_surface_road_length_km ?? route.summary.surface_road_length_km).toFixed(2)} km</strong></span>
                      <span>접속도로 <strong>{Number(route.summary.connector_length_km || 0).toFixed(2)} km</strong></span>
                      <span>신설터널 <strong>{route.summary.tunnel_length_km.toFixed(2)} km</strong></span>
                      <span>수요x절감 <strong>{formatNumber(route.summary.benefit_proxy || 0)}</strong></span>
                      <span>직접공사비 <strong>{formatMoneyEok(cost?.total_direct_cost)}</strong></span>
                      <span>예비율 포함 공사비 <strong>{formatMoneyEok(route.total_screen_cost)}</strong></span>
                      <span>MVP 예비 경제성 점수 <strong>{route.economic_score.toFixed(1)}</strong></span>
                    </div>
                    {route.summary.failed_reason && <p className="status-text error-copy">{route.summary.failed_reason}</p>}
                    <div className="route-report-actions">
                      <button
                        type="button"
                        onClick={(event) => openRouteReport(event, route.route_id)}
                        onKeyDown={(event) => event.stopPropagation()}
                      >
                        <FileText size={16} />
                        보고서 보기
                      </button>
                    </div>
                  </article>
                );
              }) : edges.map((edge) => (
                <article
                  className={`edge-card ${
                    focusedCandidate?.type === "edge" && focusedCandidate.id === edge.edge_id ? "active" : ""
                  }`}
                  key={edge.edge_id}
                  role="button"
                  tabIndex={0}
                  onClick={() => focusConnectionPair(
                    "edge",
                    edge.edge_id,
                    edge.from_node_id,
                    edge.to_node_id
                  )}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      focusConnectionPair(
                        "edge",
                        edge.edge_id,
                        edge.from_node_id,
                        edge.to_node_id
                      );
                    }
                  }}
                >
                  <header>
                    <strong>#{edge.rank} {edge.from_node_id} → {edge.to_node_id}</strong>
                    <small>{edge.edge_id}</small>
                  </header>
                  <div>
                    <span>거리 <strong>{edge.straight_distance_km.toFixed(2)} km</strong></span>
                    <span>추정 수요 <strong>{formatNumber(edge.estimated_flow)}</strong></span>
                    <span>집계 OD <strong>{formatNumber(edge.od_count)}</strong></span>
                    <span>기준 <strong>{stats?.region_filter_summary?.enabled ? "선택 구역 OD" : "전체 OD"}</strong></span>
                  </div>
                </article>
              ))}
            </div>
          </>
        )}
      </aside>
      </>
      )}
    </section>
    </>
  );
}

function App() {
  const [hasStarted, setHasStarted] = useState(false);
  const [activePage, setActivePage] = useState("analysis");
  const [showGuide, setShowGuide] = useState(false);
  const [scenarios, setScenarios] = useState(sampleScenarios);
  const [selectedScenarioId, setSelectedScenarioId] = useState(sampleScenarios[0].id);

  const selectedScenario = scenarios.find((scenario) => scenario.id === selectedScenarioId) || scenarios[0];

  const addScenario = useCallback((scenario) => {
    setScenarios((current) => [scenario, ...current]);
    setSelectedScenarioId(scenario.id);
  }, []);

  const handleSaveScenario = useCallback(
    (scenario) => {
      addScenario(scenario);
      setActivePage("analysis");
    },
    [addScenario]
  );

  if (!hasStarted) {
    return (
      <main className="service-intro">
        <div className="service-intro-visual" aria-hidden="true">
          <svg className="route-build-map" viewBox="0 0 620 420" role="img" aria-label="도로 후보 노선 연결 애니메이션">
            <path className="route-grid-line" d="M70 80H540" />
            <path className="route-grid-line" d="M90 190H560" />
            <path className="route-grid-line" d="M70 310H520" />
            <path className="route-grid-line" d="M150 42V360" />
            <path className="route-grid-line" d="M320 58V380" />
            <path className="route-grid-line" d="M485 42V350" />
            <path className="route-shadow-path" d="M92 282 C160 224 206 216 260 232 S352 268 410 206 S496 104 548 122" />
            <path className="route-build-path" d="M92 282 C160 224 206 216 260 232 S352 268 410 206 S496 104 548 122" />
            <path className="route-build-path route-build-path-alt" d="M122 318 C214 314 266 294 318 250 S405 198 506 226" />
            <g className="route-build-node node-one">
              <circle cx="92" cy="282" r="17" />
              <circle cx="92" cy="282" r="6" />
            </g>
            <g className="route-build-node node-two">
              <circle cx="260" cy="232" r="17" />
              <circle cx="260" cy="232" r="6" />
            </g>
            <g className="route-build-node node-three">
              <circle cx="410" cy="206" r="17" />
              <circle cx="410" cy="206" r="6" />
            </g>
            <g className="route-build-node node-four">
              <circle cx="548" cy="122" r="17" />
              <circle cx="548" cy="122" r="6" />
            </g>
            <circle className="route-progress-marker" cx="0" cy="0" r="11" />
          </svg>
        </div>
        <section className="service-intro-content">
          <div className="service-brand">
            <span>1</span>
            <strong>ONESTEP</strong>
          </div>
          <h1>
            교통 수요 기반
            <span>도로·터널 후보 노선</span>
            <span>분석 서비스</span>
          </h1>
          <p>
            교통 수요 데이터를 기반으로 도로·터널 후보지를 자동 산정하고,
            <span>사업 초기 검토에 필요한 비용과 효과를 한 화면에서 확인합니다.</span>
          </p>
          <div className="service-intro-metrics" aria-label="서비스 핵심 기능">
            <span>OD 수요 분석</span>
            <span>후보 노선 산정</span>
            <span>공사비 검토</span>
          </div>
          <button className="service-start-button" type="button" onClick={() => setHasStarted(true)}>
            <Play size={19} fill="currentColor" />
            서비스 시작하기
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="prototype-shell">
      <Header activePage={activePage} onPageChange={setActivePage} onShowGuide={() => setShowGuide(true)} />
      {showGuide && <GuideDialog onClose={() => setShowGuide(false)} />}

      {activePage === "analysis" && (
        <AnalysisMvpPage scenarios={scenarios} selectedScenarioId={selectedScenarioId} />
      )}

      {activePage === "create" && <ScenarioCreatePage onSaveScenario={handleSaveScenario} />}
    </main>
  );
}

export default App;

