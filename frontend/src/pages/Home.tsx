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
  { name: "QuickBooks",      category: "Billing",        abbr: "QB", color: "#fff", bg: "#2CA01C" },
  { name: "Xero",            category: "Billing",        abbr: "X",  color: "#fff", bg: "#1AB4D7" },
  { name: "Wolters Kluwer",  category: "Tax",            abbr: "WK", color: "#fff", bg: "#004C97" },
  { name: "Thomson Reuters", category: "Tax",            abbr: "TR", color: "#fff", bg: "#FF8200" },
  { name: "Drake Software",  category: "Tax",            abbr: "DS", color: "#fff", bg: "#C8102E" },
  { name: "Sage",            category: "Accounting",     abbr: "S",  color: "#fff", bg: "#00B050" },
  { name: "Karbon",          category: "Practice Mgmt",  abbr: "K",  color: "#fff", bg: "#6C47FF" },
  { name: "Canopy",          category: "Practice Mgmt",  abbr: "C",  color: "#fff", bg: "#0EA5E9" },
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

const PIPELINE_SVG = `<svg width="100%" viewBox="0 0 680 300" xmlns="http://www.w3.org/2000/svg">
<defs>
  <marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M2 2L8 5L2 8" fill="none" stroke="#4ADE80" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
  </marker>
  <style>
    @keyframes floatup  { 0%{opacity:0;transform:translateY(12px)} 45%{opacity:1} 100%{opacity:0;transform:translateY(-22px)} }
    @keyframes dash     { to{stroke-dashoffset:-24} }
    @keyframes pulse    { 0%,100%{opacity:1;r:6} 50%{opacity:0.4;r:4} }
    @keyframes spin     { to{transform:rotate(360deg)} }
    @keyframes appear   { 0%{opacity:0;transform:translateX(-6px)} 100%{opacity:1;transform:translateX(0)} }
    @keyframes glow     { 0%,100%{opacity:0.3} 50%{opacity:0.7} }
    @keyframes scanline { 0%{transform:translateY(0)} 100%{transform:translateY(60px)} }
    @keyframes popcheck { 0%{opacity:0;transform:scale(0)} 60%{transform:scale(1.2)} 100%{opacity:1;transform:scale(1)} }
    @media (prefers-reduced-motion: no-preference) {
      .f1{animation:floatup 2.8s ease-in-out infinite 0s}
      .f2{animation:floatup 2.8s ease-in-out infinite 0.6s}
      .f3{animation:floatup 2.8s ease-in-out infinite 1.2s}
      .f4{animation:floatup 2.8s ease-in-out infinite 1.9s}
      .flow1{animation:dash 1.2s linear infinite}
      .flow2{animation:dash 1.2s linear infinite 0.35s}
      .spin{animation:spin 3s linear infinite;transform-origin:340px 130px}
      .glow{animation:glow 2.4s ease-in-out infinite}
      .scan{animation:scanline 1.8s linear infinite}
      .r1{animation:appear 0.5s 0.1s ease both}
      .r2{animation:appear 0.5s 0.4s ease both}
      .r3{animation:appear 0.5s 0.7s ease both}
      .r4{animation:appear 0.5s 1.0s ease both}
      .r5{animation:appear 0.5s 1.3s ease both}
      .ck1{animation:popcheck 0.4s 0.2s ease both}
      .ck2{animation:popcheck 0.4s 0.5s ease both}
      .ck3{animation:popcheck 0.4s 0.8s ease both}
      .ck4{animation:popcheck 0.4s 1.1s ease both}
    }
  </style>
  <clipPath id="scan-clip"><rect x="40" y="56" width="134" height="82" rx="0"/></clipPath>
</defs>

<ellipse cx="100" cy="150" rx="90" ry="70" fill="rgba(43,157,144,0.08)"/>
<ellipse cx="340" cy="150" rx="80" ry="60" fill="rgba(74,222,128,0.06)"/>
<ellipse cx="580" cy="150" rx="90" ry="70" fill="rgba(43,157,144,0.07)"/>

<!-- PANEL 1 -->
<rect x="12" y="28" width="190" height="220" rx="22" fill="rgba(255,255,255,0.09)" stroke="rgba(255,255,255,0.18)" stroke-width="1.2"/>
<rect x="34" y="50" width="146" height="104" rx="10" fill="rgba(255,255,255,0.95)" stroke="rgba(255,255,255,0.4)" stroke-width="1"/>
<rect x="40" y="56" width="134" height="82" rx="6" fill="#0C1B28"/>
<rect class="scan" x="40" y="56" width="134" height="4" fill="rgba(43,157,144,0.18)" clip-path="url(#scan-clip)"/>
<rect x="46" y="62" width="36" height="24" rx="4" fill="#1E3A4A"/>
<rect x="46" y="62" width="36" height="6"  rx="4" fill="#2B9D90" opacity="0.8"/>
<rect x="87" y="62" width="30" height="24" rx="4" fill="#1E3A4A"/>
<rect x="87" y="62" width="30" height="6"  rx="4" fill="#F59E0B" opacity="0.7"/>
<rect x="122" y="62" width="48" height="24" rx="4" fill="#1E3A4A"/>
<rect x="122" y="62" width="48" height="6"  rx="4" fill="#2B9D90" opacity="0.5"/>
<rect x="46" y="91"  width="120" height="3" rx="1" fill="#2B9D90" opacity="0.25"/>
<rect x="46" y="98"  width="88"  height="3" rx="1" fill="#2B9D90" opacity="0.18"/>
<rect x="46" y="105" width="104" height="3" rx="1" fill="#2B9D90" opacity="0.2"/>
<rect x="46" y="112" width="72"  height="3" rx="1" fill="#2B9D90" opacity="0.15"/>
<rect x="46" y="119" width="96"  height="3" rx="1" fill="#F59E0B" opacity="0.18"/>
<rect x="46" y="126" width="60"  height="3" rx="1" fill="#2B9D90" opacity="0.12"/>
<circle cx="162" cy="125" r="4" fill="#4ADE80" class="glow"/>
<rect x="100" y="154" width="14" height="10" rx="3" fill="rgba(255,255,255,0.3)"/>
<rect x="84"  y="163" width="46" height="5"  rx="2" fill="rgba(255,255,255,0.25)"/>
<g class="f1" style="transform-box:fill-box">
  <rect x="36" y="32" width="54" height="16" rx="8" fill="#2B9D90"/>
  <text font-family="sans-serif" font-size="8.5" font-weight="700" fill="white" x="63" y="44" text-anchor="middle">Chrome</text>
</g>
<g class="f2" style="transform-box:fill-box">
  <rect x="100" y="28" width="56" height="16" rx="8" fill="#1F7269"/>
  <text font-family="sans-serif" font-size="8.5" font-weight="700" fill="white" x="128" y="40" text-anchor="middle">Outlook</text>
</g>
<g class="f3" style="transform-box:fill-box">
  <rect x="36" y="16" width="72" height="16" rx="8" fill="#34B5A7"/>
  <text font-family="sans-serif" font-size="8.5" font-weight="700" fill="white" x="72" y="28" text-anchor="middle">QuickBooks</text>
</g>
<g class="f4" style="transform-box:fill-box">
  <rect x="118" y="14" width="48" height="16" rx="8" fill="#F59E0B"/>
  <text font-family="sans-serif" font-size="8.5" font-weight="700" fill="white" x="142" y="26" text-anchor="middle">Slack</text>
</g>
<text font-family="sans-serif" font-size="11.5" font-weight="800" fill="white" x="107" y="200" text-anchor="middle">Desktop Agent</text>
<text font-family="sans-serif" font-size="9" fill="rgba(255,255,255,0.45)" x="107" y="215" text-anchor="middle">Silent · Mac &amp; Windows</text>

<!-- ARROW 1 -->
<line class="flow1" x1="206" y1="128" x2="264" y2="128" stroke="#4ADE80" stroke-width="2" stroke-dasharray="5 4" marker-end="url(#arr)" opacity="0.9"/>
<text font-family="sans-serif" font-size="8" font-weight="600" fill="rgba(255,255,255,0.4)" x="235" y="120" text-anchor="middle">events</text>

<!-- PANEL 2 -->
<rect x="268" y="28" width="144" height="220" rx="22" fill="rgba(255,255,255,0.09)" stroke="rgba(255,255,255,0.18)" stroke-width="1.2"/>
<circle cx="340" cy="120" r="52" fill="rgba(43,157,144,0.07)"/>
<circle cx="340" cy="120" r="38" fill="rgba(43,157,144,0.1)"/>
<circle class="spin" cx="340" cy="120" r="44" fill="none" stroke="rgba(74,222,128,0.35)" stroke-width="1.5" stroke-dasharray="6 8"/>
<circle cx="340" cy="120" r="28" fill="rgba(43,157,144,0.22)" class="glow"/>
<circle cx="340" cy="120" r="18" fill="#2B9D90" opacity="0.7"/>
<text font-family="sans-serif" font-size="14" font-weight="900" fill="white" x="340" y="125" text-anchor="middle">AI</text>
<circle cx="340" cy="72"  r="7" fill="#4ADE80" opacity="0.85"/>
<text font-family="sans-serif" font-size="6.5" font-weight="700" fill="#0C1B28" x="340" y="75" text-anchor="middle">$</text>
<circle cx="384" cy="100" r="7" fill="#FCD34D" opacity="0.85"/>
<text font-family="sans-serif" font-size="6.5" font-weight="700" fill="#0C1B28" x="384" y="103" text-anchor="middle">@</text>
<circle cx="384" cy="140" r="7" fill="#34B5A7" opacity="0.85"/>
<text font-family="sans-serif" font-size="6.5" font-weight="700" fill="white" x="384" y="143" text-anchor="middle">&#9881;</text>
<circle cx="296" cy="140" r="7" fill="#F59E0B" opacity="0.85"/>
<text font-family="sans-serif" font-size="6.5" font-weight="700" fill="white" x="296" y="143" text-anchor="middle">&#9993;</text>
<circle cx="296" cy="100" r="7" fill="#2B9D90" opacity="0.85"/>
<text font-family="sans-serif" font-size="6.5" font-weight="700" fill="white" x="296" y="103" text-anchor="middle">&#8862;</text>
<text font-family="sans-serif" font-size="11.5" font-weight="800" fill="white" x="340" y="200" text-anchor="middle">AI Engine</text>
<text font-family="sans-serif" font-size="9" fill="rgba(255,255,255,0.45)" x="340" y="215" text-anchor="middle">Categorizes instantly</text>

<!-- ARROW 2 -->
<line class="flow2" x1="416" y1="128" x2="474" y2="128" stroke="#4ADE80" stroke-width="2" stroke-dasharray="5 4" marker-end="url(#arr)" opacity="0.9"/>
<text font-family="sans-serif" font-size="8" font-weight="600" fill="rgba(255,255,255,0.4)" x="445" y="120" text-anchor="middle">mapped</text>

<!-- PANEL 3 -->
<rect x="478" y="8" width="190" height="260" rx="22" fill="rgba(255,255,255,0.09)" stroke="rgba(255,255,255,0.18)" stroke-width="1.2"/>
<rect x="492" y="24" width="162" height="232" rx="12" fill="white" stroke="rgba(43,157,144,0.25)" stroke-width="1"/>
<rect x="492" y="24" width="162" height="18" rx="12" fill="#0C1B28"/>
<rect x="492" y="32" width="162" height="10" fill="#0C1B28"/>
<circle cx="502" cy="33" r="3" fill="#ff5f57" opacity="0.85"/>
<circle cx="512" cy="33" r="3" fill="#febc2e" opacity="0.85"/>
<circle cx="522" cy="33" r="3" fill="#28c840" opacity="0.85"/>
<rect x="534" y="27" width="112" height="10" rx="5" fill="rgba(255,255,255,0.08)"/>
<text font-family="sans-serif" font-size="9.5" font-weight="800" fill="#0D1F1E" x="502" y="58">My Timesheet</text>
<text font-family="sans-serif" font-size="7" fill="#7A9E9A" x="502" y="69">Mon Mar 17 · auto-categorized</text>
<rect x="492" y="73" width="162" height="11" fill="#F4FAFA"/>
<text font-family="sans-serif" font-size="6.5" font-weight="700" fill="#3D5C58" x="500" y="82">CLIENT</text>
<text font-family="sans-serif" font-size="6.5" font-weight="700" fill="#3D5C58" x="590" y="82">HRS</text>
<text font-family="sans-serif" font-size="6.5" font-weight="700" fill="#3D5C58" x="620" y="82">STATUS</text>
<g class="r1">
  <line x1="492" y1="85" x2="654" y2="85" stroke="#DDE9E8" stroke-width="0.5"/>
  <text font-family="sans-serif" font-size="7.5" fill="#0D1F1E" x="500" y="97">Hartwell — Tax Review</text>
  <text font-family="sans-serif" font-size="7.5" font-weight="700" fill="#2B9D90" x="590" y="97">2.5h</text>
  <rect class="ck1" x="617" y="90" width="32" height="12" rx="6" fill="#E6F5F4"/>
  <text font-family="sans-serif" font-size="6.5" fill="#2B9D90" x="633" y="99" text-anchor="middle">v auto</text>
</g>
<g class="r2">
  <line x1="492" y1="101" x2="654" y2="101" stroke="#DDE9E8" stroke-width="0.5"/>
  <text font-family="sans-serif" font-size="7.5" fill="#0D1F1E" x="500" y="113">Meridian — Bookkeeping</text>
  <text font-family="sans-serif" font-size="7.5" font-weight="700" fill="#2B9D90" x="590" y="113">1.8h</text>
  <rect class="ck2" x="617" y="106" width="32" height="12" rx="6" fill="#E6F5F4"/>
  <text font-family="sans-serif" font-size="6.5" fill="#2B9D90" x="633" y="115" text-anchor="middle">v auto</text>
</g>
<g class="r3">
  <line x1="492" y1="117" x2="654" y2="117" stroke="#DDE9E8" stroke-width="0.5"/>
  <text font-family="sans-serif" font-size="7.5" fill="#0D1F1E" x="500" y="129">Stonebridge — Audit Prep</text>
  <text font-family="sans-serif" font-size="7.5" font-weight="700" fill="#2B9D90" x="590" y="129">3.2h</text>
  <rect class="ck3" x="617" y="122" width="32" height="12" rx="6" fill="#E6F5F4"/>
  <text font-family="sans-serif" font-size="6.5" fill="#2B9D90" x="633" y="131" text-anchor="middle">v auto</text>
</g>
<g class="r4">
  <line x1="492" y1="133" x2="654" y2="133" stroke="#DDE9E8" stroke-width="0.5"/>
  <text font-family="sans-serif" font-size="7.5" fill="#0D1F1E" x="500" y="145">Sunrise LLC — Advisory</text>
  <text font-family="sans-serif" font-size="7.5" font-weight="700" fill="#2B9D90" x="590" y="145">0.5h</text>
  <rect class="ck4" x="617" y="138" width="32" height="12" rx="6" fill="#E6F5F4"/>
  <text font-family="sans-serif" font-size="6.5" fill="#2B9D90" x="633" y="147" text-anchor="middle">v auto</text>
</g>
<g class="r5">
  <line x1="492" y1="149" x2="654" y2="149" stroke="#DDE9E8" stroke-width="0.5"/>
  <text font-family="sans-serif" font-size="7.5" fill="#0D1F1E" x="500" y="161">Internal — Admin</text>
  <text font-family="sans-serif" font-size="7.5" font-weight="700" fill="#2B9D90" x="590" y="161">0.3h</text>
  <rect x="617" y="154" width="32" height="12" rx="6" fill="#FEF3C7"/>
  <text font-family="sans-serif" font-size="6.5" fill="#D97706" x="633" y="163" text-anchor="middle">1 edit</text>
</g>
<line x1="492" y1="167" x2="654" y2="167" stroke="#DDE9E8" stroke-width="1"/>
<text font-family="sans-serif" font-size="8" font-weight="800" fill="#0D1F1E" x="500" y="180">Total</text>
<text font-family="sans-serif" font-size="8" font-weight="800" fill="#2B9D90" x="590" y="180">8.3h</text>
<rect x="492" y="188" width="162" height="26" rx="13" fill="#2B9D90"/>
<text font-family="sans-serif" font-size="9" font-weight="700" fill="white" x="573" y="205" text-anchor="middle">Approve All</text>
<text font-family="sans-serif" font-size="11.5" font-weight="800" fill="white" x="573" y="246" text-anchor="middle">Auto Timesheet</text>
<text font-family="sans-serif" font-size="9" fill="rgba(255,255,255,0.45)" x="573" y="260" text-anchor="middle">Zero manual entry</text>
</svg>`;

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
        .nav-logo { display: flex; align-items: center; gap: 6px; }
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

        /* HERO — two column */
        .hero-section {
          background: linear-gradient(160deg, #2B9D90 0%, #1F7269 55%, #174F4A 100%);
          padding: 120px 32px 96px;
        }
        .hero-inner {
          max-width: 1320px; margin: 0 auto;
          display: grid; grid-template-columns: 1fr 1.5fr;
          gap: 48px; align-items: center;
        }
        .hero-eyebrow {
          display: inline-flex; align-items: center; gap: 7px;
          font-size: 10.5px; font-weight: 700; letter-spacing: 0.13em;
          text-transform: uppercase; color: rgba(255,255,255,0.45);
          margin-bottom: 24px;
        }
        .hero-dot { width: 6px; height: 6px; border-radius: 50%; background: #4ADE80; flex-shrink: 0; }
        .hero-h1 {
          font-size: clamp(36px, 4.5vw, 58px);
          font-weight: 800; letter-spacing: -0.03em; line-height: 1.05;
          color: #fff; margin-bottom: 18px;
        }
        .hero-h1 em { color: rgba(255,255,255,0.38); font-style: normal; }
        .hero-sub {
          font-size: 16px; color: rgba(255,255,255,0.55);
          line-height: 1.7; margin-bottom: 32px; font-weight: 400;
        }
        .hero-btns { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 52px; }
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
          display: grid; grid-template-columns: repeat(3, auto);
          border-top: 1px solid rgba(255,255,255,0.1); padding-top: 36px;
          width: fit-content; gap: 0;
        }
        .hero-stat { padding-right: 40px; }
        .hero-stat:not(:first-child) { padding-left: 40px; border-left: 1px solid rgba(255,255,255,0.1); }
        .hero-stat-val { font-size: 36px; font-weight: 800; letter-spacing: -0.03em; color: #fff; line-height: 1; margin-bottom: 4px; }
        .hero-stat-label { font-size: 12px; color: rgba(255,255,255,0.38); }

        /* Pipeline illustration right column */
        .hero-visual {
          position: relative;
          display: flex; align-items: center; justify-content: center;
          min-width: 0;
        }
        .hero-visual svg {
          width: 100%; min-width: 0; max-width: 780px;
          filter: drop-shadow(0 20px 40px rgba(0,0,0,0.22));
        }

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
        .int-abbr { 
          width: 32px; height: 32px; border-radius: 8px; 
          display: flex; align-items: center; justify-content: center;
          font-size: 11px; font-weight: 800; letter-spacing: -0.02em;
          flex-shrink: 0;
        }
        .int-name { font-size: 12.5px; font-weight: 600; color: var(--text); line-height: 1.2; }
        .int-cat  { font-size: 10.5px; color: var(--text-3); }

        .section { max-width: 1120px; margin: 0 auto; padding: 88px 32px; }
        .section-eyebrow { font-size: 10.5px; font-weight: 700; letter-spacing: 0.13em; text-transform: uppercase; color: var(--teal-mid); margin-bottom: 12px; }
        .section-h2 { font-size: clamp(28px, 3.5vw, 40px); font-weight: 800; letter-spacing: -0.025em; line-height: 1.1; color: var(--text); margin-bottom: 40px; }
        .section-sub { font-size: 16px; color: var(--text-2); line-height: 1.65; max-width: 500px; margin-bottom: 40px; margin-top: -24px; }
        .hr { border: none; border-top: 1px solid var(--line); }
        
        .steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
        @media (max-width: 768px) { .steps { grid-template-columns: 1fr; } }
        .step-card {
          background: var(--white); border: 1px solid var(--line);
          border-radius: 20px; padding: 36px 32px;
          transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
          position: relative; overflow: hidden;
        }
        .step-card::before {
          content: attr(data-step);
          position: absolute; top: -10px; right: 20px;
          font-size: 80px; font-weight: 900; letter-spacing: -0.05em;
          color: var(--teal-light); line-height: 1;
          pointer-events: none; user-select: none;
        }
        .step-card:hover { transform: translateY(-3px); box-shadow: 0 12px 32px rgba(43,157,144,0.12); border-color: var(--teal-border); }
        .step-num { font-size: 10px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: var(--teal-mid); margin-bottom: 20px; }
        .step-icon { width: 44px; height: 44px; border-radius: 12px; background: linear-gradient(135deg, var(--teal-light), #d0f0ec); border: 1px solid var(--teal-border); display: flex; align-items: center; justify-content: center; margin-bottom: 20px; }
        .step-icon svg { width: 20px; height: 20px; color: var(--teal); }
        .step-card h3 { font-size: 16px; font-weight: 800; letter-spacing: -0.02em; margin-bottom: 10px; color: var(--text); }
        .step-card p { font-size: 13.5px; color: var(--text-2); line-height: 1.7; }

        .feat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
        @media (max-width: 900px) { .feat-grid { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 560px) { .feat-grid { grid-template-columns: 1fr; } }
        .feat-card {
          background: var(--white); border: 1px solid var(--line);
          border-radius: 20px; padding: 32px 28px;
          transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
          display: flex; flex-direction: column; gap: 0;
        }
        .feat-card:hover { transform: translateY(-3px); box-shadow: 0 12px 32px rgba(43,157,144,0.12); border-color: var(--teal-border); }
        .feat-card:nth-child(1) .feat-icon { background: linear-gradient(135deg, #E6F5F4, #d0f0ec); }
        .feat-card:nth-child(2) .feat-icon { background: linear-gradient(135deg, #E0F3FD, #c7eaf9); }
        .feat-card:nth-child(3) .feat-icon { background: linear-gradient(135deg, #EEF2FF, #dde4ff); }
        .feat-card:nth-child(4) .feat-icon { background: linear-gradient(135deg, #FFF7ED, #fde8cc); }
        .feat-card:nth-child(5) .feat-icon { background: linear-gradient(135deg, #F0FDF4, #d1fae5); }
        .feat-card:nth-child(6) .feat-icon { background: linear-gradient(135deg, #FDF4FF, #f3e8ff); }
        .feat-icon { width: 44px; height: 44px; border-radius: 12px; border: 1px solid rgba(0,0,0,0.06); display: flex; align-items: center; justify-content: center; margin-bottom: 20px; }
        .feat-icon svg { width: 18px; height: 18px; color: var(--teal); }
        .feat-card:nth-child(3) .feat-icon svg { color: #6366F1; }
        .feat-card:nth-child(4) .feat-icon svg { color: #F97316; }
        .feat-card:nth-child(5) .feat-icon svg { color: #22C55E; }
        .feat-card:nth-child(6) .feat-icon svg { color: #A855F7; }
        .feat-card h3 { font-size: 14.5px; font-weight: 800; letter-spacing: -0.015em; margin-bottom: 8px; color: var(--text); }
        .feat-card p { font-size: 13px; color: var(--text-2); line-height: 1.65; }

        .compare-grid { display: grid; grid-template-columns: 1fr 1fr; border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }
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
        .ci-icon { width: 17px; height: 17px; border-radius: 50%; flex-shrink: 0; margin-top: 1px; display: flex; align-items: center; justify-content: center; font-size: 9px; font-weight: 700; }
        .ci-icon.old { background: #EAEAEA; color: #AAAAAA; }
        .ci-icon.new { background: var(--teal); color: #fff; }

        .pricing-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; max-width: 780px; }
        @media (max-width: 600px) { .pricing-grid { grid-template-columns: 1fr; } }
        .plan { border: 1px solid var(--line); border-radius: 16px; padding: 36px 32px; background: var(--white); }
        .plan.exec { background: var(--teal); border-color: var(--teal); }
        .plan-badge { display: inline-block; font-size: 9.5px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; background: var(--teal-mid); color: #fff; padding: 3px 9px; border-radius: 20px; margin-bottom: 18px; }
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
        .plan-cta { display: block; width: 100%; text-align: center; padding: 12px; border-radius: 999px; font-size: 14px; font-weight: 600; font-family: inherit; cursor: pointer; border: none; transition: opacity 0.15s, transform 0.1s; }
        .plan-cta:active { transform: scale(0.98); }
        .plan.exec .plan-cta { background: var(--teal-mid); color: #fff; }
        .plan.exec .plan-cta:hover { opacity: 0.88; }
        .plan:not(.exec) .plan-cta { background: var(--teal-light); color: var(--teal-dark); }
        .plan:not(.exec) .plan-cta:hover { opacity: 0.8; }
        .pricing-note { font-size: 12.5px; color: var(--text-3); margin-top: 16px; }

        .cta-section { background: var(--teal); padding: 80px 32px; text-align: center; }
        .cta-inner { max-width: 560px; margin: 0 auto; }
        .cta-section h2 { font-size: clamp(26px, 4vw, 40px); font-weight: 800; letter-spacing: -0.025em; color: #fff; margin-bottom: 14px; line-height: 1.1; }
        .cta-section p { font-size: 15px; color: rgba(255,255,255,0.5); line-height: 1.65; margin-bottom: 32px; }

        .footer { border-top: 1px solid var(--line); background: var(--bg); }
        .footer-inner { max-width: 1120px; margin: 0 auto; padding: 32px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
        .footer-logo { display: flex; align-items: center; gap: 8px; }
        .footer-logo img { width: 28px; height: 28px; opacity: 0.7; }
        .footer-logo-name { font-size: 14px; font-weight: 800; letter-spacing: -0.02em; color: var(--text); }
        .footer-by { color: var(--text-3); font-weight: 400; font-size: 12px; }
        .footer-links { display: flex; gap: 20px; }
        .footer-links a { font-size: 12px; color: var(--text-3); transition: color 0.15s; }
        .footer-links a:hover { color: var(--text); }
        .footer-copy { font-size: 12px; color: var(--text-3); }

        @media (max-width: 900px) {
          .hero-inner { grid-template-columns: 1fr; }
          .hero-visual { display: flex; width: 100%; overflow: hidden; }
          .nav-links { display: none; }
          .hero-stats { grid-template-columns: 1fr 1fr; gap: 16px; width: 100%; padding-top: 28px; }
          .hero-stat { padding-right: 0; }
          .hero-stat:not(:first-child) { padding-left: 0; border-left: none; }
          .hero-stat-val { font-size: 26px; }
        }

        @media (max-width: 480px) {
          .hero-section { padding: 100px 20px 64px; }
          .hero-stats { grid-template-columns: 1fr 1fr; gap: 14px; width: 100%; padding-top: 24px; }
          .hero-stat { padding-right: 0; }
          .hero-stat:not(:first-child) { padding-left: 0; border-left: none; }
          .hero-stat-val { font-size: 24px; }
          .section { padding: 56px 20px; }
          .nav-inner { padding: 0 20px; }
          .footer-inner { flex-direction: column; align-items: flex-start; gap: 16px; }
          .compare-col:first-child { border-right: none; border-bottom: 1px solid var(--line); }
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
            <a href="/request-access" className="btn-primary">
              Request Access <ChevronRight size={14} />
            </a>
          </div>
        </div>
      </nav>

      {/* HERO — two column */}
      <section className="hero-section">
        <div className="hero-inner">
          {/* LEFT: copy + stats */}
          <div>
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
              <a href="/request-access" className="btn-hero-primary">
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

          {/* RIGHT: pipeline illustration */}
          <div className="hero-visual" dangerouslySetInnerHTML={{ __html: PIPELINE_SVG }} />
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
                <div className="int-abbr" style={{ background: int.bg, color: int.color }}>
                  {int.abbr}
                </div>
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
            <div key={i} className="step-card" data-step={step}>
              <div className="step-num">Step {step}</div>
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
              <a href="/request-access" className="plan-cta">
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
          <a href="/request-access" className="btn-hero-primary">
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