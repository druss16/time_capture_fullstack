// Home.tsx — TimeTracker · Modern, Calm
import { Link } from "react-router-dom";
import { ArrowRight, Clock, Check, BarChart3, FileText, Zap, ChevronRight } from "lucide-react";

const NAV_LINKS = [
  { label: "How It Works", href: "#how-it-works" },
  { label: "Features", href: "#features" },
  { label: "Pricing", href: "#pricing" },
];

const HOW_IT_WORKS = [
  {
    icon: Zap,
    step: "01",
    title: "Silent background tracking",
    desc: "One-time install on Mac or Windows. Captures activity automatically — no timers, no manual logging.",
  },
  {
    icon: Clock,
    step: "02",
    title: "AI maps time to clients instantly",
    desc: "Real-time categorization using your firm's context — highly accurate with zero manual fixes needed.",
  },
  {
    icon: FileText,
    step: "03",
    title: "Approve → sync to QuickBooks / Xero",
    desc: "Review clean timesheets, approve in one click, push billable hours directly to your accounting system.",
  },
];

const FEATURES = [
  { icon: BarChart3, title: "Client profitability insights", desc: "See true margins by client, staff, and matter type — identify winners and leaks fast." },
  { icon: Clock, title: "100% automatic capture", desc: "Every minute tracked and assigned. No reconstruction. No forgotten hours." },
  { icon: Check, title: "Streamlined approval flow", desc: "Submit → review → approve → invoice. One unified billing workflow." },
  { icon: Zap, title: "Seamless QuickBooks & Xero sync", desc: "Two-way integration. No exports, no double entry, always aligned." },
  { icon: FileText, title: "Weekly AI firm intelligence", desc: "Automated reports on billing efficiency, utilization, and performance trends." },
  { icon: BarChart3, title: "Native Mac + Windows", desc: "Lightweight agents that run invisibly and never miss a second." },
];

const INTEGRATIONS = [
  { name: "QuickBooks", abbr: "QB", color: "#2CA01C", bg: "#E8F5E2", category: "Billing" },
  { name: "Xero", abbr: "X", color: "#1AB4D7", bg: "#E2F6FB", category: "Billing" },
  { name: "Wolters Kluwer", abbr: "WK", color: "#004C97", bg: "#E0EAF5", category: "Tax" },
  { name: "Thomson Reuters", abbr: "TR", color: "#FF8200", bg: "#FFF0E0", category: "Tax" },
  { name: "Drake Software", abbr: "DS", color: "#C8102E", bg: "#FAE2E5", category: "Tax" },
  { name: "Sage", abbr: "S", color: "#00DC82", bg: "#E0FAF0", category: "Accounting" },
  { name: "Karbon", abbr: "K", color: "#6C47FF", bg: "#EEEAFF", category: "Practice Mgmt" },
  { name: "Canopy", abbr: "C", color: "#0EA5E9", bg: "#E0F3FD", category: "Practice Mgmt" },
];

const PRICING = [
  {
    name: "Professional",
    price: 29.99,
    desc: "Perfect for growing firms ready to eliminate manual time tracking.",
    features: ["Automatic capture", "AI client mapping", "QB & Xero sync", "Approval workflow", "Core reports"],
    highlighted: false,
  },
  {
    name: "Executive",
    price: 49.99,
    desc: "For leaders who want deep visibility into profitability and performance.",
    features: ["Everything in Professional", "Profitability dashboard", "AI firm insights", "Utilization analytics", "Priority support"],
    highlighted: true,
  },
];

export default function Home() {
  return (
    <div style={{ fontFamily: "'DM Sans', sans-serif", background: "#F4FAFA", color: "#0D1F1E", minHeight: "100vh" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600;9..40,700;9..40,800&display=swap');

        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        html { scroll-behavior: smooth; }

        :root {
          --teal:       #2B9D90;
          --teal-dark:  #1F7269;
          --teal-mid:   #34B5A7;
          --teal-light: #E6F5F4;
          --teal-border:#B8DDD9;
          --text:       #0D1F1E;
          --text-2:     #3D5C58;
          --text-3:     #7A9E9A;
          --line:       #DDE9E8;
          --bg:         #F4FAFA;
          --white:      #FFFFFF;
        }

        a { text-decoration: none; color: inherit; }

        /* NAV */
        .nav {
          position: fixed; top: 0; left: 0; right: 0; z-index: 100;
          height: 60px; display: flex; align-items: center;
          border-bottom: 1px solid var(--line);
          background: rgba(248,250,249,0.94);
          backdrop-filter: blur(12px);
        }
        .nav-inner {
          width: 100%; max-width: 1120px; margin: 0 auto;
          padding: 0 32px;
          display: flex; align-items: center; justify-content: space-between;
        }
        .nav-logo { display: flex; align-items: center; gap: 10px; }
        .nav-logo img { width: 42px; height: 42px; }
        .nav-logo-name { font-size: 19px; font-weight: 800; letter-spacing: -0.03em; color: #0D1F1A; }
        .nav-logo-by { font-size: 13px; font-weight: 400; color: var(--text-3); }
        .nav-links { display: flex; gap: 28px; }
        .nav-links a { font-size: 13.5px; font-weight: 500; color: var(--text-2); transition: color 0.15s; }
        .nav-links a:hover { color: var(--text); }
        .nav-right { display: flex; align-items: center; gap: 18px; }
        .nav-signin { font-size: 13.5px; font-weight: 500; color: var(--text-2); transition: color 0.15s; }
        .nav-signin:hover { color: var(--text); }
        .btn-primary {
          display: inline-flex; align-items: center; gap: 6px;
          padding: 9px 20px; border-radius: 999px;
          font-size: 13.5px; font-weight: 600; font-family: inherit;
          background: var(--teal); color: #fff;
          transition: background 0.15s, transform 0.1s;
          cursor: pointer; border: none;
        }
        .btn-primary:hover { background: var(--teal-dark); }
        .btn-primary:active { transform: scale(0.98); }

        /* HERO */
        .hero-section {
          background: linear-gradient(160deg, #2B9D90 0%, #1F7269 55%, #174F4A 100%);
          padding: 128px 32px 88px;
        }
        .hero-inner { max-width: 1120px; margin: 0 auto; }
        .hero-eyebrow {
          display: inline-flex; align-items: center; gap: 7px;
          font-size: 10.5px; font-weight: 700; letter-spacing: 0.13em;
          text-transform: uppercase; color: rgba(255,255,255,0.45);
          margin-bottom: 24px;
        }
        .hero-dot { width: 6px; height: 6px; border-radius: 50%; background: #4ADE80; }
        .hero-h1 {
          font-size: clamp(42px, 5.5vw, 68px);
          font-weight: 800; letter-spacing: -0.03em; line-height: 1.03;
          color: #fff; margin-bottom: 20px;
        }
        .hero-h1 em { color: rgba(255,255,255,0.38); font-style: normal; }
        .hero-sub {
          font-size: 17px; color: rgba(255,255,255,0.55);
          line-height: 1.7; max-width: 520px; margin-bottom: 36px; font-weight: 400;
        }
        .hero-btns { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 60px; }
        .btn-hero-primary {
          display: inline-flex; align-items: center; gap: 8px;
          padding: 13px 28px; border-radius: 999px;
          font-size: 15px; font-weight: 600; font-family: inherit;
          background: #fff; color: var(--teal-dark);
          transition: opacity 0.15s, transform 0.1s; cursor: pointer; border: none;
        }
        .btn-hero-primary:hover { opacity: 0.92; }
        .btn-hero-primary:active { transform: scale(0.98); }
        .btn-hero-ghost {
          display: inline-flex; align-items: center; gap: 7px;
          padding: 13px 24px; border-radius: 999px;
          font-size: 15px; font-weight: 500; font-family: inherit;
          color: rgba(255,255,255,0.65);
          border: 1px solid rgba(255,255,255,0.15);
          background: transparent;
          transition: color 0.15s, border-color 0.15s; cursor: pointer;
        }
        .btn-hero-ghost:hover { color: rgba(255,255,255,0.9); border-color: rgba(255,255,255,0.3); }
        .hero-stats {
          display: grid; grid-template-columns: repeat(3, auto); gap: 0;
          border-top: 1px solid rgba(255,255,255,0.1); padding-top: 40px;
          width: fit-content;
        }
        .hero-stat { padding-right: 48px; }
        .hero-stat:not(:first-child) { padding-left: 48px; border-left: 1px solid rgba(255,255,255,0.1); }
        .hero-stat-val { font-size: 40px; font-weight: 800; letter-spacing: -0.03em; color: #fff; line-height: 1; margin-bottom: 5px; }
        .hero-stat-label { font-size: 13px; color: rgba(255,255,255,0.38); }

        /* MARQUEE */
        .marquee-section {
          border-bottom: 1px solid var(--line);
          padding: 24px 0; overflow: hidden; position: relative;
          background: var(--white);
        }
        .marquee-eyebrow {
          text-align: center; font-size: 10px; font-weight: 700;
          letter-spacing: 0.14em; text-transform: uppercase;
          color: var(--text-3); margin-bottom: 18px;
        }
        .mfade-l { position: absolute; left: 0; top: 0; bottom: 0; width: 72px; z-index: 2; background: linear-gradient(to right, #fff, transparent); pointer-events: none; }
        .mfade-r { position: absolute; right: 0; top: 0; bottom: 0; width: 72px; z-index: 2; background: linear-gradient(to left, #fff, transparent); pointer-events: none; }
        @keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
        .marquee-track { display: flex; gap: 10px; white-space: nowrap; animation: marquee 38s linear infinite; }
        .int-chip {
          display: inline-flex; align-items: center; gap: 10px;
          padding: 9px 15px; border-radius: 10px;
          border: 1px solid var(--line); background: var(--bg);
          flex-shrink: 0; transition: border-color 0.15s;
        }
        .int-chip:hover { border-color: var(--teal-border); }
        .int-abbr { width: 30px; height: 30px; border-radius: 7px; display: flex; align-items: center; justify-content: center; font-size: 10.5px; font-weight: 800; }
        .int-name { font-size: 12.5px; font-weight: 600; color: var(--text); line-height: 1.2; }
        .int-cat  { font-size: 10.5px; color: var(--text-3); }

        /* SHARED SECTION */
        .section { max-width: 1120px; margin: 0 auto; padding: 88px 32px; }
        .section-eyebrow {
          font-size: 10.5px; font-weight: 700; letter-spacing: 0.13em;
          text-transform: uppercase; color: var(--teal-mid); margin-bottom: 12px;
        }
        .section-h2 {
          font-size: clamp(28px, 3.5vw, 40px);
          font-weight: 800; letter-spacing: -0.025em; line-height: 1.1;
          color: var(--text); margin-bottom: 40px;
        }
        .section-sub {
          font-size: 16px; color: var(--text-2); line-height: 1.65;
          max-width: 500px; margin-bottom: 40px; margin-top: -24px;
        }
        .hr { border: none; border-top: 1px solid var(--line); }

        /* HOW IT WORKS */
        .steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
        @media (max-width: 768px) { .steps { grid-template-columns: 1fr; } }
        .step-card {
          background: var(--white); border: 1px solid var(--line);
          border-radius: 14px; padding: 32px 28px;
          transition: border-color 0.2s;
        }
        .step-card:hover { border-color: var(--teal-border); }
        .step-num { font-size: 10.5px; font-weight: 700; letter-spacing: 0.1em; color: var(--text-3); margin-bottom: 24px; }
        .step-icon {
          width: 38px; height: 38px; border-radius: 9px;
          background: var(--teal-light); border: 1px solid var(--teal-border);
          display: flex; align-items: center; justify-content: center;
          margin-bottom: 18px;
        }
        .step-icon svg { width: 17px; height: 17px; color: var(--teal); }
        .step-card h3 { font-size: 15.5px; font-weight: 700; letter-spacing: -0.01em; margin-bottom: 10px; }
        .step-card p { font-size: 13.5px; color: var(--text-2); line-height: 1.65; }

        /* FEATURES */
        .feat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
        @media (max-width: 900px) { .feat-grid { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 560px) { .feat-grid { grid-template-columns: 1fr; } }
        .feat-card {
          background: var(--white); border: 1px solid var(--line);
          border-radius: 14px; padding: 28px 24px;
          transition: border-color 0.2s;
        }
        .feat-card:hover { border-color: var(--teal-border); }
        .feat-icon {
          width: 34px; height: 34px; border-radius: 8px;
          background: var(--teal-light); border: 1px solid var(--teal-border);
          display: flex; align-items: center; justify-content: center;
          margin-bottom: 16px;
        }
        .feat-icon svg { width: 15px; height: 15px; color: var(--teal); }
        .feat-card h3 { font-size: 14px; font-weight: 700; letter-spacing: -0.01em; margin-bottom: 7px; }
        .feat-card p { font-size: 13px; color: var(--text-2); line-height: 1.6; }

        /* COMPARE */
        .compare-grid {
          display: grid; grid-template-columns: 1fr 1fr;
          border: 1px solid var(--line); border-radius: 14px; overflow: hidden;
        }
        @media (max-width: 640px) { .compare-grid { grid-template-columns: 1fr; } }
        .compare-col { padding: 40px 36px; background: var(--white); }
        .compare-col:first-child { border-right: 1px solid var(--line); background: var(--bg); }
        .compare-label { font-size: 10.5px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 24px; }
        .compare-label.old { color: var(--text-3); }
        .compare-label.new { color: var(--teal-mid); }
        .compare-list { list-style: none; display: flex; flex-direction: column; gap: 13px; }
        .compare-item { display: flex; align-items: flex-start; gap: 10px; font-size: 13.5px; line-height: 1.5; }
        .compare-item.old { color: var(--text-3); }
        .compare-item.new { color: var(--text); }
        .ci-icon {
          width: 17px; height: 17px; border-radius: 50%; flex-shrink: 0; margin-top: 1px;
          display: flex; align-items: center; justify-content: center;
          font-size: 9px; font-weight: 700;
        }
        .ci-icon.old { background: #EAEAEA; color: #AAAAAA; }
        .ci-icon.new { background: var(--teal); color: #fff; }

        /* PRICING */
        .pricing-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; max-width: 780px; }
        @media (max-width: 600px) { .pricing-grid { grid-template-columns: 1fr; } }
        .plan {
          border: 1px solid var(--line); border-radius: 16px; padding: 36px 32px;
          background: var(--white);
        }
        .plan.exec { background: var(--teal); border-color: var(--teal); }
        .plan-badge {
          display: inline-block;
          font-size: 9.5px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
          background: var(--teal-mid); color: #fff;
          padding: 3px 9px; border-radius: 20px; margin-bottom: 18px;
        }
        .plan-name { font-size: 10.5px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; margin-bottom: 10px; }
        .plan.exec .plan-name { color: rgba(255,255,255,0.4); }
        .plan:not(.exec) .plan-name { color: var(--text-3); }
        .plan-price { font-size: 46px; font-weight: 800; letter-spacing: -0.04em; line-height: 1; }
        .plan.exec .plan-price { color: #fff; }
        .plan:not(.exec) .plan-price { color: var(--text); }
        .plan-per { font-size: 13px; font-weight: 400; }
        .plan.exec .plan-per { color: rgba(255,255,255,0.35); }
        .plan:not(.exec) .plan-per { color: var(--text-3); }
        .plan-desc { font-size: 13px; line-height: 1.6; margin: 14px 0 24px; }
        .plan.exec .plan-desc { color: rgba(255,255,255,0.45); }
        .plan:not(.exec) .plan-desc { color: var(--text-2); }
        .plan-divider { border: none; border-top: 1px solid; margin-bottom: 20px; }
        .plan.exec .plan-divider { border-color: rgba(255,255,255,0.1); }
        .plan:not(.exec) .plan-divider { border-color: var(--line); }
        .plan-feats { list-style: none; display: flex; flex-direction: column; gap: 11px; margin-bottom: 28px; }
        .plan-feat { display: flex; align-items: center; gap: 9px; font-size: 13.5px; }
        .plan.exec .plan-feat { color: rgba(255,255,255,0.7); }
        .plan:not(.exec) .plan-feat { color: var(--text-2); }
        .pf-check { width: 15px; height: 15px; flex-shrink: 0; }
        .plan.exec .pf-check { color: #4ADE80; }
        .plan:not(.exec) .pf-check { color: var(--teal); }
        .plan-cta {
          display: block; width: 100%; text-align: center;
          padding: 12px; border-radius: 999px;
          font-size: 14px; font-weight: 600; font-family: inherit;
          cursor: pointer; border: none;
          transition: opacity 0.15s, transform 0.1s;
        }
        .plan-cta:active { transform: scale(0.98); }
        .plan.exec .plan-cta { background: var(--teal-mid); color: #fff; }
        .plan.exec .plan-cta:hover { opacity: 0.88; }
        .plan:not(.exec) .plan-cta { background: var(--teal-light); color: var(--teal-dark); }
        .plan:not(.exec) .plan-cta:hover { opacity: 0.8; }
        .pricing-note { font-size: 12.5px; color: var(--text-3); margin-top: 16px; }

        /* CTA */
        .cta-section {
          background: var(--teal);
          padding: 80px 32px; text-align: center;
        }
        .cta-inner { max-width: 560px; margin: 0 auto; }
        .cta-section h2 {
          font-size: clamp(26px, 4vw, 40px);
          font-weight: 800; letter-spacing: -0.025em;
          color: #fff; margin-bottom: 14px; line-height: 1.1;
        }
        .cta-section p { font-size: 15px; color: rgba(255,255,255,0.5); line-height: 1.65; margin-bottom: 32px; }

        /* FOOTER */
        .footer { border-top: 1px solid var(--line); background: var(--bg); }
        .footer-inner {
          max-width: 1120px; margin: 0 auto; padding: 32px;
          display: flex; align-items: center; justify-content: space-between;
          flex-wrap: wrap; gap: 12px;
        }
        .footer-logo { display: flex; align-items: center; gap: 8px; }
        .footer-logo img { width: 28px; height: 28px; opacity: 0.7; }
        .footer-logo-name { font-size: 14px; font-weight: 800; letter-spacing: -0.02em; color: var(--text); }
        .footer-by { color: var(--text-3); font-weight: 400; font-size: 12px; }
        .footer-links { display: flex; gap: 20px; }
        .footer-links a { font-size: 12px; color: var(--text-3); transition: color 0.15s; }
        .footer-links a:hover { color: var(--text); }
        .footer-copy { font-size: 12px; color: var(--text-3); }

        @media (max-width: 768px) {
          .hero-stats { grid-template-columns: 1fr; }
          .nav-links { display: none; }
          .hero-stat:not(:first-child) { padding-left: 0; border-left: none; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 24px; }
          .hero-stat { padding-right: 0; }
        }
      `}</style>

      {/* NAV */}
      <nav className="nav">
        <div className="nav-inner">
          <div className="nav-logo">
            <img src="/timetracker-icon.svg" alt="TimeTracker" />
            <div style={{ display: "flex", alignItems: "baseline", gap: "6px" }}>
              <span className="nav-logo-name">TimeTracker</span>
              <span className="nav-logo-by">by MavOps</span>
            </div>
          </div>
          <div className="nav-links">
            {NAV_LINKS.map(({ label, href }) => (
              <a key={label} href={href}>{label}</a>
            ))}
          </div>
          <div className="nav-right">
            <Link to="/login" className="nav-signin">Sign in</Link>
            <a href="mailto:info@mavops.ai?subject=TimeTracker%20Access%20Request" className="btn-primary">
              Request Access <ChevronRight size={14} />
            </a>
          </div>
        </div>
      </nav>

      {/* HERO */}
      <section className="hero-section">
        <div className="hero-inner">
          <div className="hero-eyebrow">
            <span className="hero-dot" />
            Purpose-built for CPA firms
          </div>
          <h1 className="hero-h1">
            Recover hours.<br />
            Reveal profit.<br />
            <em>Run smarter.</em>
          </h1>
          <p className="hero-sub">
            TimeTracker is an AI-powered time intelligence platform that eliminates manual timesheets, captures every billable minute, and gives firm leaders the margin data to grow with confidence.
          </p>
          <div className="hero-btns">
            <a href="mailto:info@mavops.ai?subject=TimeTracker%20Access%20Request" className="btn-hero-primary">
              Get Started <ArrowRight size={16} />
            </a>
            <a href="#how-it-works" className="btn-hero-ghost">
              Learn How It Works
            </a>
          </div>
          <div className="hero-stats">
            {[
              { val: "2+ hrs", label: "Extra billable time / staff / day" },
              { val: "~98%",   label: "Billable capture rate" },
              { val: "1-click", label: "Sync to QB & Xero" },
            ].map(({ val, label }, i) => (
              <div key={i} className="hero-stat">
                <div className="hero-stat-val">{val}</div>
                <div className="hero-stat-label">{label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* INTEGRATIONS */}
      <div className="marquee-section">
        <p className="marquee-eyebrow">Integrates with tools you already trust</p>
        <div style={{ position: "relative" }}>
          <div className="mfade-l" /><div className="mfade-r" />
          <div className="marquee-track">
            {[...INTEGRATIONS, ...INTEGRATIONS].map((int, i) => (
              <div key={i} className="int-chip">
                <div className="int-abbr" style={{ background: int.bg, color: int.color }}>{int.abbr}</div>
                <div>
                  <div className="int-name">{int.name}</div>
                  <div className="int-cat">{int.category}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* HOW IT WORKS */}
      <section id="how-it-works" className="section" style={{ background: "#F8FAF9" }}>
        <p className="section-eyebrow">How It Works</p>
        <h2 className="section-h2">Effortless accuracy from day one</h2>
        <p className="section-sub">No setup hassle. No daily input. Just reliable billable time.</p>
        <div className="steps">
          {HOW_IT_WORKS.map(({ icon: Icon, step, title, desc }, i) => (
            <div key={i} className="step-card">
              <div className="step-num">{step}</div>
              <div className="step-icon"><Icon /></div>
              <h3>{title}</h3>
              <p>{desc}</p>
            </div>
          ))}
        </div>
      </section>

      <hr className="hr" />

      {/* FEATURES */}
      <section id="features" className="section" style={{ background: "#F8FAF9" }}>
        <p className="section-eyebrow">Features</p>
        <h2 className="section-h2">Everything a CPA firm needs</h2>
        <div className="feat-grid">
          {FEATURES.map(({ icon: Icon, title, desc }, i) => (
            <div key={i} className="feat-card">
              <div className="feat-icon"><Icon /></div>
              <h3>{title}</h3>
              <p>{desc}</p>
            </div>
          ))}
        </div>
      </section>

      <hr className="hr" />

      {/* BEFORE / AFTER */}
      <section className="section" style={{ background: "#F8FAF9" }}>
        <p className="section-eyebrow">The Difference</p>
        <h2 className="section-h2">Before vs. after TimeTracker</h2>
        <div className="compare-grid">
          <div className="compare-col">
            <p className="compare-label old">The old way</p>
            <ul className="compare-list">
              {["Manual time entry at end of day", "Forgotten hours, guessed durations", "Misattributed client work", "Hours of monthly cleanup"].map((t, i) => (
                <li key={i} className="compare-item old">
                  <span className="ci-icon old">✕</span>{t}
                </li>
              ))}
            </ul>
          </div>
          <div className="compare-col">
            <p className="compare-label new">With TimeTracker</p>
            <ul className="compare-list">
              {["Automatic, real-time capture", "100% of billable minutes recorded", "AI maps every activity to the right client", "One-click approval and sync"].map((t, i) => (
                <li key={i} className="compare-item new">
                  <span className="ci-icon new"><Check size={9} /></span>{t}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <hr className="hr" />

      {/* PRICING */}
      <section id="pricing" className="section" style={{ background: "#F8FAF9" }}>
        <p className="section-eyebrow">Pricing</p>
        <h2 className="section-h2">Simple per-seat pricing</h2>
        <div className="pricing-grid">
          {PRICING.map(({ name, price, desc, features, highlighted }) => (
            <div key={name} className={`plan${highlighted ? " exec" : ""}`}>
              {highlighted && <span className="plan-badge">Most Popular</span>}
              <div className="plan-name">{name}</div>
              <div className="plan-price">${price}<span className="plan-per"> /seat/mo</span></div>
              <p className="plan-desc">{desc}</p>
              <hr className="plan-divider" />
              <ul className="plan-feats">
                {features.map((f, fi) => (
                  <li key={fi} className="plan-feat">
                    <Check className="pf-check" size={15} />{f}
                  </li>
                ))}
              </ul>
              <a href="mailto:info@mavops.ai?subject=TimeTracker%20Access%20Request" className="plan-cta">
                Get Started
              </a>
            </div>
          ))}
        </div>
        <p className="pricing-note">No contracts. No setup fees. Cancel anytime.</p>
      </section>

      {/* CTA */}
      <section className="cta-section">
        <div className="cta-inner">
          <h2>Start capturing every billable minute</h2>
          <p>Join CPA firms that have eliminated manual timesheets and unlocked clearer profitability with TimeTracker.</p>
          <a href="mailto:info@mavops.ai?subject=TimeTracker%20Access%20Request" className="btn-hero-primary">
            Request Access <ArrowRight size={16} />
          </a>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="footer">
        <div className="footer-inner">
          <div className="footer-logo">
            <img src="/timetracker-icon.svg" alt="" />
            <span className="footer-logo-name">TimeTracker</span>
            <span className="footer-by">by MavOps AI</span>
          </div>
          <div className="footer-links">
            <a href="/privacy">Privacy</a>
            <a href="/terms">Terms</a>
            <a href="mailto:info@mavops.ai">Contact</a>
          </div>
          <p className="footer-copy">© 2025 MavOps AI</p>
        </div>
      </footer>
    </div>
  );
}