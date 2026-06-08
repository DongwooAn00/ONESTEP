import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BarChart3,
  Bell,
  BookOpen,
  Building2,
  FileUp,
  Heart,
  ListPlus,
  MapPin,
  Megaphone,
  MessageSquareText,
  MousePointer2,
  Play,
  Plus,
  RotateCcw,
  Save,
  Search,
  Trophy,
  X
} from "lucide-react";

const KAKAO_MAP_JS_KEY = import.meta.env.VITE_KAKAO_MAP_JS_KEY;
const DEFAULT_CENTER = { lat: 36.35, lng: 127.85 };
const DEFAULT_MAP_LEVEL = 13;

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

function RouteMap({ routes, draftRoute, onSelectPoint, helperText, compact = false }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const clickHandlerRef = useRef(null);
  const onSelectPointRef = useRef(onSelectPoint);
  const markersRef = useRef([]);
  const linesRef = useRef([]);
  const overlaysRef = useRef([]);
  const [loadError, setLoadError] = useState("");

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
    if (!window.kakao?.maps || !mapRef.current) {
      return;
    }

    const kakao = window.kakao;
    const map = mapRef.current;
    const allRoutes = [...routes, ...(draftRoute ? [draftRoute] : [])];
    const bounds = new kakao.maps.LatLngBounds();
    let hasBounds = false;

    markersRef.current.forEach((marker) => marker.setMap(null));
    linesRef.current.forEach((line) => line.setMap(null));
    overlaysRef.current.forEach((overlay) => overlay.setMap(null));
    markersRef.current = [];
    linesRef.current = [];
    overlaysRef.current = [];

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

        const position = new kakao.maps.LatLng(point.lat, point.lng);
        bounds.extend(position);
        hasBounds = true;

        const marker = new kakao.maps.Marker({ map, position, title });
        markersRef.current.push(marker);
      });

      if (route.start && route.end) {
        const path = [
          new kakao.maps.LatLng(route.start.lat, route.start.lng),
          new kakao.maps.LatLng(route.end.lat, route.end.lng)
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
          position: new kakao.maps.LatLng(
            (route.start.lat + route.end.lat) / 2,
            (route.start.lng + route.end.lng) / 2
          ),
          content: label,
          yAnchor: 1.4
        });
        overlaysRef.current.push(overlay);
      }
    });

    window.setTimeout(() => {
      map.relayout();
      if (hasBounds) {
        map.setBounds(bounds);
      }
    }, 80);
  }, [routes, draftRoute]);

  return (
    <div className={`live-map-wrap ${compact ? "compact-map" : ""}`}>
      <div ref={containerRef} className="live-map" />
      {loadError && (
        <div className="map-error">
          <strong>지도를 불러올 수 없습니다.</strong>
          <span>{loadError}</span>
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
    { id: "analysis", label: "기존 페이지", icon: BarChart3 },
    { id: "create", label: "시나리오 생성", icon: ListPlus },
    { id: "community", label: "커뮤니티", icon: MessageSquareText }
  ];

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">A</span>
        <div>
          <strong>ONESTEP</strong>
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
    </section>
  );
}

function ScenarioCreatePage({ onSaveScenario }) {
  const [scenarioName, setScenarioName] = useState("새 OD 시나리오");
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
      setMessage("OD 정보 입력 후 시나리오 추가 버튼을 누르세요.");
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
      setMessage("OD 정보 입력 후 시나리오 추가 버튼을 누르세요.");
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
    <section className="create-page">
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
          시나리오 종료
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

function App() {
  const [activePage, setActivePage] = useState("analysis");
  const [showGuide, setShowGuide] = useState(false);
  const [scenarios, setScenarios] = useState(sampleScenarios);
  const [selectedScenarioId, setSelectedScenarioId] = useState(sampleScenarios[0].id);
  const [communityPosts, setCommunityPosts] = useState(initialCommunityPosts);

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

  const handleCreatePost = useCallback((post) => {
    setCommunityPosts((current) => [post, ...current]);
  }, []);

  const handleLikePost = useCallback((postId) => {
    setCommunityPosts((current) =>
      current.map((post) => (post.id === postId ? { ...post, likes: post.likes + 1 } : post))
    );
  }, []);

  return (
    <main className="prototype-shell">
      <Header activePage={activePage} onPageChange={setActivePage} onShowGuide={() => setShowGuide(true)} />
      {showGuide && <GuideDialog onClose={() => setShowGuide(false)} />}

      {activePage === "analysis" && (
        <AnalysisPage
          scenarios={scenarios}
          selectedScenario={selectedScenario}
          selectedScenarioId={selectedScenarioId}
          onSelectScenario={setSelectedScenarioId}
          onImportScenario={addScenario}
          onGoCreate={() => setActivePage("create")}
        />
      )}

      {activePage === "create" && <ScenarioCreatePage onSaveScenario={handleSaveScenario} />}

      {activePage === "community" && (
        <CommunityPage posts={communityPosts} onCreatePost={handleCreatePost} onLikePost={handleLikePost} />
      )}
    </main>
  );
}

export default App;
