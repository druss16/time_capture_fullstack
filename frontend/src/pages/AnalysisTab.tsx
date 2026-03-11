/**
 * AIAnalysisTab.tsx
 * Drop this into ExecutiveDashboard as the 5th tab.
 *
 * Usage inside ExecutiveDashboard:
 *   import AIAnalysisTab from "./AIAnalysisTab";
 *   ...
 *   {tab === "analysis" && <AIAnalysisTab data={data} apiBase={apiBase} />}
 *
 * Also add to tab list:
 *   {(["overview","clients","billing","staff","analysis"] as const).map(...)}
 */

import { useState, CSSProperties } from "react";

// ─── Design tokens (mirror ExecutiveDashboard) ────────────────────────────────
const C = {
  navy:    "#0d1b2a",
  navyMid: "#122035",
  navyLt:  "#1a2e45",
  gold:    "#c9a84c",
  goldLt:  "#e2c97e",
  teal:    "#2dd4bf",
  rose:    "#fb7185",
  amber:   "#f59e0b",
  slate:   "#94a3b8",
  white:   "#f1f5f9",
  border:  "rgba(201,168,76,0.15)",
} as const;

function _getToken() {
  return localStorage.getItem("auth_token") || localStorage.getItem("tt_auth_token") || localStorage.getItem("authToken") || localStorage.getItem("token") || "";
}

interface Analysis {
  headline: string;
  score: number;
  wins:     string[];
  warnings: string[];
  actions:  string[];
}

interface AIAnalysisTabProps {
  data: { meta: Record<string, unknown>; kpis: Record<string, unknown> } | null;
  apiBase?: string;
}

// ─── Health score ring ────────────────────────────────────────────────────────
function ScoreRing({ score }: { score: number }) {
  const radius    = 54;
  const circ      = 2 * Math.PI * radius;
  const fill      = (score / 100) * circ;
  const color     = score >= 85 ? C.teal : score >= 70 ? C.gold : score >= 50 ? C.amber : C.rose;
  const label     = score >= 85 ? "Healthy" : score >= 70 ? "Solid" : score >= 50 ? "At Risk" : "Critical";

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
      <svg width={130} height={130} viewBox="0 0 130 130">
        {/* track */}
        <circle cx={65} cy={65} r={radius} fill="none" stroke={C.navyLt} strokeWidth={10} />
        {/* fill */}
        <circle
          cx={65} cy={65} r={radius} fill="none"
          stroke={color} strokeWidth={10}
          strokeDasharray={`${fill} ${circ}`}
          strokeLinecap="round"
          transform="rotate(-90 65 65)"
          style={{ transition: "stroke-dasharray 1s ease" }}
        />
        <text x={65} y={60} textAnchor="middle" fill={color} fontSize={28} fontWeight={700} fontFamily="'Cormorant Garamond', serif">{score}</text>
        <text x={65} y={80} textAnchor="middle" fill={C.slate} fontSize={12} fontFamily="'DM Mono', monospace">{label}</text>
      </svg>
      <span style={{ fontSize: 11, color: C.slate, letterSpacing: 1 }}>FIRM HEALTH SCORE</span>
    </div>
  );
}

// ─── Single analysis column ───────────────────────────────────────────────────
interface ColumnProps {
  icon:    string;
  label:   string;
  bullets: string[];
  accent:  string;
  bg:      string;
}
function AnalysisColumn({ icon, label, bullets, accent, bg }: ColumnProps) {
  return (
    <div style={{ flex: 1, background: bg, border: `1px solid ${accent}33`, borderRadius: 12, padding: "24px 20px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
        <span style={{ fontSize: 22 }}>{icon}</span>
        <span style={{ fontSize: 13, letterSpacing: 2, color: accent, textTransform: "uppercase" as const, fontFamily: "'DM Mono', monospace" }}>{label}</span>
      </div>
      <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column" as const, gap: 14 }}>
        {bullets.map((b, i) => (
          <li key={i} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
            <span style={{ color: accent, fontSize: 16, lineHeight: 1.4, flexShrink: 0 }}>▸</span>
            <span style={{ fontSize: 14, color: C.white, lineHeight: 1.6 }}>{b}</span>
          </li>
        ))}
        {bullets.length === 0 && (
          <li style={{ color: C.slate, fontSize: 13, fontStyle: "italic" }}>Nothing notable here.</li>
        )}
      </ul>
    </div>
  );
}

// ─── Skeleton loader ──────────────────────────────────────────────────────────
function AnalysisSkeleton() {
  const bar = (w: string, opacity = 1): CSSProperties => ({
    height: 14, borderRadius: 7, background: C.navyLt, width: w,
    animation: "pulse 1.5s ease-in-out infinite", opacity,
  });
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20, padding: "32px 0" }}>
      <style>{`@keyframes pulse { 0%,100%{opacity:.4} 50%{opacity:.9} }`}</style>
      <div style={{ display: "flex", gap: 16 }}>
        {[1,2,3].map((k) => (
          <div key={k} style={{ flex: 1, background: C.navyMid, border: `1px solid ${C.border}`, borderRadius: 12, padding: 24, display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={bar("40%")} />
            {[0,1,2].map((j) => <div key={j} style={bar(`${60 + j * 10}%`, 0.7)} />)}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function AIAnalysisTab({ data, apiBase = "https://timetracker-api-k375.onrender.com" }: AIAnalysisTabProps) {
  const [analysis, setAnalysis]   = useState<Analysis | null>(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [lastRun, setLastRun]     = useState<Date | null>(null);

  const runAnalysis = async () => {
    if (!data) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/analytics/ai-analysis/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${_getToken()}`,
        },
        body: JSON.stringify({ kpis: data.kpis, meta: data.meta }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { error?: string };
        throw new Error(body.error || `HTTP ${res.status}`);
      }
      const json = await res.json() as { analysis: Analysis };
      setAnalysis(json.analysis);
      setLastRun(new Date());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Analysis failed.");
    } finally {
      setLoading(false);
    }
  };

  const hasData = !!data?.kpis;

  return (
    <div style={{ paddingBottom: 48 }}>

      {/* ── Hero CTA ── */}
      {!analysis && !loading && (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          padding: "64px 32px", textAlign: "center", gap: 24,
          background: `radial-gradient(ellipse at center, ${C.navyMid} 0%, ${C.navy} 70%)`,
          border: `1px solid ${C.border}`, borderRadius: 16, marginBottom: 24,
        }}>
          <div style={{ fontSize: 52 }}>🧠</div>
          <h2 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 32, color: C.gold, margin: 0 }}>
            AI Firm Analysis
          </h2>
          <p style={{ color: C.slate, fontSize: 15, maxWidth: 440, lineHeight: 1.7, margin: 0 }}>
            Instantly see what's working, what's hurting you, and exactly what to do about it — based on your real data.
          </p>
          {!hasData && (
            <p style={{ color: C.rose, fontSize: 13 }}>⚠ Dashboard data hasn't loaded yet. Switch to Overview first, then come back.</p>
          )}
          <button
            onClick={runAnalysis}
            disabled={!hasData || loading}
            style={{
              padding: "14px 40px", borderRadius: 8,
              background: hasData ? C.gold : C.navyLt,
              color: hasData ? C.navy : C.slate,
              border: "none", cursor: hasData ? "pointer" : "not-allowed",
              fontSize: 15, fontWeight: 700, fontFamily: "'DM Mono', monospace",
              letterSpacing: 1, transition: "all 0.2s",
              boxShadow: hasData ? `0 0 32px ${C.gold}44` : "none",
            }}
            onMouseEnter={(e) => { if (hasData) (e.currentTarget as HTMLButtonElement).style.background = C.goldLt; }}
            onMouseLeave={(e) => { if (hasData) (e.currentTarget as HTMLButtonElement).style.background = C.gold; }}
          >
            Analyze My Firm
          </button>
          {error && <p style={{ color: C.rose, fontSize: 13, marginTop: 8 }}>⚠ {error}</p>}
        </div>
      )}

      {/* ── Loading state ── */}
      {loading && (
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 24, padding: "18px 24px", background: C.navyMid, border: `1px solid ${C.border}`, borderRadius: 12 }}>
            <div style={{ width: 20, height: 20, border: `2px solid ${C.gold}`, borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            <span style={{ color: C.slate, fontSize: 14 }}>Analyzing your firm data with GPT-4o-mini…</span>
          </div>
          <AnalysisSkeleton />
        </div>
      )}

      {/* ── Results ── */}
      {analysis && !loading && (
        <div>
          {/* Header bar */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 28, flexWrap: "wrap", gap: 16 }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, color: C.slate, letterSpacing: 1.5, textTransform: "uppercase", marginBottom: 8 }}>AI Summary</div>
              <p style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 22, color: C.white, margin: 0, lineHeight: 1.4, maxWidth: 620 }}>
                "{analysis.headline}"
              </p>
              {lastRun && <div style={{ fontSize: 11, color: C.slate, marginTop: 10 }}>Last analyzed at {lastRun.toLocaleTimeString()}</div>}
            </div>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
              <ScoreRing score={analysis.score} />
              <button
                onClick={runAnalysis}
                style={{ background: "transparent", border: `1px solid ${C.border}`, color: C.slate, borderRadius: 6, padding: "6px 16px", cursor: "pointer", fontSize: 11, fontFamily: "'DM Mono', monospace" }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.borderColor = C.gold; (e.currentTarget as HTMLButtonElement).style.color = C.gold; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.borderColor = C.border; (e.currentTarget as HTMLButtonElement).style.color = C.slate; }}
              >↻ Re-analyze</button>
            </div>
          </div>

          {/* Three columns */}
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <AnalysisColumn
              icon="✅"
              label="What's Working"
              bullets={analysis.wins}
              accent={C.teal}
              bg="rgba(45,212,191,0.05)"
            />
            <AnalysisColumn
              icon="⚠️"
              label="What's Hurting You"
              bullets={analysis.warnings}
              accent={C.amber}
              bg="rgba(245,158,11,0.05)"
            />
            <AnalysisColumn
              icon="🎯"
              label="Do This Now"
              bullets={analysis.actions}
              accent={C.rose}
              bg="rgba(251,113,133,0.05)"
            />
          </div>

          {/* Disclaimer */}
          <p style={{ textAlign: "center", color: C.slate, fontSize: 11, marginTop: 32, lineHeight: 1.8 }}>
            AI analysis is generated by GPT-4o-mini based on your firm's data.
            Review findings with your leadership team before acting on recommendations.
          </p>
        </div>
      )}
    </div>
  );
}