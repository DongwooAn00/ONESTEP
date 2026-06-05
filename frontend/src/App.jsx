import { useCallback, useEffect, useRef, useState } from "react";
import {
  BarChart3,
  Bell,
  BookOpen,
  ChevronDown,
  CircleHelp,
  Download,
  MapPin,
  Play,
  RotateCcw,
  Share2,
  Trophy,
  UserRound
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

const candidates = [
  {
    id: 1,
    name: "후보 1",
    kind: "도로 추천",
    tag: "우선 검토",
    score: 86.7,
    time: "34분",
    cost: "2,350억원",
    type: "신설 도로",
    color: "#0b7ff3",
    description: "기존 도로망을 최대한 활용하며, 높은 편익 대비 비용 효율을 보입니다."
  },
  {
    id: 2,
    name: "후보 2",
    kind: "터널 추천",
    tag: "직선 경로",
    score: 72.1,
    time: "41분",
    cost: "4,980억원",
    type: "터널 신설",
    color: "#7f57d9",
    description: "직선형 터널로 최단 시간 경로 확보가 가능하나, 공사비가 높습니다."
  },
  {
    id: 3,
    name: "후보 3",
    kind: "도로 추천",
    tag: "비용 절감",
    score: 61.3,
    time: "22분",
    cost: "1,820억원",
    type: "신설 도로",
    color: "#14a8b5",
    description: "남측 우회 경로로 공사비는 낮으나, 거리 및 시간 단축 효과가 낮습니다."
  }
];

const comparisonRows = [
  ["후보 1", "5,420", "2,350", "2.31", "3,070"],
  ["후보 2", "6,210", "4,980", "1.25", "1,230"],
  ["후보 3", "3,620", "1,820", "1.99", "1,540"]
];

function formatPoint(point) {
  if (!point) {
    return "지도에서 선택";
  }

  if (point.label) {
    return point.label;
  }

  return `${point.lat.toFixed(5)}, ${point.lng.toFixed(5)}`;
}

function InputField({ icon, label, value, unit }) {
  return (
    <label className="field">
      <span>{label}</span>
      <div className="field-control">
        {icon}
        <input readOnly value={value} />
        {unit && <em>{unit}</em>}
        <ChevronDown size={16} aria-hidden="true" />
      </div>
    </label>
  );
}

function LocationSearchField({
  icon,
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
      <label htmlFor={`${label}-input`}>{label}</label>
      <div className="location-search-control">
        {icon}
        <input
          id={`${label}-input`}
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

function CandidateCard({ candidate, active }) {
  return (
    <article className={`candidate-card ${active ? "active" : ""}`}>
      <header className="candidate-head">
        <div>
          <span className="candidate-index" style={{ backgroundColor: candidate.color }}>
            {candidate.id}
          </span>
          <strong>{candidate.name}</strong>
          <small style={{ color: candidate.color }}>{candidate.kind}</small>
          {candidate.tag && <mark>{candidate.tag}</mark>}
        </div>
        {active && <Trophy size={22} aria-hidden="true" />}
      </header>

      <div className="candidate-stats">
        <span>
          경제성 점수
          <strong>
            {candidate.score}
            <small>/100</small>
          </strong>
        </span>
        <span>
          예상 시간 단축
          <strong>{candidate.time}</strong>
        </span>
        <span>
          추정 공사비
          <strong>{candidate.cost}</strong>
        </span>
        <span>
          추천 유형
          <strong>{candidate.type}</strong>
        </span>
      </div>
      <p>{candidate.description}</p>
    </article>
  );
}

function KakaoRouteMap({ startPoint, endPoint, onSelectPoint, onResetPoints }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markersRef = useRef({ start: null, end: null });
  const routeLineRef = useRef(null);
  const clickHandlerRef = useRef(null);
  const onSelectPointRef = useRef(onSelectPoint);
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

        const center = new kakao.maps.LatLng(DEFAULT_CENTER.lat, DEFAULT_CENTER.lng);
        const map = new kakao.maps.Map(containerRef.current, {
          center,
          level: DEFAULT_MAP_LEVEL
        });

        map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);
        map.addControl(new kakao.maps.MapTypeControl(), kakao.maps.ControlPosition.TOPRIGHT);

        const clickHandler = (mouseEvent) => {
          const latLng = mouseEvent.latLng;
          onSelectPointRef.current({ lat: latLng.getLat(), lng: latLng.getLng() });
        };

        kakao.maps.event.addListener(map, "click", clickHandler);
        mapRef.current = map;
        clickHandlerRef.current = clickHandler;
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

    const syncMarker = (key, point, title) => {
      if (!point) {
        if (markersRef.current[key]) {
          markersRef.current[key].setMap(null);
          markersRef.current[key] = null;
        }
        return;
      }

      const position = new kakao.maps.LatLng(point.lat, point.lng);

      if (!markersRef.current[key]) {
        markersRef.current[key] = new kakao.maps.Marker({ map, position, title });
      } else {
        markersRef.current[key].setPosition(position);
      }
    };

    syncMarker("start", startPoint, "출발점");
    syncMarker("end", endPoint, "도착점");

    if (routeLineRef.current) {
      routeLineRef.current.setMap(null);
      routeLineRef.current = null;
    }

    if (startPoint && endPoint) {
      const path = [
        new kakao.maps.LatLng(startPoint.lat, startPoint.lng),
        new kakao.maps.LatLng(endPoint.lat, endPoint.lng)
      ];

      routeLineRef.current = new kakao.maps.Polyline({
        map,
        path,
        strokeWeight: 6,
        strokeColor: "#0878ec",
        strokeOpacity: 0.9,
        strokeStyle: "solid"
      });

      const bounds = new kakao.maps.LatLngBounds();
      path.forEach((latLng) => bounds.extend(latLng));
      map.setBounds(bounds);
    } else if (startPoint) {
      map.panTo(new kakao.maps.LatLng(startPoint.lat, startPoint.lng));
    }
  }, [startPoint, endPoint]);

  return (
    <div className="live-map-wrap">
      <div ref={containerRef} className="live-map" />
      {loadError && (
        <div className="map-error">
          <strong>지도를 불러올 수 없습니다.</strong>
          <span>{loadError}</span>
        </div>
      )}
      <div className="map-selection-card">
        <strong>{startPoint ? (endPoint ? "출발/도착 선택 완료" : "도착점을 선택하세요") : "출발점을 선택하세요"}</strong>
        <span>지도 위 원하는 위치를 클릭하세요.</span>
        {startPoint && <small>출발: {formatPoint(startPoint)}</small>}
        {endPoint && <small>도착: {formatPoint(endPoint)}</small>}
        <button type="button" onClick={onResetPoints}>
          선택 초기화
        </button>
      </div>
    </div>
  );
}

function App() {
  const [startPoint, setStartPoint] = useState(null);
  const [endPoint, setEndPoint] = useState(null);
  const [selectionStep, setSelectionStep] = useState("start");
  const [locationSearch, setLocationSearch] = useState({
    start: { query: "", results: [], message: "" },
    end: { query: "", results: [], message: "" }
  });

  const handleSelectPoint = useCallback((point) => {
    if (selectionStep === "start") {
      setStartPoint(point);
      setEndPoint(null);
      setSelectionStep("end");
      setLocationSearch((current) => ({
        ...current,
        start: { query: formatPoint(point), results: [], message: "지도에서 선택됨" },
        end: { query: "", results: [], message: "" }
      }));
      return;
    }

    setEndPoint(point);
    setSelectionStep("start");
    setLocationSearch((current) => ({
      ...current,
      end: { query: formatPoint(point), results: [], message: "지도에서 선택됨" }
    }));
  }, [selectionStep]);

  const handleResetPoints = useCallback(() => {
    setStartPoint(null);
    setEndPoint(null);
    setSelectionStep("start");
    setLocationSearch({
      start: { query: "", results: [], message: "" },
      end: { query: "", results: [], message: "" }
    });
  }, []);

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
      [target]: { ...current[target], results: [], message: "검색 중..." }
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
      setStartPoint(point);
      setEndPoint(null);
      setSelectionStep("end");
    } else {
      setEndPoint(point);
      setSelectionStep("start");
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

  return (
    <main className="prototype-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">A</span>
          <strong>한걸음 AI</strong>
          <p>도로 · 터널 후보지 경제성 분석 서비스</p>
        </div>
        <nav className="top-actions" aria-label="상단 메뉴">
          <button type="button">
            <BookOpen size={18} />
            사용 가이드
          </button>
          <button className="icon-button" type="button" aria-label="알림">
            <Bell size={19} />
            <span>3</span>
          </button>
          <button type="button">
            <UserRound size={18} />
            홍길동
            <ChevronDown size={15} />
          </button>
        </nav>
      </header>

      <section className="dashboard">
        <aside className="input-panel">
          <h2>
            <BarChart3 size={18} />
            분석 입력
          </h2>

          <LocationSearchField
            label="출발 지역"
            point={startPoint}
            query={locationSearch.start.query}
            results={locationSearch.start.results}
            message={locationSearch.start.message}
            placeholder="출발지 검색 또는 지도 선택"
            icon={<MapPin className="pin start" size={17} />}
            onQueryChange={(query) => handleLocationQueryChange("start", query)}
            onSearch={(event) => handleLocationSearch("start", event)}
            onSelectResult={(result) => handleSelectLocationResult("start", result)}
          />
          <LocationSearchField
            label="도착 지역"
            point={endPoint}
            query={locationSearch.end.query}
            results={locationSearch.end.results}
            message={locationSearch.end.message}
            placeholder="도착지 검색 또는 지도 선택"
            icon={<MapPin className="pin end" size={17} />}
            onQueryChange={(query) => handleLocationQueryChange("end", query)}
            onSearch={(event) => handleLocationSearch("end", event)}
            onSelectResult={(result) => handleSelectLocationResult("end", result)}
          />
          <InputField label="물동량 (톤/연)" value="3,500,000" unit="톤/연" icon={<CircleHelp size={16} />} />
          <InputField label="교통량 (대/일)" value="18,500" unit="대/일" icon={<CircleHelp size={16} />} />
          <InputField label="분석 범위" value="15 km" icon={<CircleHelp size={16} />} />

          <button className="primary-action" type="button">
            <Play size={18} fill="currentColor" />
            후보 분석 시작
          </button>
          <button className="secondary-action" type="button">
            <RotateCcw size={17} />
            초기화
          </button>

          <div className="ai-note">
            <span>AI</span>
            <p>AI가 지형, 교통, 비용, 수요 데이터를 종합 분석해 최적 도로 · 터널 후보를 추천합니다.</p>
          </div>
        </aside>

        <section className="main-panel">
          <section className="map-card" aria-label="후보 노선 지도">
            <div className="map-toolbar">
              <span className="legend candidate"></span>선택 경로
              <span className="legend tunnel"></span>분석 후보
            </div>

            <KakaoRouteMap
              startPoint={startPoint}
              endPoint={endPoint}
              onSelectPoint={handleSelectPoint}
              onResetPoints={handleResetPoints}
            />
          </section>

          <section className="comparison">
            <article className="chart-card">
              <h3>후보별 비교 분석</h3>
              <div className="bar-list">
                {candidates.map((candidate) => (
                  <div className="bar-row" key={candidate.id}>
                    <span>{candidate.name} ({candidate.type.includes("터널") ? "터널" : "도로"})</span>
                    <div>
                      <i style={{ width: `${candidate.score}%`, backgroundColor: candidate.color }}></i>
                    </div>
                    <strong>{candidate.score}</strong>
                  </div>
                ))}
              </div>
              <div className="axis">
                <span>0</span>
                <span>20</span>
                <span>40</span>
                <span>60</span>
                <span>80</span>
                <span>100</span>
              </div>
            </article>

            <article className="table-card">
              <table>
                <thead>
                  <tr>
                    <th></th>
                    <th>총 편익<br />(억원)</th>
                    <th>총 비용<br />(억원)</th>
                    <th>B/C<br />편익/비용</th>
                    <th>순현재가치<br />NPV, 억원</th>
                  </tr>
                </thead>
                <tbody>
                  {comparisonRows.map((row, index) => (
                    <tr key={row[0]}>
                      <td>
                        <span style={{ backgroundColor: candidates[index].color }}></span>
                      </td>
                      {row.slice(1).map((cell) => (
                        <td key={cell}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </article>
          </section>
        </section>

        <aside className="result-panel">
          <div className="panel-title">
            <h2>
              <BarChart3 size={19} />
              분석 결과
            </h2>
            <button type="button">상세 비교 보기</button>
          </div>

          {candidates.map((candidate, index) => (
            <CandidateCard candidate={candidate} active={index === 0} key={candidate.id} />
          ))}

          <div className="score-note">
            <CircleHelp size={17} />
            경제성 점수 = 편익(B/C) 기반 종합 점수 (100점 만점)
          </div>

          <article className="ai-summary">
            <h3>AI 종합 의견</h3>
            <p>
              <strong>후보 1(도로)</strong>이 경제성, 시간 단축, 공사비 측면에서 가장 균형 잡힌 최적 대안으로 분석되었습니다.
            </p>
            <button className="primary-action" type="button">
              <Download size={18} />
              리포트 다운로드
            </button>
            <button className="secondary-action" type="button">
              <Share2 size={17} />
              분석 결과 공유
            </button>
          </article>
        </aside>
      </section>
    </main>
  );
}

export default App;
