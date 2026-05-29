import { Calculator, FileText, TrendingUp } from "lucide-react";

const metrics = [
  { label: "B/C", value: "1.18", tone: "positive" },
  { label: "NPV", value: "327억 원", tone: "positive" },
  { label: "IRR", value: "6.4%", tone: "neutral" }
];

function App() {
  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">O</span>
          <div>
            <strong>ONESTEP</strong>
            <small>도로 터널 경제성 분석</small>
          </div>
        </div>

        <nav className="nav-list" aria-label="주요 메뉴">
          <a className="active" href="#scenario">
            <Calculator size={18} />
            시나리오
          </a>
          <a href="#results">
            <TrendingUp size={18} />
            분석 결과
          </a>
          <a href="#reports">
            <FileText size={18} />
            리포트
          </a>
        </nav>
      </aside>

      <section className="workspace">
        <header className="page-header">
          <div>
            <h1>도로 터널 건설 경제성 분석</h1>
            <p>사업 조건, 비용, 편익을 입력하고 경제성 지표를 검토합니다.</p>
          </div>
          <button type="button">분석 실행</button>
        </header>

        <section id="scenario" className="input-grid">
          <label>
            터널 연장(km)
            <input type="number" defaultValue="3.2" min="0" step="0.1" />
          </label>
          <label>
            총사업비(억 원)
            <input type="number" defaultValue="4200" min="0" />
          </label>
          <label>
            운영 기간(년)
            <input type="number" defaultValue="30" min="1" />
          </label>
          <label>
            할인율(%)
            <input type="number" defaultValue="4.5" min="0" step="0.1" />
          </label>
        </section>

        <section id="results" className="metric-grid">
          {metrics.map((metric) => (
            <article className="metric-card" data-tone={metric.tone} key={metric.label}>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
            </article>
          ))}
        </section>
      </section>
    </main>
  );
}

export default App;
