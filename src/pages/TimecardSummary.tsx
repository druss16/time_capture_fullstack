// src/pages/TimecardSummary.tsx
import { useEffect, useMemo, useState } from "react";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

type TaskRow = { task_name: string; total_hours: number; categories: Record<string, number>; block_ids?: number[]; };
type ClientRow = { client_name: string; total_hours: number; categories: Record<string, number>; block_ids?: number[]; tasks?: TaskRow[]; };
type SummaryResp = { date: string; user: string; total_hours: number; clients: ClientRow[]; };

const fmtHours = (n: number) => (Math.round((n || 0) * 100) / 100).toFixed(2);
const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const displayClient = (name?: string) => {
  const n = (name || "").trim();
  if (!n || n.toLowerCase() === "unknown") return "Unassigned";
  return n;
};

export default function TimecardSummary() {
  const [data, setData] = useState<SummaryResp | null>(null);
  const [busy, setBusy] = useState(false);
  const [user, setUser] = useState<string>("");
  const [date, setDate] = useState<string>(todayIso());
  const [err, setErr] = useState<string | null>(null);
  const [whoami, setWhoami] = useState<string>("");

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/whoami/`, { credentials: "include" });
        if (r.ok) {
          const j = (await r.json()) as { username?: string };
          const name = (j?.username || "").trim();
          setWhoami(name);
          setUser((u) => (u.trim() ? u : name));
        }
      } catch {/* ignore */}
    })();
  }, []);

  const load = async () => {
    setBusy(true);
    setErr(null);
    try {
      const url = new URL(`${API_BASE}/timecards/summary/day/`);
      url.searchParams.set("date", date);
      if (user.trim()) url.searchParams.set("user", user.trim());

      const r = await fetch(url.toString(), { credentials: "include" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as SummaryResp;

      const clients = (Array.isArray(j.clients) ? j.clients : []).map((c) => ({
        ...c,
        client_name: displayClient(c.client_name),
        tasks: Array.isArray((c as any).tasks) ? (c as any).tasks : [],
      }));

      clients.sort((a, b) => {
        const au = a.client_name === "Unassigned";
        const bu = b.client_name === "Unassigned";
        if (au && !bu) return 1;
        if (!au && bu) return -1;
        return b.total_hours - a.total_hours;
      });

      setData({
        date: j.date || date,
        user: typeof j.user === "string" ? j.user : user,
        total_hours: Number(j.total_hours || 0),
        clients,
      });
    } catch (e: any) {
      console.error(e);
      setErr(e?.message || "Failed to load.");
      setData({ date, user, total_hours: 0, clients: [] });
    } finally {
      setBusy(false);
    }
  };

  const generate = async (status: "draft" | "pending" = "pending") => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch(`${API_BASE}/timecards/generate/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ date, user, status }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await r.json();
      await load();
    } catch (e: any) {
      console.error(e);
      setErr(e?.message || "Failed to generate.");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [date, user]);

  const headerUser = useMemo(() => {
    return user?.trim() ? user.trim() : (data?.user?.trim() ? data.user : "All Users");
  }, [user, data?.user]);

  return (
    <>
      <style>{`
        .tc-container {
          min-height: 100vh;
          background: #f8f9fa;
          padding: 2rem 1rem;
        }
        .tc-wrapper {
          max-width: 1200px;
          margin: 0 auto;
        }
        .tc-card {
          background: white;
          border-radius: 8px;
          box-shadow: 0 1px 3px rgba(0,0,0,0.1);
          border: 1px solid #e5e7eb;
          margin-bottom: 1.5rem;
        }
        .tc-card-body {
          padding: 1.5rem;
        }
        .tc-title {
          font-size: 1.875rem;
          font-weight: 700;
          color: #111827;
          margin: 0 0 0.5rem 0;
        }
        .tc-subtitle {
          font-size: 0.875rem;
          color: #6b7280;
          margin: 0;
        }
        .tc-user-badge {
          background: #f3f4f6;
          padding: 0.375rem 0.75rem;
          border-radius: 4px;
          font-size: 0.875rem;
          display: inline-block;
        }
        .tc-form-group {
          display: inline-block;
          margin-right: 1rem;
          margin-bottom: 1rem;
        }
        .tc-form-label {
          display: block;
          font-size: 0.75rem;
          font-weight: 600;
          color: #374151;
          margin-bottom: 0.25rem;
          text-transform: uppercase;
          letter-spacing: 0.025em;
        }
        .tc-form-input {
          border: 1px solid #d1d5db;
          border-radius: 4px;
          padding: 0.5rem 0.75rem;
          font-size: 0.875rem;
          width: 220px;
        }
        .tc-form-input:focus {
          outline: 2px solid #3b82f6;
          outline-offset: 0;
          border-color: #3b82f6;
        }
        .tc-btn {
          padding: 0.5rem 1rem;
          border-radius: 4px;
          font-size: 0.875rem;
          font-weight: 500;
          cursor: pointer;
          border: 1px solid #d1d5db;
          background: white;
          color: #374151;
          transition: all 0.15s;
          margin-right: 0.5rem;
          margin-bottom: 0.5rem;
        }
        .tc-btn:hover:not(:disabled) {
          background: #f9fafb;
        }
        .tc-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .tc-btn-primary {
          background: #2563eb;
          color: white;
          border-color: #2563eb;
        }
        .tc-btn-primary:hover:not(:disabled) {
          background: #1d4ed8;
        }
        .tc-alert-error {
          background: #fef2f2;
          border: 1px solid #fecaca;
          color: #991b1b;
          padding: 0.75rem 1rem;
          border-radius: 4px;
          font-size: 0.875rem;
          margin-top: 1rem;
        }
        .tc-summary-header {
          background: #f9fafb;
          border-bottom: 1px solid #e5e7eb;
          padding: 1.25rem 1.5rem;
          display: grid;
          grid-template-columns: 1fr 1fr auto;
          gap: 1.5rem;
          align-items: center;
        }
        .tc-summary-label {
          font-size: 0.625rem;
          color: #6b7280;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          margin-bottom: 0.25rem;
        }
        .tc-summary-value {
          font-size: 1.125rem;
          font-weight: 700;
          color: #111827;
        }
        .tc-total-hours {
          background: #2563eb;
          color: white;
          padding: 0.75rem 1.5rem;
          border-radius: 6px;
        }
        .tc-total-hours .tc-summary-label {
          color: rgba(255,255,255,0.9);
        }
        .tc-total-hours .tc-summary-value {
          color: white;
          font-size: 1.5rem;
        }
        .tc-client-section {
          padding: 1.25rem 1.5rem;
          border-bottom: 1px solid #e5e7eb;
        }
        .tc-client-section:last-child {
          border-bottom: none;
        }
        .tc-client-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: 0.75rem;
        }
        .tc-client-name {
          font-size: 1.25rem;
          font-weight: 600;
          color: #111827;
          margin: 0;
        }
        .tc-client-meta {
          font-size: 0.75rem;
          color: #6b7280;
          margin-top: 0.25rem;
        }
        .tc-client-hours {
          font-size: 1.25rem;
          font-weight: 700;
          color: #111827;
        }
        .tc-category-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
          margin-bottom: 0.75rem;
        }
        .tc-category-tag {
          display: inline-flex;
          align-items: center;
          gap: 0.5rem;
          background: #eff6ff;
          border: 1px solid #bfdbfe;
          color: #1e40af;
          padding: 0.25rem 0.75rem;
          border-radius: 9999px;
          font-size: 0.75rem;
          font-weight: 500;
        }
        .tc-category-hours {
          font-weight: 600;
        }
        .tc-task-breakdown {
          margin-top: 0.75rem;
          border: 1px solid #e5e7eb;
          border-radius: 4px;
          overflow: hidden;
        }
        .tc-task-breakdown-header {
          background: #f9fafb;
          padding: 0.5rem 0.75rem;
          border-bottom: 1px solid #e5e7eb;
        }
        .tc-task-breakdown-title {
          font-size: 0.75rem;
          font-weight: 600;
          color: #6b7280;
          text-transform: uppercase;
          margin: 0;
        }
        .tc-task-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 0.625rem 0.75rem;
          border-bottom: 1px solid #f3f4f6;
        }
        .tc-task-row:last-child {
          border-bottom: none;
        }
        .tc-task-name {
          font-size: 0.875rem;
          color: #374151;
        }
        .tc-task-hours {
          font-size: 0.875rem;
          font-weight: 600;
          color: #111827;
        }
        .tc-empty-state {
          padding: 3rem;
          text-align: center;
        }
        .tc-empty-state-title {
          color: #6b7280;
          font-weight: 500;
          margin: 0 0 0.5rem 0;
        }
        .tc-empty-state-subtitle {
          font-size: 0.875rem;
          color: #9ca3af;
          margin: 0;
        }
        .tc-header-flex {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          flex-wrap: wrap;
          gap: 1rem;
          margin-bottom: 1.5rem;
        }
        .tc-controls {
          margin-top: 1.5rem;
        }
        @media (max-width: 768px) {
          .tc-summary-header {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
      <div className="tc-container">
        <div className="tc-wrapper">
          {/* Header */}
          <div className="tc-card">
            <div className="tc-card-body">
              <div className="tc-header-flex">
                <div>
                  <h1 className="tc-title">Timecard Summary</h1>
                  <p className="tc-subtitle">Client time allocation with category breakdowns</p>
                </div>
                {whoami?.trim() && (
                  <div className="tc-user-badge">
                    Signed in as: <strong>{whoami}</strong>
                  </div>
                )}
              </div>

              {/* Controls */}
              <div className="tc-controls">
                <div className="tc-form-group">
                  <label className="tc-form-label">Date</label>
                  <input 
                    type="date" 
                    className="tc-form-input" 
                    value={date} 
                    onChange={(e) => setDate(e.target.value)} 
                  />
                </div>

                <div className="tc-form-group">
                  <label className="tc-form-label">User</label>
                  <input
                    type="text"
                    className="tc-form-input"
                    placeholder="All users"
                    value={user}
                    onChange={(e) => setUser(e.target.value)}
                    list="user-hints"
                  />
                  <datalist id="user-hints">{whoami ? <option value={whoami} /> : null}</datalist>
                </div>

                <div className="tc-form-group" style={{marginLeft: 'auto'}}>
                  <label className="tc-form-label">&nbsp;</label>
                  <div>
                    <button 
                      onClick={load} 
                      className="tc-btn" 
                      disabled={busy}
                    >
                      Refresh
                    </button>
                    <button 
                      onClick={() => generate("draft")} 
                      className="tc-btn" 
                      disabled={busy}
                    >
                      Save as Draft
                    </button>
                    <button 
                      onClick={() => generate("pending")} 
                      className="tc-btn tc-btn-primary" 
                      disabled={busy}
                    >
                      Save as Pending
                    </button>
                  </div>
                </div>
              </div>

              {/* Status Messages */}
              {busy && <div style={{marginTop: '1rem', fontSize: '0.875rem', color: '#2563eb'}}>Loading...</div>}
              {err && <div className="tc-alert-error">{err}</div>}
            </div>
          </div>

          {/* Summary Card */}
          {!!data && (
            <div className="tc-card">
              {/* Summary Header */}
              <div className="tc-summary-header">
                <div className="tc-summary-field">
                  <div className="tc-summary-label">Summary For</div>
                  <div className="tc-summary-value">{headerUser}</div>
                </div>
                <div className="tc-summary-field">
                  <div className="tc-summary-label">Date</div>
                  <div className="tc-summary-value">{data.date}</div>
                </div>
                <div className="tc-total-hours">
                  <div className="tc-summary-label">Total Hours</div>
                  <div className="tc-summary-value">{fmtHours(data.total_hours)}</div>
                </div>
              </div>

              {/* Client List */}
              <div>
                {data.clients.map((c) => (
                  <div key={`${c.client_name}-${fmtHours(c.total_hours)}`} className="tc-client-section">
                    <div className="tc-client-header">
                      <div>
                        <h3 className="tc-client-name">{displayClient(c.client_name)}</h3>
                        {(c as any).tasks?.length > 0 && (
                          <p className="tc-client-meta">{(c as any).tasks.length} task{(c as any).tasks.length !== 1 ? 's' : ''}</p>
                        )}
                      </div>
                      <div className="tc-client-hours">{fmtHours(c.total_hours)} h</div>
                    </div>

                    {/* Category Tags */}
                    {Object.entries(c.categories || {}).filter(([k]) => !(k === "Uncategorized" && (c.tasks?.length || 0) > 0)).length > 0 && (
                      <div className="tc-category-tags">
                        {Object.entries(c.categories || {})
                          .filter(([k]) => !(k === "Uncategorized" && (c.tasks?.length || 0) > 0))
                          .map(([cat, hrs]) => (
                            <span key={cat} className="tc-category-tag">
                              {cat} <span className="tc-category-hours">{fmtHours(hrs)}h</span>
                            </span>
                          ))}
                      </div>
                    )}

                    {/* Task Breakdown */}
                    {(c as any).tasks?.length > 0 && (
                      <div className="tc-task-breakdown">
                        <div className="tc-task-breakdown-header">
                          <h4 className="tc-task-breakdown-title">Tasks</h4>
                        </div>
                        <div>
                          {(c as any).tasks.map((t: any) => (
                            <div key={`${c.client_name}-${t.task_name}`} className="tc-task-row">
                              <span className="tc-task-name">{t.task_name}</span>
                              <span className="tc-task-hours">{fmtHours(Number(t.total_hours || 0))} h</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}

                {!data.clients.length && (
                  <div className="tc-empty-state">
                    <p className="tc-empty-state-title">No tracked time for this date</p>
                    <p className="tc-empty-state-subtitle">Select a different date or user to view time entries</p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}