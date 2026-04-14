// RequestAccess.tsx — TimeTracker · Request Access page
import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Check, ArrowLeft } from "lucide-react";

export default function RequestAccess() {
  const [form, setForm] = useState({
    name: "",
    email: "",
    firm: "",
    size: "",
    role: "",
    message: "",
  });
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);

  const FIRM_SIZES = ["1–5 staff", "6–15 staff", "16–50 staff", "50+ staff"];
  const ROLES = ["Partner / Owner", "Managing Partner", "Controller", "Office Manager", "Other"];

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await fetch("https://formspree.io/f/xrerblpz", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          _replyto: form.email,   // reply-to goes straight to the prospect
          _subject: `New TimeTracker request — ${form.firm}`,
        }),
      });
    } catch {}
    setBusy(false);
    setSubmitted(true);
  }

  return (
    <div style={{ fontFamily: "'DM Sans', sans-serif", background: "#F4FAFA", color: "#0D1F1E", minHeight: "100vh" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600;9..40,700;9..40,800&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        :root {
          --teal:#2B9D90;--teal-dark:#1F7269;--teal-mid:#34B5A7;
          --teal-light:#E6F5F4;--teal-border:#B8DDD9;
          --text:#0D1F1E;--text-2:#3D5C58;--text-3:#7A9E9A;
          --line:#DDE9E8;--bg:#F4FAFA;--white:#FFFFFF;
        }
        a{text-decoration:none;color:inherit}
        .nav{height:60px;display:flex;align-items:center;border-bottom:1px solid var(--line);background:rgba(248,250,249,0.96)}
        .nav-inner{width:100%;max-width:1120px;margin:0 auto;padding:0 32px;display:flex;align-items:center;justify-content:space-between}
        .nav-logo{display:flex;align-items:center;gap:6px} .nav-logo img{width:42px;height:42px}
        .nav-logo-name{font-size:19px;font-weight:800;letter-spacing:-0.03em;color:#0D1F1A}
        .nav-logo-by{font-size:13px;font-weight:400;color:var(--text-3)}
        .back-link{display:inline-flex;align-items:center;gap:6px;font-size:13.5px;font-weight:500;color:var(--text-2);transition:color 0.15s} .back-link:hover{color:var(--teal)}
        .page{min-height:calc(100vh - 60px);display:grid;grid-template-columns:1fr 1fr;max-width:1120px;margin:0 auto;padding:64px 32px;gap:80px;align-items:start}
        @media(max-width:860px){.page{grid-template-columns:1fr;gap:48px;padding:40px 24px}.left-col{order:2}.right-col{order:1}}
        .eyebrow{display:inline-flex;align-items:center;gap:7px;font-size:10.5px;font-weight:700;letter-spacing:0.13em;text-transform:uppercase;color:var(--teal);margin-bottom:20px}
        .page-h1{font-size:clamp(28px,3.5vw,42px);font-weight:800;letter-spacing:-0.025em;line-height:1.1;color:var(--text);margin-bottom:16px}
        .page-sub{font-size:15px;color:var(--text-2);line-height:1.7;margin-bottom:40px}
        .proof-list{list-style:none;display:flex;flex-direction:column;gap:14px;margin-bottom:40px}
        .proof-item{display:flex;align-items:flex-start;gap:12px}
        .proof-check{width:20px;height:20px;border-radius:50%;background:var(--teal-light);border:1px solid var(--teal-border);display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:1px}
        .proof-check svg{width:11px;height:11px;color:var(--teal)}
        .proof-text{font-size:14px;color:var(--text-2);line-height:1.5} .proof-text strong{color:var(--text);font-weight:700}
        .stat-row{display:flex;gap:0;border:1px solid var(--line);border-radius:14px;overflow:hidden;background:var(--white)}
        .stat-item{flex:1;padding:20px 24px;border-right:1px solid var(--line)} .stat-item:last-child{border-right:none}
        .stat-val{font-size:26px;font-weight:800;letter-spacing:-0.03em;color:var(--teal);line-height:1;margin-bottom:4px}
        .stat-label{font-size:11.5px;color:var(--text-3);line-height:1.4}
        .form-card{background:var(--white);border:1px solid var(--line);border-radius:20px;padding:40px}
        .form-title{font-size:20px;font-weight:800;letter-spacing:-0.02em;margin-bottom:6px}
        .form-sub{font-size:13.5px;color:var(--text-3);margin-bottom:32px}
        .field{margin-bottom:18px}
        .field label{display:block;font-size:12.5px;font-weight:700;color:var(--text-2);margin-bottom:7px;letter-spacing:0.01em}
        .field input,.field select,.field textarea{width:100%;padding:11px 14px;border:1.5px solid var(--line);border-radius:10px;font-size:14px;font-family:inherit;color:var(--text);background:var(--bg);outline:none;transition:border-color 0.15s,background 0.15s;appearance:none}
        .field input:focus,.field select:focus,.field textarea:focus{border-color:var(--teal);background:var(--white)}
        .field input::placeholder,.field textarea::placeholder{color:var(--text-3)}
        .field select{cursor:pointer;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%237A9E9A' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 14px center;padding-right:36px}
        .field textarea{resize:none;line-height:1.6}
        .field-row{display:grid;grid-template-columns:1fr 1fr;gap:14px}
        @media(max-width:540px){.field-row{grid-template-columns:1fr}}
        .submit-btn{width:100%;display:flex;align-items:center;justify-content:center;gap:8px;padding:14px;border-radius:999px;font-size:15px;font-weight:700;font-family:inherit;background:var(--teal);color:white;border:none;cursor:pointer;transition:background 0.15s,transform 0.1s;margin-top:8px}
        .submit-btn:hover{background:var(--teal-dark)} .submit-btn:active{transform:scale(0.98)} .submit-btn:disabled{opacity:0.6;cursor:not-allowed}
        .form-note{text-align:center;font-size:12px;color:var(--text-3);margin-top:14px;line-height:1.5}
        .success-card{background:var(--white);border:1px solid var(--line);border-radius:20px;padding:56px 40px;text-align:center}
        .success-icon{width:56px;height:56px;border-radius:50%;background:var(--teal-light);border:1px solid var(--teal-border);display:flex;align-items:center;justify-content:center;margin:0 auto 20px}
        .success-icon svg{width:24px;height:24px;color:var(--teal)}
        .success-h2{font-size:22px;font-weight:800;letter-spacing:-0.02em;margin-bottom:10px}
        .success-p{font-size:14px;color:var(--text-2);line-height:1.65;max-width:300px;margin:0 auto 28px}
        .back-home-btn{display:inline-flex;align-items:center;gap:6px;padding:11px 24px;border-radius:999px;font-size:14px;font-weight:600;background:var(--teal-light);color:var(--teal-dark);transition:opacity 0.15s} .back-home-btn:hover{opacity:0.8}
      `}</style>

      <nav className="nav">
        <div className="nav-inner">
          <Link to="/" className="nav-logo">
            <img src="/timetracker-icon.svg" alt="TimeTracker" />
            <div style={{ display: "flex", alignItems: "baseline", gap: "6px" }}>
              <span className="nav-logo-name">TimeTracker</span>
              <span className="nav-logo-by">by MavOps</span>
            </div>
          </Link>
          <Link to="/" className="back-link">
            <ArrowLeft size={14} /> Back to home
          </Link>
        </div>
      </nav>

      <div className="page">
        <div className="left-col">
          <p className="eyebrow">Request Access</p>
          <h1 className="page-h1">Start recovering<br />billable time today.</h1>
          <p className="page-sub">
            Tell us about your firm and we'll get you set up with a free trial. No contracts, no setup fees — just cleaner timesheets from day one.
          </p>
          <ul className="proof-list">
            {[
              { strong: "No IT required — but we love to involve them.", rest: " Self-install takes minutes, or let us handle GPO/MDM deployment for a white-glove setup." },
              { strong: "Works on Mac & Windows.", rest: " Background agent captures everything silently." },
              { strong: "98% billable capture rate.", rest: " Recover 2+ hours per staff per day." },
              { strong: "Syncs to QuickBooks & Xero.", rest: " One-click approval and invoice push." },
            ].map(({ strong, rest }, i) => (
              <li key={i} className="proof-item">
                <span className="proof-check"><Check /></span>
                <span className="proof-text"><strong>{strong}</strong>{rest}</span>
              </li>
            ))}
          </ul>
          <div className="stat-row">
            {[
              { val: "2+ hrs", label: "Extra billable time\nper staff per day" },
              { val: "~98%", label: "Billable\ncapture rate" },
              { val: "$0", label: "Setup fee\nor contracts" },
            ].map(({ val, label }, i) => (
              <div key={i} className="stat-item">
                <div className="stat-val">{val}</div>
                <div className="stat-label">{label}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="right-col">
          {submitted ? (
            <div className="success-card">
              <div className="success-icon"><Check /></div>
              <h2 className="success-h2">Request received!</h2>
              <p className="success-p">
                Thanks for reaching out. We'll be in touch within one business day to get you set up.
              </p>
              <Link to="/" className="back-home-btn">
                <ArrowLeft size={14} /> Back to home
              </Link>
            </div>
          ) : (
            <div className="form-card">
              <h2 className="form-title">Get early access</h2>
              <p className="form-sub">We'll reach out within one business day.</p>
              <form onSubmit={handleSubmit}>
                <div className="field-row">
                  <div className="field">
                    <label>Your name</label>
                    <input type="text" placeholder="Jane Smith" required
                      value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}/>
                  </div>
                  <div className="field">
                    <label>Work email</label>
                    <input type="email" placeholder="jane@firmname.com" required
                      value={form.email} onChange={e => setForm({ ...form, email: e.target.value })}/>
                  </div>
                </div>
                <div className="field">
                  <label>Firm name</label>
                  <input type="text" placeholder="Hartwell & Associates CPA" required
                    value={form.firm} onChange={e => setForm({ ...form, firm: e.target.value })}/>
                </div>
                <div className="field-row">
                  <div className="field">
                    <label>Firm size</label>
                    <select required value={form.size} onChange={e => setForm({ ...form, size: e.target.value })}>
                      <option value="">Select size</option>
                      {FIRM_SIZES.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </div>
                  <div className="field">
                    <label>Your role</label>
                    <select required value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}>
                      <option value="">Select role</option>
                      {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </div>
                </div>
                <div className="field">
                  <label>Anything else? <span style={{ fontWeight: 400, color: "var(--text-3)" }}>(optional)</span></label>
                  <textarea rows={3} placeholder="Current time tracking setup, specific questions, etc."
                    value={form.message} onChange={e => setForm({ ...form, message: e.target.value })}/>
                </div>
                <button type="submit" className="submit-btn" disabled={busy}>
                  {busy ? "Sending…" : <><span>Request Access</span> <ArrowRight size={16} /></>}
                </button>
              </form>
              <p className="form-note">No spam. No sales calls unless you want one. Just a quick setup chat.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}