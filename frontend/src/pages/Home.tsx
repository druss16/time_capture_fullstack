// Home.tsx — TimeTracker · Modern, Calm
import { Link } from "react-router-dom";
import { ArrowRight, Clock, Check, BarChart3, FileText, Zap, ChevronRight } from "lucide-react";

const NAV_LINKS = [
  { label: "How It Works", href: "#how-it-works" },
  { label: "Features",     href: "#features"     },
  { label: "Pricing",      href: "#pricing"      },
];

// ─── HERO SVG: Option B ─ Floating 3-layer depth
// Layer 1: Desktop agent — UltraTax / Outlook / Excel bubbles float up, scan line sweeps, Hartwell timer ticks
// Layer 2: Auto-filled timesheet — rows appear one by one, Approve All button
// Layer 3: Clean margin bar chart — bars grow, Hartwell winner badge
const HERO_SVG = `<svg viewBox="0 -8 340 520" width="100%" xmlns="http://www.w3.org/2000/svg">
<defs>
  <style>
    @keyframes ut{0%,5%{opacity:0;transform:translateY(10px)}16%,50%{opacity:1;transform:translateY(0)}60%,100%{opacity:0;transform:translateY(-8px)}}
    @keyframes ol{0%,25%{opacity:0;transform:translateY(10px)}36%,66%{opacity:1;transform:translateY(0)}76%,100%{opacity:0;transform:translateY(-8px)}}
    @keyframes xl{0%,46%{opacity:0;transform:translateY(10px)}57%,83%{opacity:1;transform:translateY(0)}93%,100%{opacity:0;transform:translateY(-8px)}}
    @keyframes sc{0%{transform:translateY(0);opacity:0}5%{opacity:.55}90%{opacity:.55}100%{transform:translateY(62px);opacity:0}}
    @keyframes xlscan{0%{transform:translateY(0);opacity:0}6%{opacity:.6}88%{opacity:.6}100%{transform:translateY(50px);opacity:0}}
    @keyframes r1{0%,28%{opacity:0;transform:translateX(-6px)}42%,100%{opacity:1;transform:translateX(0)}}
    @keyframes r2{0%,42%{opacity:0;transform:translateX(-6px)}56%,100%{opacity:1;transform:translateX(0)}}
    @keyframes r3{0%,56%{opacity:0;transform:translateX(-6px)}70%,100%{opacity:1;transform:translateX(0)}}
    @keyframes r4{0%,68%{opacity:0;transform:translateX(-6px)}82%,100%{opacity:1;transform:translateX(0)}}
    @keyframes tot{0%,80%{opacity:0}90%,100%{opacity:1}}
    @keyframes appr{0%,86%{opacity:0;transform:scale(.92)}95%,100%{opacity:1;transform:scale(1)}}
    @keyframes win{0%,92%{opacity:0;transform:translateY(4px)}100%{opacity:1;transform:translateY(0)}}
    @keyframes a1{0%,24%{opacity:0}36%,100%{opacity:1}}
    @keyframes a2{0%,76%{opacity:0}86%,100%{opacity:1}}
    @keyframes pulse{0%,100%{opacity:1}50%{opacity:.15}}
    @keyframes barchart{0%,76%{transform:scaleY(0)}90%,100%{transform:scaleY(1)}}
    @keyframes t0{0%,100%{opacity:1}25%,75%{opacity:0}}
    @keyframes t1{0%,12%{opacity:0}18%,30%{opacity:1}36%,100%{opacity:0}}
    @keyframes t2{0%,37%{opacity:0}43%,55%{opacity:1}61%,100%{opacity:0}}
    @keyframes t3{0%,62%{opacity:0}68%,80%{opacity:1}86%,100%{opacity:0}}
    @keyframes lbl{0%,24%{opacity:0;transform:translateX(-6px)}36%,100%{opacity:1;transform:translateX(0)}}
    .ut{animation:ut 9s ease-in-out infinite}
    .ol{animation:ol 9s ease-in-out infinite}
    .xl{animation:xl 9s ease-in-out infinite}
    .sc{animation:sc 2.8s ease-in-out infinite}
    .xlsc{animation:xlscan 2.4s ease-in-out infinite}
    .r1{animation:r1 9s ease infinite}
    .r2{animation:r2 9s ease infinite}
    .r3{animation:r3 9s ease infinite}
    .r4{animation:r4 9s ease infinite}
    .tot{animation:tot 9s ease infinite}
    .appr{animation:appr 9s ease infinite}
    .win{animation:win 9s ease infinite}
    .a1{animation:a1 9s ease infinite}
    .a2{animation:a2 9s ease infinite}
    .pulse{animation:pulse 2s ease-in-out infinite}
    .b1{animation:barchart 9s ease infinite;transform-origin:62px 476px}
    .b2{animation:barchart 9s ease infinite .15s;transform-origin:122px 476px}
    .b3{animation:barchart 9s ease infinite .3s;transform-origin:182px 476px}
    .b4{animation:barchart 9s ease infinite .45s;transform-origin:242px 476px}
    .tm0{animation:t0 4s steps(1) infinite}
    .tm1{animation:t1 4s steps(1) infinite}
    .tm2{animation:t2 4s steps(1) infinite}
    .tm3{animation:t3 4s steps(1) infinite}
    .lbl{animation:lbl 9s ease infinite}
  </style>
  <linearGradient id="hsg" x1="0%" y1="0%" x2="100%" y2="0%">
    <stop offset="0%" stop-color="#00e5cc" stop-opacity="0"/>
    <stop offset="50%" stop-color="#00e5cc" stop-opacity=".7"/>
    <stop offset="100%" stop-color="#00e5cc" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="hsgxl" x1="0%" y1="0%" x2="100%" y2="0%">
    <stop offset="0%" stop-color="#4ADE80" stop-opacity="0"/>
    <stop offset="50%" stop-color="#4ADE80" stop-opacity=".6"/>
    <stop offset="100%" stop-color="#4ADE80" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="hbg" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" stop-color="#2B9D90"/>
    <stop offset="100%" stop-color="#1a6b63"/>
  </linearGradient>
  <clipPath id="hcc"><rect x="28" y="60" width="172" height="70"/></clipPath>
  <clipPath id="xlcc"><rect x="144" y="60" width="100" height="70"/></clipPath>
  <filter id="sd1"><feDropShadow dx="0" dy="6" stdDeviation="10" flood-color="rgba(0,0,0,0.28)"/></filter>
  <filter id="sd2"><feDropShadow dx="0" dy="4" stdDeviation="8" flood-color="rgba(0,0,0,0.18)"/></filter>
</defs>

<!-- ══ CARD 1: Desktop monitor ══ -->
<g filter="url(#sd1)">
  <rect x="8" y="14" width="252" height="162" rx="14" fill="#1A2B28" stroke="rgba(255,255,255,.15)" stroke-width="1"/>
  <rect x="16" y="22" width="236" height="138" rx="8" fill="#0D1F1C"/>
  <rect x="16" y="22" width="236" height="16" rx="8" fill="#0A1714"/>
  <rect x="16" y="30" width="236" height="8" fill="#0A1714"/>
  <circle cx="25" cy="30" r="3" fill="#ff5f57" opacity=".8"/>
  <circle cx="35" cy="30" r="3" fill="#febc2e" opacity=".8"/>
  <circle cx="45" cy="30" r="3" fill="#28c840" opacity=".8"/>
  <text font-family="DM Sans,system-ui,sans-serif" font-size="6.5" font-weight="600" fill="rgba(255,255,255,.5)" x="58" y="34">File  Edit  View  Window</text>
  <text font-family="DM Sans,system-ui,sans-serif" font-size="6.5" fill="rgba(255,255,255,.4)" x="210" y="34">9:41 AM</text>
  <circle class="pulse" cx="244" cy="30" r="3" fill="#2B9D90"/>
  <!-- UltraTax window BEHIND -->
  <rect x="20" y="42" width="180" height="100" rx="6" fill="#162D40" stroke="rgba(255,255,255,.06)" stroke-width="1"/>
  <rect x="20" y="42" width="180" height="16" rx="6" fill="#162C42"/>
  <rect x="20" y="50" width="180" height="8" fill="#162C42"/>
  <circle cx="26" cy="47" r="3" fill="#ff5f57" opacity=".7"/>
  <circle cx="34" cy="47" r="3" fill="#febc2e" opacity=".7"/>
  <circle cx="42" cy="47" r="3" fill="#28c840" opacity=".7"/>
  <text font-family="DM Sans,system-ui,sans-serif" font-size="6.5" font-weight="600" fill="rgba(255,255,255,.35)" x="110" y="55" text-anchor="middle">UltraTax CS — Hartwell_1040</text>
  <rect x="28" y="62" width="164" height="5" rx="2" fill="rgba(255,255,255,.07)"/>
  <rect x="28" y="71" width="100" height="5" rx="2" fill="rgba(255,255,255,.08)"/>
  <rect x="132" y="71" width="60" height="5" rx="2" fill="#2B9D90" opacity=".35"/>
  <rect x="28" y="80" width="140" height="5" rx="2" fill="rgba(255,255,255,.05)"/>
  <rect x="28" y="89" width="80" height="5" rx="2" fill="rgba(255,255,255,.05)"/>
  <rect x="28" y="98" width="120" height="5" rx="2" fill="rgba(255,255,255,.06)"/>
  <rect x="28" y="107" width="60" height="5" rx="2" fill="rgba(255,255,255,.04)"/>
  <rect x="28" y="118" width="164" height="10" rx="3" fill="rgba(43,157,144,.12)" stroke="rgba(43,157,144,.25)" stroke-width="1"/>
  <text font-family="DM Sans,system-ui,sans-serif" font-size="6" fill="#2B9D90" x="110" y="125.5" text-anchor="middle">1040 · Hartwell, James R. · 2024</text>
  <rect class="sc" x="28" y="60" width="172" height="2" rx="1" fill="url(#hsg)" clip-path="url(#hcc)" opacity=".4"/>  <!-- Excel window FRONT (active) -->
  <rect x="140" y="42" width="108" height="100" rx="6" fill="#1A4828" stroke="rgba(255,255,255,.18)" stroke-width="1"/>
  <rect x="140" y="42" width="108" height="14" rx="6" fill="#0C2414"/>
  <rect x="140" y="48" width="108" height="8" fill="#0C2414"/>
  <text font-family="DM Sans,system-ui,sans-serif" font-size="6" font-weight="600" fill="rgba(255,255,255,.7)" x="194" y="56" text-anchor="middle">Excel — WIP_March.xlsx</text>
  <rect x="145" y="60" width="98" height="8" rx="1.5" fill="rgba(255,255,255,.14)"/>
  <rect x="145" y="70" width="98" height="6" rx="1.5" fill="rgba(255,255,255,.06)"/>
  <rect x="145" y="78" width="98" height="6" rx="1.5" fill="rgba(255,255,255,.07)"/>
  <rect x="145" y="86" width="98" height="6" rx="1.5" fill="rgba(255,255,255,.05)"/>
  <rect x="145" y="94" width="98" height="6" rx="1.5" fill="rgba(255,255,255,.07)"/>
  <rect x="145" y="102" width="98" height="6" rx="1.5" fill="rgba(255,255,255,.04)"/>
  <rect x="145" y="110" width="70" height="6" rx="1.5" fill="rgba(255,255,255,.06)"/>
  <rect class="xlsc" x="144" y="60" width="100" height="2" rx="1" fill="url(#hsg)" clip-path="url(#xlcc)"/>


  <!-- macOS dock / taskbar at screen bottom — shows agent running invisibly -->
  <rect x="16" y="146" width="236" height="14" rx="0" fill="#07100F"/>
  <rect x="16" y="151" width="236" height="9" fill="#07100F"/>
  <!-- Dock app icons -->
  <rect x="64"  y="153" width="8" height="8" rx="2" fill="#2CA01C" opacity=".7"/>
  <rect x="76"  y="153" width="8" height="8" rx="2" fill="#217346" opacity=".8"/>
  <rect x="88"  y="153" width="8" height="8" rx="2" fill="#1F4B99" opacity=".7"/>
  <rect x="100" y="153" width="8" height="8" rx="2" fill="#0078D4" opacity=".7"/>
  <line x1="114" y1="153" x2="114" y2="161" stroke="rgba(255,255,255,.12)" stroke-width=".8"/>
  <!-- System tray right side -->
  <text font-family="DM Sans,system-ui,sans-serif" font-size="5" fill="rgba(255,255,255,.3)" x="120" y="159">9:41 AM</text>
  <!-- TimeTracker tray dot — glowing teal -->
  <circle cx="236" cy="157" r="3.5" fill="#2B9D90" opacity=".9"/>
  <circle cx="236" cy="157" r="5.5" fill="none" stroke="#2B9D90" stroke-width=".8" opacity=".35"/>

</g>

<!-- Agent badge -->
<rect x="8" y="150" width="214" height="28" rx="8" fill="rgba(8,20,18,.92)" stroke="rgba(43,157,144,.4)" stroke-width="1"/>
<circle cx="21" cy="164" r="4.5" fill="#2B9D90"/>
<text font-family="DM Sans,system-ui,sans-serif" font-size="7.5" font-weight="700" fill="white" x="31" y="161">TimeTracker — Silent Agent</text>
<text font-family="DM Sans,system-ui,sans-serif" font-size="7" fill="rgba(255,255,255,.45)" x="31" y="172">Hartwell · Excel · tracking</text>
<rect x="174" y="156" width="42" height="16" rx="8" fill="rgba(43,157,144,.2)" stroke="rgba(43,157,144,.5)" stroke-width="1"/>
<text class="tm0" font-family="DM Sans,system-ui,sans-serif" font-size="8" font-weight="700" fill="#2B9D90" x="195" y="167.5" text-anchor="middle">0:21</text>
<text class="tm1" font-family="DM Sans,system-ui,sans-serif" font-size="8" font-weight="700" fill="#2B9D90" x="195" y="167.5" text-anchor="middle">0:22</text>
<text class="tm2" font-family="DM Sans,system-ui,sans-serif" font-size="8" font-weight="700" fill="#2B9D90" x="195" y="167.5" text-anchor="middle">0:23</text>
<text class="tm3" font-family="DM Sans,system-ui,sans-serif" font-size="8" font-weight="700" fill="#2B9D90" x="195" y="167.5" text-anchor="middle">0:24</text>

<!-- Monitor stand -->
<rect x="118" y="176" width="20" height="8" rx="2" fill="#1A2B28"/>
<rect x="108" y="183" width="40" height="4" rx="2" fill="#162520"/>

<!-- App bubbles -->
<g class="ut"><rect x="8" y="2" width="80" height="17" rx="8.5" fill="#1F4B99"/><text font-family="DM Sans,system-ui,sans-serif" font-size="7.5" font-weight="700" fill="white" x="48" y="14" text-anchor="middle">UltraTax CS</text></g>
<g class="ol"><rect x="100" y="0" width="66" height="17" rx="8.5" fill="#0078D4"/><text font-family="DM Sans,system-ui,sans-serif" font-size="7.5" font-weight="700" fill="white" x="133" y="12" text-anchor="middle">Outlook</text></g>
<g class="xl"><rect x="178" y="2" width="52" height="17" rx="8.5" fill="#217346"/><text font-family="DM Sans,system-ui,sans-serif" font-size="7.5" font-weight="700" fill="white" x="204" y="14" text-anchor="middle">Excel</text></g>

<!-- ── Arrow 1: short line + solid pill label to the right ── -->
<g class="a1">
  <line x1="120" y1="190" x2="120" y2="206" stroke="rgba(43,157,144,.6)" stroke-width="1.5" stroke-dasharray="3 2.5"/>
  <polygon points="116,204 120,210 124,204" fill="rgba(43,157,144,.6)"/>
  <!-- Bright solid pill — stands out -->
  <rect x="132" y="192" width="136" height="20" rx="10" fill="#2B9D90"/>
  <text font-family="DM Sans,system-ui,sans-serif" font-size="8" font-weight="700" fill="white" x="200" y="205.5" text-anchor="middle">✦ AI auto-classified</text>
</g>

<!-- ══ CARD 2: Timesheet — slightly smaller (scale down heights) ══ -->
<g filter="url(#sd2)">
  <rect x="46" y="218" width="276" height="140" rx="14" fill="white" stroke="#DDE9E8" stroke-width="1"/>
  <rect x="46" y="218" width="276" height="24" rx="14" fill="#0D1F1E"/>
  <rect x="46" y="230" width="276" height="12" fill="#0D1F1E"/>
  <circle cx="58" cy="230" r="3" fill="#ff5f57" opacity=".7"/>
  <circle cx="67" cy="230" r="3" fill="#febc2e" opacity=".7"/>
  <circle cx="76" cy="230" r="3" fill="#28c840" opacity=".7"/>
  <text font-family="DM Sans,system-ui,sans-serif" font-size="7.5" fill="rgba(255,255,255,.5)" x="88" y="234">My Timesheet · auto-categorized</text>
  <rect x="46" y="242" width="276" height="11" fill="#F8FAF9"/>
  <text font-family="DM Sans,system-ui,sans-serif" font-size="6" font-weight="700" fill="#7A9E9A" x="57" y="250" letter-spacing=".3">CLIENT</text>
  <text font-family="DM Sans,system-ui,sans-serif" font-size="6" font-weight="700" fill="#7A9E9A" x="240" y="250">HRS</text>
  <text font-family="DM Sans,system-ui,sans-serif" font-size="6" font-weight="700" fill="#7A9E9A" x="271" y="250">STATUS</text>
  <g class="r1">
    <line x1="57" y1="255" x2="312" y2="255" stroke="#DDE9E8" stroke-width=".5"/>
    <rect x="57" y="258" width="5" height="5" rx="1.5" fill="#2B9D90"/>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="7.5" fill="#0D1F1E" x="66" y="265">Hartwell — Tax Review</text>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="7.5" font-weight="700" fill="#2B9D90" x="240" y="265">2.5h</text>
    <rect x="265" y="257" width="34" height="10" rx="5" fill="#E6F5F4"/>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="6" fill="#2B9D90" x="282" y="264.5" text-anchor="middle">✓ auto</text>
  </g>
  <g class="r2">
    <line x1="57" y1="270" x2="312" y2="270" stroke="#DDE9E8" stroke-width=".5"/>
    <rect x="57" y="273" width="5" height="5" rx="1.5" fill="#34B5A7"/>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="7.5" fill="#0D1F1E" x="66" y="280">Meridian — Bookkeeping</text>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="7.5" font-weight="700" fill="#2B9D90" x="240" y="280">1.8h</text>
    <rect x="265" y="272" width="34" height="10" rx="5" fill="#E6F5F4"/>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="6" fill="#2B9D90" x="282" y="279.5" text-anchor="middle">✓ auto</text>
  </g>
  <g class="r3">
    <line x1="57" y1="285" x2="312" y2="285" stroke="#DDE9E8" stroke-width=".5"/>
    <rect x="57" y="288" width="5" height="5" rx="1.5" fill="#2B9D90"/>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="7.5" fill="#0D1F1E" x="66" y="295">Stonebridge — Audit Prep</text>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="7.5" font-weight="700" fill="#2B9D90" x="240" y="295">3.2h</text>
    <rect x="265" y="287" width="34" height="10" rx="5" fill="#E6F5F4"/>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="6" fill="#2B9D90" x="282" y="294.5" text-anchor="middle">✓ auto</text>
  </g>
  <g class="r4">
    <line x1="57" y1="300" x2="312" y2="300" stroke="#DDE9E8" stroke-width=".5"/>
    <rect x="57" y="303" width="5" height="5" rx="1.5" fill="#A7F3D0"/>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="7.5" fill="#0D1F1E" x="66" y="310">Sunrise — Advisory</text>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="7.5" font-weight="700" fill="#2B9D90" x="240" y="310">0.5h</text>
    <rect x="265" y="302" width="34" height="10" rx="5" fill="#FEF3C7"/>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="6" fill="#D97706" x="282" y="309.5" text-anchor="middle">1 edit</text>
  </g>
  <g class="tot">
    <line x1="57" y1="316" x2="312" y2="316" stroke="#DDE9E8" stroke-width="1"/>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="8.5" font-weight="800" fill="#0D1F1E" x="57" y="328">Total</text>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="8.5" font-weight="800" fill="#2B9D90" x="240" y="328">8.0h</text>
  </g>
  <g class="appr">
    <rect x="57" y="334" width="254" height="20" rx="10" fill="#2B9D90"/>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="9.5" font-weight="700" fill="white" x="184" y="348" text-anchor="middle">Approve All</text>
  </g>
</g>

<!-- Arrow 2 — no label -->
<g class="a2">
  <line x1="184" y1="362" x2="184" y2="374" stroke="#2B9D90" stroke-width="1.5" stroke-dasharray="3 2.5" opacity=".6"/>
  <polygon points="180,372 184,378 188,372" fill="#2B9D90" opacity=".6"/>
</g>

<!-- ══ CARD 3: Margin chart — bigger, baseline at y=476 ══ -->
<g filter="url(#sd2)">
  <rect x="14" y="382" width="310" height="122" rx="14" fill="#0F2E2A" stroke="rgba(255,255,255,.1)" stroke-width="1"/>
  <text font-family="DM Sans,system-ui,sans-serif" font-size="7.5" font-weight="700" fill="rgba(255,255,255,.4)" x="28" y="400" letter-spacing=".8">MARGIN BY CLIENT</text>
  <!-- Grid lines -->
  <line x1="28" y1="476" x2="310" y2="476" stroke="rgba(255,255,255,.1)" stroke-width="1"/>
  <line x1="28" y1="454" x2="310" y2="454" stroke="rgba(255,255,255,.05)" stroke-width=".8" stroke-dasharray="3 3"/>
  <line x1="28" y1="432" x2="310" y2="432" stroke="rgba(255,255,255,.04)" stroke-width=".8" stroke-dasharray="3 3"/>
  <!-- Bars — all bottom-anchored at baseline y=476, h+y=476 -->
  <!-- Smith:    h=36 → y=440 -->
  <rect class="b1" x="44"  y="440" width="36" height="36" rx="5" fill="url(#hbg)"/>
  <!-- Jones:    h=20 → y=456 -->
  <rect class="b2" x="108" y="456" width="36" height="20" rx="5" fill="url(#hbg)" opacity=".6"/>
  <!-- Hartwell: h=52 → y=424 -->
  <rect class="b3" x="164" y="424" width="44" height="52" rx="5" fill="url(#hbg)"/>
  <!-- Sunrise:  h=12 → y=464 -->
  <rect class="b4" x="234" y="464" width="36" height="12" rx="5" fill="url(#hbg)" opacity=".45"/>
  <!-- Labels -->
  <text font-family="DM Sans,system-ui,sans-serif" font-size="8" fill="rgba(255,255,255,.35)" x="62"  y="492" text-anchor="middle">Smith</text>
  <text font-family="DM Sans,system-ui,sans-serif" font-size="8" fill="rgba(255,255,255,.35)" x="126" y="492" text-anchor="middle">Jones</text>
  <text font-family="DM Sans,system-ui,sans-serif" font-size="8" font-weight="700" fill="#2B9D90" x="186" y="492" text-anchor="middle">Hartwell</text>
  <text font-family="DM Sans,system-ui,sans-serif" font-size="8" fill="rgba(255,255,255,.35)" x="252" y="492" text-anchor="middle">Sunrise</text>
  <!-- Winner badge -->
  <g class="win">
    <rect x="148" y="382" width="76" height="14" rx="7" fill="rgba(43,157,144,.25)" stroke="rgba(43,157,144,.5)" stroke-width="1"/>
    <text font-family="DM Sans,system-ui,sans-serif" font-size="7.5" font-weight="700" fill="#2B9D90" x="186" y="392.5" text-anchor="middle">↑ top margin</text>
  </g>
  <text font-family="DM Sans,system-ui,sans-serif" font-size="6.5" fill="rgba(255,255,255,.1)" x="163" y="498" text-anchor="middle">TimeTracker · MavOps AI</text>
</g>
</svg>`


// ─── Step Animations ─────────────────────────────────────────────────────────

const StepOneAnim = () => (
  <svg viewBox="0 0 240 160" width="100%" height="160" xmlns="http://www.w3.org/2000/svg" style={{display:"block"}}>
    <defs>
      <linearGradient id="s1s" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stopColor="#2B9D90" stopOpacity="0"/><stop offset="50%" stopColor="#2B9D90" stopOpacity="0.8"/><stop offset="100%" stopColor="#2B9D90" stopOpacity="0"/></linearGradient>
      <clipPath id="s1c"><rect x="30" y="18" width="180" height="108" rx="8"/></clipPath>
      <style>{`@keyframes s1m{0%{transform:translateY(0);opacity:0}10%{opacity:1}80%{opacity:1}100%{transform:translateY(68px);opacity:0}}@keyframes s1b{0%,15%{opacity:0;transform:translateY(6px)}25%,70%{opacity:1;transform:translateY(0)}85%,100%{opacity:0;transform:translateY(-6px)}}@keyframes s1d{0%,100%{opacity:1}50%{opacity:0.2}}.s1m{animation:s1m 2.6s ease-in-out infinite}.s1d{animation:s1d 1.8s ease-in-out infinite}.s1ba{animation:s1b 9s ease-in-out infinite 0s}.s1bb{animation:s1b 9s ease-in-out infinite 3s}.s1bc{animation:s1b 9s ease-in-out infinite 6s}`}</style>
    </defs>
    <rect x="30" y="18" width="180" height="108" rx="10" fill="white" stroke="#DDE9E8" strokeWidth="1.5"/>
    <rect x="30" y="18" width="180" height="22" rx="10" fill="#F0FAF8"/><rect x="30" y="28" width="180" height="12" fill="#F0FAF8"/>
    <circle cx="46" cy="29" r="3.5" fill="#fca5a5"/><circle cx="57" cy="29" r="3.5" fill="#fde68a"/><circle cx="68" cy="29" r="3.5" fill="#6ee7b7"/>
    <rect x="82" y="25.5" width="60" height="7" rx="3.5" fill="#D1EDE6"/>
    <rect x="42" y="50" width="8" height="8" rx="2" fill="#2B9D90"/><rect x="56" y="52" width="64" height="5" rx="2.5" fill="#CCEEE8"/><rect x="126" y="52" width="28" height="5" rx="2.5" fill="#E8F7F4"/>
    <rect x="42" y="66" width="8" height="8" rx="2" fill="#A7F3D0"/><rect x="56" y="68" width="50" height="5" rx="2.5" fill="#E8F7F4"/>
    <rect x="42" y="82" width="8" height="8" rx="2" fill="#D1FAE5"/><rect x="56" y="84" width="58" height="5" rx="2.5" fill="#F0FAF8"/>
    <rect x="42" y="98" width="8" height="8" rx="2" fill="#ECFDF5"/><rect x="56" y="100" width="44" height="5" rx="2.5" fill="#F5FCFB"/>
    <rect className="s1m" x="30" y="48" width="180" height="2" rx="1" fill="url(#s1s)" clipPath="url(#s1c)"/>
    <circle className="s1d" cx="170" cy="54" r="4" fill="#2B9D90"/>
    <rect x="112" y="126" width="16" height="12" rx="2" fill="#E0EBE7"/><rect x="98" y="136" width="44" height="5" rx="2.5" fill="#D1EDE6"/>
    <g className="s1ba"><rect x="142" y="10" width="82" height="18" rx="9" fill="#2B9D90"/><text x="183" y="22.5" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="700" fill="white" textAnchor="middle">Smith 1040 · 0:04</text></g>
    <g className="s1bb"><rect x="142" y="10" width="82" height="18" rx="9" fill="#0D1F1E"/><text x="183" y="22.5" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="700" fill="#2B9D90" textAnchor="middle">Johnson LLC · 0:11</text></g>
    <g className="s1bc"><rect x="142" y="10" width="82" height="18" rx="9" fill="#2B9D90"/><text x="183" y="22.5" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="700" fill="white" textAnchor="middle">Varacchi · 0:07</text></g>
    <circle className="s1d" cx="86" cy="150" r="3" fill="#2B9D90"/>
    <text x="95" y="154" fontFamily="DM Sans,sans-serif" fontSize="9" fontWeight="600" fill="#7A9E9A" letterSpacing="1.5">RUNNING SILENTLY</text>
  </svg>
);

const StepTwoAnim = () => (
  <svg viewBox="0 0 240 160" width="100%" height="160" xmlns="http://www.w3.org/2000/svg" style={{display:"block"}}>
    <defs>
      <style>{`@keyframes s2sp{to{transform:rotate(360deg)}}@keyframes s2pl{0%,100%{r:16;opacity:0.8}50%{r:18;opacity:0.4}}@keyframes s2a1{0%,20%{opacity:0;transform:translateX(-4px)}35%,100%{opacity:1;transform:translateX(0)}}@keyframes s2a2{0%,35%{opacity:0;transform:translateX(-4px)}50%,100%{opacity:1;transform:translateX(0)}}@keyframes s2a3{0%,50%{opacity:0;transform:translateX(-4px)}65%,100%{opacity:1;transform:translateX(0)}}.s2sp{animation:s2sp 4s linear infinite;transform-origin:120px 80px}.s2pl{animation:s2pl 2s ease-in-out infinite}.s2r1{animation:s2a1 4s ease infinite}.s2r2{animation:s2a2 4s ease infinite}.s2r3{animation:s2a3 4s ease infinite}`}</style>
    </defs>
    <rect x="8" y="28" width="76" height="104" rx="10" fill="white" stroke="#DDE9E8" strokeWidth="1.5"/>
    <text x="46" y="46" fontFamily="DM Sans,sans-serif" fontSize="7.5" fontWeight="700" fill="#7A9E9A" textAnchor="middle">ACTIVITY</text>
    <rect x="18" y="52" width="8" height="8" rx="2" fill="#A7F3D0"/><rect x="30" y="54" width="46" height="5" rx="2.5" fill="#E8F7F4"/>
    <rect x="18" y="66" width="8" height="8" rx="2" fill="#6EE7B7"/><rect x="30" y="68" width="38" height="5" rx="2.5" fill="#E8F7F4"/>
    <rect x="18" y="80" width="8" height="8" rx="2" fill="#A7F3D0"/><rect x="30" y="82" width="44" height="5" rx="2.5" fill="#E8F7F4"/>
    <line x1="84" y1="80" x2="96" y2="80" stroke="#2B9D90" strokeWidth="1.5" strokeDasharray="3 3"><animate attributeName="strokeDashoffset" values="12;0" dur="0.8s" repeatCount="indefinite"/></line>
    <circle cx="120" cy="80" r="28" fill="#F0FAF8" stroke="#CCEEE8" strokeWidth="1.5"/>
    <circle className="s2pl" cx="120" cy="80" r="16" fill="#E8F7F4" stroke="#A7F3D0" strokeWidth="1.5"/>
    <circle className="s2sp" cx="120" cy="80" r="22" fill="none" stroke="#2B9D90" strokeWidth="1.2" strokeDasharray="5 7" strokeOpacity="0.5"/>
    <circle cx="120" cy="80" r="10" fill="#2B9D90" opacity="0.85"/>
    <text x="120" y="78" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="800" fill="white" textAnchor="middle">AI</text>
    <text x="120" y="88" fontFamily="DM Sans,sans-serif" fontSize="6" fill="rgba(255,255,255,0.7)" textAnchor="middle">classify</text>
    <circle cx="120" cy="58" r="4" fill="#2B9D90"><animateTransform attributeName="transform" type="rotate" values="0 120 80;360 120 80" dur="3s" repeatCount="indefinite"/></circle>
    <line x1="144" y1="80" x2="156" y2="80" stroke="#2B9D90" strokeWidth="1.5" strokeDasharray="3 3"><animate attributeName="strokeDashoffset" values="12;0" dur="0.8s" repeatCount="indefinite"/></line>
    <rect x="156" y="28" width="76" height="104" rx="10" fill="white" stroke="#DDE9E8" strokeWidth="1.5"/>
    <text x="194" y="46" fontFamily="DM Sans,sans-serif" fontSize="7.5" fontWeight="700" fill="#7A9E9A" textAnchor="middle">CLIENTS</text>
    <g className="s2r1"><rect x="164" y="52" width="60" height="18" rx="5" fill="#F0FAF8" stroke="#CCEEE8" strokeWidth="1"/><rect x="168" y="56" width="8" height="8" rx="2" fill="#2B9D90"/><text x="180" y="63.5" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="600" fill="#0D1F1E">Smith 1040</text></g>
    <g className="s2r2"><rect x="164" y="74" width="60" height="18" rx="5" fill="#F0FAF8" stroke="#CCEEE8" strokeWidth="1"/><rect x="168" y="78" width="8" height="8" rx="2" fill="#6EE7B7"/><text x="180" y="85.5" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="600" fill="#0D1F1E">Johnson LLC</text></g>
    <g className="s2r3"><rect x="164" y="96" width="60" height="18" rx="5" fill="#F0FAF8" stroke="#CCEEE8" strokeWidth="1"/><rect x="168" y="100" width="8" height="8" rx="2" fill="#A7F3D0"/><text x="180" y="107.5" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="600" fill="#0D1F1E">Varacchi</text></g>
    <rect x="66" y="142" width="108" height="14" rx="7" fill="#2B9D90"/>
    <text x="120" y="152.5" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="700" fill="white" textAnchor="middle">Real-time · Zero manual fixes</text>
  </svg>
);

const StepThreeAnim = () => (
  <svg viewBox="0 0 240 160" width="100%" height="160" xmlns="http://www.w3.org/2000/svg" style={{display:"block"}}>
    <defs>
      <style>{`@keyframes s3a{0%,60%{opacity:1}70%,100%{opacity:0}}@keyframes s3bu{0%,60%{opacity:0;r:8}70%{opacity:0.5;r:16}100%{opacity:0;r:22}}@keyframes s3c1{0%,50%{opacity:0;transform:scale(0)}65%,100%{opacity:1;transform:scale(1)}}@keyframes s3c2{0%,60%{opacity:0;transform:scale(0)}75%,100%{opacity:1;transform:scale(1)}}@keyframes s3sy{0%,70%{opacity:0}80%,95%{opacity:1}100%{opacity:0}}.s3a{animation:s3a 3s ease-in-out infinite}.s3bu{animation:s3bu 3s ease-in-out infinite}.s3c1{animation:s3c1 3s ease-in-out infinite;transform-box:fill-box;transform-origin:center}.s3c2{animation:s3c2 3s ease-in-out infinite;transform-box:fill-box;transform-origin:center}.s3sy{animation:s3sy 3s ease-in-out infinite}`}</style>
    </defs>
    <rect x="8" y="14" width="96" height="132" rx="10" fill="white" stroke="#DDE9E8" strokeWidth="1.5"/>
    <rect x="8" y="14" width="96" height="24" rx="10" fill="#F0FAF8"/><rect x="8" y="26" width="96" height="12" fill="#F0FAF8"/>
    <text x="56" y="31" fontFamily="DM Sans,sans-serif" fontSize="7.5" fontWeight="700" fill="#7A9E9A" textAnchor="middle">TIMESHEET</text>
    <rect x="18" y="46" width="6" height="6" rx="1.5" fill="#2B9D90"/><rect x="28" y="47" width="38" height="4" rx="2" fill="#CCEEE8"/>
    <rect x="18" y="58" width="6" height="6" rx="1.5" fill="#6EE7B7"/><rect x="28" y="59" width="32" height="4" rx="2" fill="#E8F7F4"/>
    <rect x="18" y="70" width="6" height="6" rx="1.5" fill="#A7F3D0"/><rect x="28" y="71" width="42" height="4" rx="2" fill="#E8F7F4"/>
    <rect x="18" y="82" width="6" height="6" rx="1.5" fill="#D1FAE5"/><rect x="28" y="83" width="36" height="4" rx="2" fill="#F0FAF8"/>
    <line x1="18" y1="96" x2="94" y2="96" stroke="#DDE9E8" strokeWidth="1"/>
    <text x="18" y="108" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="800" fill="#0D1F1E">Total</text>
    <text x="70" y="108" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="800" fill="#2B9D90">8.3h</text>
    <g className="s3a"><rect x="18" y="116" width="76" height="22" rx="11" fill="#2B9D90"/><text x="56" y="130.5" fontFamily="DM Sans,sans-serif" fontSize="9" fontWeight="700" fill="white" textAnchor="middle">Approve ✓</text></g>
    <circle className="s3bu" cx="56" cy="127" r="8" fill="#2B9D90" opacity="0"/>
    <line x1="104" y1="80" x2="136" y2="80" stroke="#CCEEE8" strokeWidth="2" strokeDasharray="4 3"/>
    <polygon points="134,76 140,80 134,84" fill="#2B9D90"/>
    <circle r="4" fill="#2B9D90"><animate attributeName="cx" values="104;136" dur="1.2s" repeatCount="indefinite" calcMode="spline" keySplines="0.4 0 0.6 1"/><animate attributeName="opacity" values="1;0" dur="1.2s" repeatCount="indefinite"/><animate attributeName="cy" values="80;80" dur="1.2s" repeatCount="indefinite"/></circle>
    <rect x="136" y="14" width="96" height="132" rx="10" fill="white" stroke="#DDE9E8" strokeWidth="1.5"/>
    <rect x="136" y="14" width="96" height="24" rx="10" fill="#F0FAF8"/><rect x="136" y="26" width="96" height="12" fill="#F0FAF8"/>
    <text x="184" y="31" fontFamily="DM Sans,sans-serif" fontSize="7.5" fontWeight="700" fill="#7A9E9A" textAnchor="middle">SYNCED</text>
    <rect x="148" y="44" width="40" height="40" rx="10" fill="#2CA01C"/><text x="168" y="69" fontFamily="DM Sans,sans-serif" fontSize="14" fontWeight="900" fill="white" textAnchor="middle">QB</text>
    <rect x="200" y="44" width="40" height="40" rx="10" fill="#13B5EA"/><text x="220" y="69" fontFamily="DM Sans,sans-serif" fontSize="13" fontWeight="900" fill="white" textAnchor="middle">Xe</text>
    <g className="s3c1"><circle cx="168" cy="100" r="10" fill="#F0FAF8" stroke="#CCEEE8" strokeWidth="1.5"/><path d="M163 100 L167 104 L173 96" stroke="#2B9D90" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" fill="none"/></g>
    <g className="s3c2"><circle cx="220" cy="100" r="10" fill="#F0FAF8" stroke="#CCEEE8" strokeWidth="1.5"/><path d="M215 100 L219 104 L225 96" stroke="#2B9D90" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" fill="none"/></g>
    <g className="s3sy"><rect x="148" y="118" width="80" height="16" rx="8" fill="#2B9D90"/><text x="188" y="129.5" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="700" fill="white" textAnchor="middle">Hours synced ✓</text></g>
  </svg>
);


const FeatProfitabilityAnim = () => (
  <svg viewBox="0 0 280 160" width="100%" height="130" xmlns="http://www.w3.org/2000/svg" style={{ display: "block" }}>
    <defs>
      <style>{`
        @keyframes fa1-bar1 { 0%,10%{height:0;y:120} 40%,100%{height:64;y:56} }
        @keyframes fa1-bar2 { 0%,20%{height:0;y:120} 50%,100%{height:44;y:76} }
        @keyframes fa1-bar3 { 0%,30%{height:0;y:120} 60%,100%{height:80;y:40} }
        @keyframes fa1-bar4 { 0%,40%{height:0;y:120} 70%,100%{height:28;y:92} }
        @keyframes fa1-bar5 { 0%,50%{height:0;y:120} 80%,100%{height:56;y:64} }
        @keyframes fa1-lbl  { 0%,60%{opacity:0} 80%,100%{opacity:1} }
        @keyframes fa1-win  { 0%,65%{opacity:0;transform:translateY(6px)} 85%,100%{opacity:1;transform:translateY(0)} }
        .fa1-b1{animation:fa1-bar1 4s cubic-bezier(.4,0,.2,1) infinite}
        .fa1-b2{animation:fa1-bar2 4s cubic-bezier(.4,0,.2,1) infinite}
        .fa1-b3{animation:fa1-bar3 4s cubic-bezier(.4,0,.2,1) infinite}
        .fa1-b4{animation:fa1-bar4 4s cubic-bezier(.4,0,.2,1) infinite}
        .fa1-b5{animation:fa1-bar5 4s cubic-bezier(.4,0,.2,1) infinite}
        .fa1-lbl{animation:fa1-lbl 4s ease infinite}
        .fa1-win{animation:fa1-win 4s ease infinite}
      `}</style>
    </defs>
    <line x1="48" y1="120" x2="264" y2="120" stroke="#DDE9E8" strokeWidth="1"/>
    <line x1="48" y1="90"  x2="264" y2="90"  stroke="#DDE9E8" strokeWidth="0.5" strokeDasharray="3 3"/>
    <line x1="48" y1="60"  x2="264" y2="60"  stroke="#DDE9E8" strokeWidth="0.5" strokeDasharray="3 3"/>
    <text x="40" y="123" fontFamily="DM Sans,sans-serif" fontSize="7.5" fill="#7A9E9A" textAnchor="end">0%</text>
    <text x="40" y="93"  fontFamily="DM Sans,sans-serif" fontSize="7.5" fill="#7A9E9A" textAnchor="end">40%</text>
    <text x="40" y="63"  fontFamily="DM Sans,sans-serif" fontSize="7.5" fill="#7A9E9A" textAnchor="end">80%</text>
    <rect className="fa1-b1" x="58"  y="56" width="28" height="64" rx="5" fill="#2B9D90"/>
    <rect className="fa1-b2" x="100" y="76" width="28" height="44" rx="5" fill="#34B5A7" opacity="0.7"/>
    <rect className="fa1-b3" x="142" y="40" width="28" height="80" rx="5" fill="#2B9D90"/>
    <rect className="fa1-b4" x="184" y="92" width="28" height="28" rx="5" fill="#34B5A7" opacity="0.5"/>
    <rect className="fa1-b5" x="226" y="64" width="28" height="56" rx="5" fill="#34B5A7" opacity="0.8"/>
    <text className="fa1-lbl" x="72"  y="135" fontFamily="DM Sans,sans-serif" fontSize="7" fill="#7A9E9A" textAnchor="middle">Smith</text>
    <text className="fa1-lbl" x="114" y="135" fontFamily="DM Sans,sans-serif" fontSize="7" fill="#7A9E9A" textAnchor="middle">Jones</text>
    <text className="fa1-lbl" x="156" y="135" fontFamily="DM Sans,sans-serif" fontSize="7" fill="#7A9E9A" textAnchor="middle">Hartwell</text>
    <text className="fa1-lbl" x="198" y="135" fontFamily="DM Sans,sans-serif" fontSize="7" fill="#7A9E9A" textAnchor="middle">Sunrise</text>
    <text className="fa1-lbl" x="240" y="135" fontFamily="DM Sans,sans-serif" fontSize="7" fill="#7A9E9A" textAnchor="middle">Mercer</text>
    <g className="fa1-win">
      <rect x="128" y="22" width="56" height="16" rx="8" fill="#2B9D90"/>
      <text x="156" y="33.5" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="700" fill="white" textAnchor="middle">↑ Top margin</text>
    </g>
    <text x="16" y="16" fontFamily="DM Sans,sans-serif" fontSize="9" fontWeight="700" fill="#3D5C58" letterSpacing="0.5">MARGIN BY CLIENT</text>
  </svg>
);

const FeatCaptureAnim = () => (
  <svg viewBox="0 0 280 160" width="100%" height="130" xmlns="http://www.w3.org/2000/svg" style={{ display: "block" }}>
    <defs>
      <style>{`
        @keyframes fa2-arc  { 0%,5%{stroke-dashoffset:100} 70%,100%{stroke-dashoffset:0} }
        @keyframes fa2-minH { 0%{transform:rotate(0deg)} 100%{transform:rotate(360deg)} }
        @keyframes fa2-hrH  { 0%{transform:rotate(0deg)} 100%{transform:rotate(30deg)} }
        @keyframes fa2-bl1  { 0%,10%{opacity:0;width:0} 30%,100%{opacity:1;width:52px} }
        @keyframes fa2-bl2  { 0%,30%{opacity:0;width:0} 50%,100%{opacity:1;width:38px} }
        @keyframes fa2-bl3  { 0%,50%{opacity:0;width:0} 70%,100%{opacity:1;width:64px} }
        @keyframes fa2-bl4  { 0%,65%{opacity:0;width:0} 85%,100%{opacity:1;width:28px} }
        @keyframes fa2-pct  { 0%,5%{opacity:0} 80%,100%{opacity:1} }
        .fa2-arc{animation:fa2-arc 5s ease-in-out infinite;stroke-dasharray:100}
        .fa2-min{animation:fa2-minH 5s linear infinite;transform-origin:90px 75px}
        .fa2-hr {animation:fa2-hrH  5s linear infinite;transform-origin:90px 75px}
        .fa2-bl1{animation:fa2-bl1 5s ease infinite}
        .fa2-bl2{animation:fa2-bl2 5s ease infinite}
        .fa2-bl3{animation:fa2-bl3 5s ease infinite}
        .fa2-bl4{animation:fa2-bl4 5s ease infinite}
        .fa2-pct{animation:fa2-pct 5s ease infinite}
      `}</style>
    </defs>
    <circle cx="90" cy="75" r="50" fill="#F0FAF8" stroke="#DDE9E8" strokeWidth="1.5"/>
    <circle cx="90" cy="75" r="42" fill="none" stroke="#E8F7F4" strokeWidth="0.5"/>
    <circle className="fa2-arc" cx="90" cy="75" r="42" fill="none" stroke="#2B9D90" strokeWidth="3" strokeLinecap="round" transform="rotate(-90 90 75)" opacity="0.7"/>
    <line x1="90" y1="28"  x2="90" y2="34"  stroke="#B8DDD9" strokeWidth="1.5" strokeLinecap="round"/>
    <line x1="90" y1="116" x2="90" y2="122" stroke="#B8DDD9" strokeWidth="1.5" strokeLinecap="round"/>
    <line x1="43" y1="75"  x2="49" y2="75"  stroke="#B8DDD9" strokeWidth="1.5" strokeLinecap="round"/>
    <line x1="131" y1="75" x2="137" y2="75" stroke="#B8DDD9" strokeWidth="1.5" strokeLinecap="round"/>
    <line className="fa2-hr"  x1="90" y1="75" x2="90" y2="52" stroke="#0D1F1E" strokeWidth="2.5" strokeLinecap="round"/>
    <line className="fa2-min" x1="90" y1="75" x2="90" y2="40" stroke="#2B9D90" strokeWidth="2"   strokeLinecap="round"/>
    <circle cx="90" cy="75" r="3.5" fill="#2B9D90"/>
    <text x="158" y="24" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="700" fill="#7A9E9A" letterSpacing="0.5">TODAY'S CAPTURES</text>
    <text x="158" y="44" fontFamily="DM Sans,sans-serif" fontSize="7.5" fill="#7A9E9A">9:00</text>
    <rect className="fa2-bl1" x="180" y="35" height="12" rx="4" fill="#2B9D90" width="52"/>
    <text x="158" y="62" fontFamily="DM Sans,sans-serif" fontSize="7.5" fill="#7A9E9A">10:30</text>
    <rect className="fa2-bl2" x="180" y="53" height="12" rx="4" fill="#34B5A7" opacity="0.8" width="38"/>
    <text x="158" y="80" fontFamily="DM Sans,sans-serif" fontSize="7.5" fill="#7A9E9A">11:45</text>
    <rect className="fa2-bl3" x="180" y="71" height="12" rx="4" fill="#2B9D90" opacity="0.9" width="64"/>
    <text x="158" y="98" fontFamily="DM Sans,sans-serif" fontSize="7.5" fill="#7A9E9A">2:15</text>
    <rect className="fa2-bl4" x="180" y="89" height="12" rx="4" fill="#34B5A7" opacity="0.7" width="28"/>
    <g className="fa2-pct">
      <rect x="158" y="112" width="100" height="22" rx="11" fill="#2B9D90"/>
      <text x="208" y="126.5" fontFamily="DM Sans,sans-serif" fontSize="9" fontWeight="700" fill="white" textAnchor="middle">~98% captured</text>
    </g>
  </svg>
);

const FeatApprovalAnim = () => (
  <svg viewBox="0 0 280 160" width="100%" height="130" xmlns="http://www.w3.org/2000/svg" style={{ display: "block" }}>
    <defs>
      <style>{`
        @keyframes fa3-move {
          0%,10%  {transform:translateX(0);opacity:1}
          35%,45% {transform:translateX(76px);opacity:1}
          55%,65% {transform:translateX(152px);opacity:1}
          80%     {transform:translateX(152px);opacity:0}
          81%,100%{transform:translateX(0);opacity:0}
        }
        @keyframes fa3-check {0%,60%{opacity:0;transform:scale(0)} 75%,100%{opacity:1;transform:scale(1)}}
        @keyframes fa3-card2 {
          0%,25%  {transform:translateX(0);opacity:0.4}
          50%,60% {transform:translateX(76px);opacity:1}
          85%     {transform:translateX(76px);opacity:0.4}
          100%    {transform:translateX(0);opacity:0.4}
        }
        .fa3-card {animation:fa3-move 5s ease-in-out infinite}
        .fa3-card2{animation:fa3-card2 5s ease-in-out infinite 0.5s}
        .fa3-check{animation:fa3-check 5s ease infinite;transform-box:fill-box;transform-origin:center}
      `}</style>
    </defs>
    <rect x="16"  y="16" width="68" height="18" rx="9" fill="#F0FAF8" stroke="#DDE9E8" strokeWidth="1"/>
    <rect x="92"  y="16" width="68" height="18" rx="9" fill="#FEF9EC" stroke="#FDE68A" strokeWidth="1"/>
    <rect x="168" y="16" width="68" height="18" rx="9" fill="#ECFDF5" stroke="#A7F3D0" strokeWidth="1"/>
    <text x="50"  y="28.5" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="700" fill="#7A9E9A" textAnchor="middle">Submit</text>
    <text x="126" y="28.5" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="700" fill="#D97706" textAnchor="middle">Review</text>
    <text x="202" y="28.5" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="700" fill="#059669" textAnchor="middle">Approved ✓</text>
    <rect x="16"  y="38" width="68" height="110" rx="8" fill="#F8FAF9" stroke="#DDE9E8" strokeWidth="0.8"/>
    <rect x="92"  y="38" width="68" height="110" rx="8" fill="#FFFBF0" stroke="#FDE68A" strokeWidth="0.8"/>
    <rect x="168" y="38" width="68" height="110" rx="8" fill="#F0FDF8" stroke="#A7F3D0" strokeWidth="0.8"/>
    <g className="fa3-card">
      <rect x="22" y="46" width="56" height="38" rx="6" fill="white" stroke="#B8DDD9" strokeWidth="1.2"/>
      <rect x="27" y="52" width="8" height="8" rx="2" fill="#2B9D90"/>
      <rect x="39" y="53" width="30" height="5" rx="2.5" fill="#CCEEE8"/>
      <rect x="27" y="64" width="46" height="4" rx="2" fill="#E8F7F4"/>
      <rect x="27" y="72" width="36" height="4" rx="2" fill="#F0FAF8"/>
    </g>
    <g className="fa3-card2">
      <rect x="22" y="90" width="56" height="38" rx="6" fill="white" stroke="#DDE9E8" strokeWidth="1"/>
      <rect x="27" y="96" width="8" height="8" rx="2" fill="#34B5A7" opacity="0.6"/>
      <rect x="39" y="97" width="28" height="5" rx="2.5" fill="#E8F7F4"/>
      <rect x="27" y="108" width="44" height="4" rx="2" fill="#F0FAF8"/>
      <rect x="27" y="116" width="32" height="4" rx="2" fill="#F0FAF8"/>
    </g>
    <g className="fa3-check">
      <circle cx="202" cy="75" r="16" fill="#ECFDF5" stroke="#A7F3D0" strokeWidth="1.5"/>
      <path d="M194 75 L200 81 L210 67" stroke="#059669" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
    </g>
    <rect x="22" y="134" width="56" height="10" rx="4" fill="#F0FAF8" stroke="#DDE9E8" strokeWidth="0.8"/>
    <rect x="27" y="137" width="40" height="4" rx="2" fill="#E8F7F4"/>
  </svg>
);

const FeatSyncAnim = () => (
  <svg viewBox="0 0 280 160" width="100%" height="130" xmlns="http://www.w3.org/2000/svg" style={{ display: "block" }}>
    <defs>
      <style>{`
        @keyframes fa4-pulse {0%,100%{r:24;opacity:0.15} 50%{r:30;opacity:0.05}}
        @keyframes fa4-sync  {0%,40%{opacity:0} 55%,90%{opacity:1} 100%{opacity:0}}
        @keyframes fa4-spin  {0%{transform:rotate(0deg)} 100%{transform:rotate(360deg)}}
        .fa4-pulse{animation:fa4-pulse 2.5s ease-in-out infinite}
        .fa4-sync {animation:fa4-sync  3.6s ease infinite}
        .fa4-spin {animation:fa4-spin  4s linear infinite;transform-origin:140px 72px}
      `}</style>
    </defs>
    <circle className="fa4-pulse" cx="140" cy="72" r="24" fill="#2B9D90"/>
    <circle cx="140" cy="72" r="20" fill="#2B9D90" opacity="0.12" stroke="#2B9D90" strokeWidth="1"/>
    <circle cx="140" cy="72" r="16" fill="#2B9D90"/>
    <text x="140" y="68" fontFamily="DM Sans,sans-serif" fontSize="7" fontWeight="800" fill="white" textAnchor="middle">Time</text>
    <text x="140" y="78" fontFamily="DM Sans,sans-serif" fontSize="7" fontWeight="800" fill="white" textAnchor="middle">Tracker</text>
    <circle className="fa4-spin" cx="140" cy="72" r="38" fill="none" stroke="#2B9D90" strokeWidth="1" strokeDasharray="4 8" opacity="0.3"/>
    <rect x="30" y="48" width="48" height="48" rx="14" fill="#2CA01C"/>
    <text x="54" y="77" fontFamily="DM Sans,sans-serif" fontSize="16" fontWeight="900" fill="white" textAnchor="middle">QB</text>
    <rect x="202" y="48" width="48" height="48" rx="14" fill="#13B5EA"/>
    <text x="226" y="77" fontFamily="DM Sans,sans-serif" fontSize="13" fontWeight="900" fill="white" textAnchor="middle">Xero</text>
    <line x1="78" y1="72" x2="120" y2="72" stroke="#DDE9E8" strokeWidth="1.5" strokeDasharray="4 3"/>
    <line x1="160" y1="72" x2="202" y2="72" stroke="#DDE9E8" strokeWidth="1.5" strokeDasharray="4 3"/>
    <circle r="4" fill="#2B9D90">
      <animate attributeName="cx" values="82;136" dur="1.8s" repeatCount="indefinite" calcMode="spline" keySplines="0.4 0 0.6 1"/>
      <animate attributeName="opacity" values="1;0" dur="1.8s" repeatCount="indefinite"/>
      <animate attributeName="cy" values="68;68" dur="1.8s" repeatCount="indefinite"/>
    </circle>
    <circle r="4" fill="#34B5A7" opacity="0.8">
      <animate attributeName="cx" values="198;144" dur="1.8s" repeatCount="indefinite" begin="0.9s" calcMode="spline" keySplines="0.4 0 0.6 1"/>
      <animate attributeName="opacity" values="1;0" dur="1.8s" repeatCount="indefinite" begin="0.9s"/>
      <animate attributeName="cy" values="76;76" dur="1.8s" repeatCount="indefinite" begin="0.9s"/>
    </circle>
    <g className="fa4-sync">
      <rect x="92" y="126" width="96" height="18" rx="9" fill="#2B9D90"/>
      <text x="140" y="138.5" fontFamily="DM Sans,sans-serif" fontSize="9" fontWeight="700" fill="white" textAnchor="middle">Two-way sync ✓</text>
    </g>
    <text x="54"  y="108" fontFamily="DM Sans,sans-serif" fontSize="8" fill="#7A9E9A" textAnchor="middle">QuickBooks</text>
    <text x="226" y="108" fontFamily="DM Sans,sans-serif" fontSize="8" fill="#7A9E9A" textAnchor="middle">Xero</text>
  </svg>
);

const FeatIntelligenceAnim = () => (
  <svg viewBox="0 0 280 160" width="100%" height="130" xmlns="http://www.w3.org/2000/svg" style={{ display: "block" }}>
    <defs>
      <linearGradient id="fa5-grad" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stopColor="#2B9D90" stopOpacity="0.2"/>
        <stop offset="100%" stopColor="#2B9D90" stopOpacity="0"/>
      </linearGradient>
      <style>{`
        @keyframes fa5-line {0%,5%{stroke-dashoffset:300} 60%,100%{stroke-dashoffset:0}}
        @keyframes fa5-area {0%,5%{opacity:0} 60%,100%{opacity:1}}
        @keyframes fa5-dot  {0%,55%{opacity:0;r:0} 70%,100%{opacity:1;r:4}}
        @keyframes fa5-ins  {0%,65%{opacity:0;transform:translateY(8px)} 80%,100%{opacity:1;transform:translateY(0)}}
        .fa5-line{animation:fa5-line 5s ease-in-out infinite;stroke-dasharray:300}
        .fa5-area{animation:fa5-area 5s ease infinite}
        .fa5-dot {animation:fa5-dot  5s ease infinite}
        .fa5-ins {animation:fa5-ins  5s ease infinite}
      `}</style>
    </defs>
    <line x1="40" y1="120" x2="264" y2="120" stroke="#DDE9E8" strokeWidth="1"/>
    <line x1="40" y1="90"  x2="264" y2="90"  stroke="#DDE9E8" strokeWidth="0.5" strokeDasharray="3 3"/>
    <line x1="40" y1="60"  x2="264" y2="60"  stroke="#DDE9E8" strokeWidth="0.5" strokeDasharray="3 3"/>
    <line x1="40" y1="30"  x2="264" y2="30"  stroke="#DDE9E8" strokeWidth="0.5" strokeDasharray="3 3"/>
    <path className="fa5-area" d="M52,95 L88,82 L124,88 L160,68 L196,72 L232,50 L232,120 L52,120 Z" fill="url(#fa5-grad)"/>
    <path className="fa5-line" d="M52,95 L88,82 L124,88 L160,68 L196,72 L232,50" fill="none" stroke="#2B9D90" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
    <circle className="fa5-dot" cx="52"  cy="95" r="4" fill="white" stroke="#2B9D90" strokeWidth="2"/>
    <circle className="fa5-dot" cx="88"  cy="82" r="4" fill="white" stroke="#2B9D90" strokeWidth="2"/>
    <circle className="fa5-dot" cx="124" cy="88" r="4" fill="white" stroke="#2B9D90" strokeWidth="2"/>
    <circle className="fa5-dot" cx="160" cy="68" r="4" fill="white" stroke="#2B9D90" strokeWidth="2"/>
    <circle className="fa5-dot" cx="196" cy="72" r="4" fill="white" stroke="#2B9D90" strokeWidth="2"/>
    <circle className="fa5-dot" cx="232" cy="50" r="5" fill="#2B9D90"/>
    <text x="52"  y="132" fontFamily="DM Sans,sans-serif" fontSize="7.5" fill="#7A9E9A" textAnchor="middle">W1</text>
    <text x="88"  y="132" fontFamily="DM Sans,sans-serif" fontSize="7.5" fill="#7A9E9A" textAnchor="middle">W2</text>
    <text x="124" y="132" fontFamily="DM Sans,sans-serif" fontSize="7.5" fill="#7A9E9A" textAnchor="middle">W3</text>
    <text x="160" y="132" fontFamily="DM Sans,sans-serif" fontSize="7.5" fill="#7A9E9A" textAnchor="middle">W4</text>
    <text x="196" y="132" fontFamily="DM Sans,sans-serif" fontSize="7.5" fill="#7A9E9A" textAnchor="middle">W5</text>
    <text x="232" y="132" fontFamily="DM Sans,sans-serif" fontSize="7.5" fill="#2B9D90" fontWeight="700" textAnchor="middle">W6</text>
    <g className="fa5-ins">
      <rect x="182" y="28" width="86" height="18" rx="9" fill="#0D1F1E"/>
      <text x="225" y="39.5" fontFamily="DM Sans,sans-serif" fontSize="8" fontWeight="700" fill="#2B9D90" textAnchor="middle">↑ 18% utilization</text>
    </g>
    <text x="16" y="16" fontFamily="DM Sans,sans-serif" fontSize="9" fontWeight="700" fill="#3D5C58" letterSpacing="0.5">BILLABLE UTILIZATION</text>
  </svg>
);

const FeatAgentsAnim = () => (
  <svg viewBox="0 0 280 160" width="100%" height="130" xmlns="http://www.w3.org/2000/svg" style={{ display: "block" }}>
    <defs>
      <style>{`
        @keyframes fa6-pulse {0%,100%{opacity:1;r:3.5} 50%{opacity:0.3;r:2.5}}
        @keyframes fa6-bar  {0%,10%{height:0;y:108} 40%,100%{height:24;y:84}}
        @keyframes fa6-bar2 {0%,20%{height:0;y:108} 50%,100%{height:36;y:72}}
        @keyframes fa6-bar3 {0%,30%{height:0;y:108} 60%,100%{height:18;y:90}}
        @keyframes fa6-beam {0%,100%{opacity:0} 40%,60%{opacity:1}}
        @keyframes fa6-lbl  {0%,50%{opacity:0} 70%,100%{opacity:1}}
        .fa6-dot {animation:fa6-pulse 2s ease-in-out infinite}
        .fa6-dot2{animation:fa6-pulse 2s ease-in-out infinite 0.4s}
        .fa6-b1  {animation:fa6-bar  3.5s cubic-bezier(.4,0,.2,1) infinite}
        .fa6-b2  {animation:fa6-bar2 3.5s cubic-bezier(.4,0,.2,1) infinite}
        .fa6-b3  {animation:fa6-bar3 3.5s cubic-bezier(.4,0,.2,1) infinite}
        .fa6-beam{animation:fa6-beam 3.5s ease infinite}
        .fa6-lbl {animation:fa6-lbl  3.5s ease infinite}
      `}</style>
    </defs>
    {/* Mac */}
    <rect x="12" y="18" width="118" height="76" rx="8" fill="#0D1F1E"/>
    <rect x="18" y="24" width="106" height="64" rx="5" fill="#0C2B29"/>
    <rect x="18" y="24" width="106" height="14" rx="5" fill="#0D1F1E"/>
    <rect x="18" y="30" width="106" height="8" fill="#0D1F1E"/>
    <circle cx="27" cy="31" r="3" fill="#ff5f57" opacity="0.8"/>
    <circle cx="36" cy="31" r="3" fill="#febc2e" opacity="0.8"/>
    <circle cx="45" cy="31" r="3" fill="#28c840" opacity="0.8"/>
    <text x="24" y="52" fontFamily="DM Sans,sans-serif" fontSize="6.5" fill="rgba(255,255,255,0.4)" letterSpacing="0.5">AGENT ACTIVE</text>
    <rect className="fa6-b1" x="28" y="84" width="14" height="24" rx="3" fill="#2B9D90"/>
    <rect className="fa6-b2" x="48" y="72" width="14" height="36" rx="3" fill="#34B5A7" opacity="0.8"/>
    <rect className="fa6-b3" x="68" y="90" width="14" height="18" rx="3" fill="#2B9D90" opacity="0.6"/>
    <circle className="fa6-dot" cx="108" cy="31" r="3.5" fill="#2B9D90"/>
    <rect x="60" y="94" width="22" height="8" rx="2" fill="#1a2f2e"/>
    <rect x="52" y="100" width="38" height="4" rx="2" fill="#162828"/>
    <text x="71" y="115" fontFamily="DM Sans,sans-serif" fontSize="9" fontWeight="700" fill="#3D5C58" textAnchor="middle">macOS</text>
    {/* Connection beam */}
    <g className="fa6-beam">
      <line x1="132" y1="56" x2="148" y2="56" stroke="#2B9D90" strokeWidth="1.5" strokeDasharray="3 2"/>
      <circle cx="140" cy="56" r="3" fill="#2B9D90" opacity="0.6"/>
    </g>
    {/* Windows */}
    <rect x="150" y="18" width="118" height="76" rx="8" fill="#0D2640"/>
    <rect x="156" y="24" width="106" height="64" rx="5" fill="#0A1E35"/>
    <rect x="156" y="24" width="106" height="14" rx="5" fill="#0D2640"/>
    <rect x="156" y="30" width="106" height="8" fill="#0D2640"/>
    <rect x="244" y="28" width="7" height="2" rx="1" fill="rgba(255,255,255,0.3)"/>
    <rect x="244" y="33" width="5" height="2" rx="1" fill="rgba(255,255,255,0.3)"/>
    <text x="162" y="52" fontFamily="DM Sans,sans-serif" fontSize="6.5" fill="rgba(255,255,255,0.4)" letterSpacing="0.5">AGENT ACTIVE</text>
    <rect className="fa6-b2" x="164" y="72" width="14" height="36" rx="3" fill="#2B9D90" opacity="0.9"/>
    <rect className="fa6-b1" x="184" y="84" width="14" height="24" rx="3" fill="#34B5A7" opacity="0.7"/>
    <rect className="fa6-b3" x="204" y="90" width="14" height="18" rx="3" fill="#2B9D90" opacity="0.5"/>
    <circle className="fa6-dot2" cx="254" cy="31" r="3.5" fill="#2B9D90"/>
    <rect x="198" y="94" width="22" height="8" rx="2" fill="#0a1e35"/>
    <rect x="190" y="100" width="38" height="4" rx="2" fill="#081828"/>
    <text x="209" y="115" fontFamily="DM Sans,sans-serif" fontSize="9" fontWeight="700" fill="#3D5C58" textAnchor="middle">Windows</text>
    {/* Unified badge */}
    <g className="fa6-lbl">
      <rect x="68" y="128" width="144" height="20" rx="10" fill="#2B9D90"/>
      <circle cx="83" cy="138" r="3.5" fill="white" opacity="0.8"/>
      <circle cx="197" cy="138" r="3.5" fill="white" opacity="0.8"/>
      <text x="140" y="141.5" fontFamily="DM Sans,sans-serif" fontSize="8.5" fontWeight="700" fill="white" textAnchor="middle">One platform · Both devices</text>
    </g>
  </svg>
);

// ─── Updated FEATURES array ───────────────────────────────────────────────────
// Replace your existing FEATURES const with this one in Home.tsx

const FEATURES = [
  {
    anim: <FeatProfitabilityAnim />,
    icon: BarChart3,
    title: "Client profitability insights",
    desc: "See true margins by client, staff, and matter type — identify winners and leaks fast.",
  },
  {
    anim: <FeatCaptureAnim />,
    icon: Clock,
    title: "100% automatic capture",
    desc: "Every minute tracked and assigned. No reconstruction. No forgotten hours.",
  },
  {
    anim: <FeatApprovalAnim />,
    icon: Check,
    title: "Streamlined approval flow",
    desc: "Submit → review → approve → invoice. One unified billing workflow.",
  },
  {
    anim: <FeatSyncAnim />,
    icon: Zap,
    title: "Seamless QuickBooks & Xero sync",
    desc: "Two-way integration. No exports, no double entry, always aligned.",
  },
  {
    anim: <FeatIntelligenceAnim />,
    icon: FileText,
    title: "Weekly AI firm intelligence",
    desc: "Automated reports on billing efficiency, utilization, and performance trends.",
  },
  {
    anim: <FeatAgentsAnim />,
    icon: BarChart3,
    title: "Native Mac + Windows",
    desc: "Lightweight agents that run invisibly and never miss a second.",
  },
];

const HOW_IT_WORKS = [
  { anim: <StepOneAnim />,   step: "01", title: "Silent background tracking",          desc: "One-time install on Mac or Windows. Captures activity automatically — no timers, no manual logging." },
  { anim: <StepTwoAnim />,   step: "02", title: "AI maps time to clients instantly",    desc: "Real-time categorization using your firm's context — highly accurate with zero manual fixes needed." },
  { anim: <StepThreeAnim />, step: "03", title: "Approve → sync to QuickBooks / Xero", desc: "Review clean timesheets, approve in one click, push billable hours directly to your accounting system." },
];

const BRANDFETCH_CLIENT_ID =
  import.meta.env.VITE_BRANDFETCH_CLIENT_ID || "1idNI0a39p1CpjGIOku";

const INTEGRATIONS = [
  { name: "QuickBooks",      category: "Billing",       domain: "quickbooks.intuit.com", fallback: "QB" },
  { name: "Xero",            category: "Billing",       domain: "xero.com",               fallback: "X"  },
  { name: "Wolters Kluwer",  category: "Tax",           domain: "wolterskluwer.com",      fallback: "WK" },
  { name: "Thomson Reuters", category: "Tax",           domain: "thomsonreuters.com",     fallback: "TR" },
  { name: "Drake Software",  category: "Tax",           domain: "drakesoftware.com",      fallback: "DS" },
  { name: "Sage",            category: "Accounting",    domain: "sage.com",               fallback: "S"  },
  { name: "Karbon",          category: "Practice Mgmt", domain: "karbonhq.com",           fallback: "K"  },
  { name: "Canopy",          category: "Practice Mgmt", domain: "getcanopy.com",          fallback: "C"  },
];

const PRICING = [
  { name: "Professional", price: 29.99, desc: "Perfect for growing firms ready to eliminate manual time tracking.", features: ["Automatic capture","AI client mapping","QB & Xero sync","Approval workflow","Core reports"], highlighted: false },
  { name: "Executive",    price: 49.99, desc: "For leaders who want deep visibility into profitability and performance.", features: ["Everything in Professional","Profitability dashboard","AI firm insights","Utilization analytics","Priority support"], highlighted: true },
];

function IntegrationLogo({
  domain,
  name,
  fallback,
}: {
  domain: string;
  name: string;
  fallback: string;
}) {
  const src = `https://cdn.brandfetch.io/${domain}?c=${BRANDFETCH_CLIENT_ID}`;

  return (
    <div className="int-logo-wrap">
      <img
        className="int-logo"
        src={src}
        alt={name}
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={(e) => {
          e.currentTarget.style.display = "none";
          const fallbackEl = e.currentTarget.nextElementSibling as HTMLDivElement;
          if (fallbackEl) fallbackEl.style.display = "flex";
        }}
      />
      <div className="int-fallback" style={{ display: "none" }}>
        {fallback}
      </div>
    </div>
  );
}

export default function Home() {
  return (
    <div style={{ fontFamily:"'DM Sans', sans-serif", background:"#F4FAFA", color:"#0D1F1E", minHeight:"100vh" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600;9..40,700;9..40,800&display=swap');
        *,*::before,*::after{box-sizing:border-box;margin:0;padding:0} html{scroll-behavior:smooth}
        :root{--teal:#2B9D90;--teal-dark:#1F7269;--teal-mid:#34B5A7;--teal-light:#E6F5F4;--teal-border:#B8DDD9;--text:#0D1F1E;--text-2:#3D5C58;--text-3:#7A9E9A;--line:#DDE9E8;--bg:#F4FAFA;--white:#FFFFFF}
        a{text-decoration:none;color:inherit}
        .nav{position:fixed;top:0;left:0;right:0;z-index:100;height:60px;display:flex;align-items:center;border-bottom:1px solid var(--line);background:rgba(248,250,249,0.94);backdrop-filter:blur(12px)}
        .nav-inner{width:100%;max-width:1120px;margin:0 auto;padding:0 32px;display:flex;align-items:center;justify-content:space-between}
        .nav-logo{display:flex;align-items:center;gap:6px} .nav-logo img{width:42px;height:42px}
        .nav-logo-name{font-size:19px;font-weight:800;letter-spacing:-0.03em;color:#0D1F1A}
        .nav-logo-by{font-size:13px;font-weight:400;color:var(--text-3)}
        .nav-links{display:flex;gap:28px} .nav-links a{font-size:13.5px;font-weight:500;color:var(--text-2);transition:color 0.15s} .nav-links a:hover{color:var(--text)}
        .nav-right{display:flex;align-items:center;gap:18px}
        .nav-signin{font-size:13.5px;font-weight:500;color:var(--text-2);transition:color 0.15s} .nav-signin:hover{color:var(--text)}
        .btn-primary{display:inline-flex;align-items:center;gap:6px;padding:9px 20px;border-radius:999px;font-size:13.5px;font-weight:600;font-family:inherit;background:var(--teal);color:#fff;transition:background 0.15s,transform 0.1s;cursor:pointer;border:none} .btn-primary:hover{background:var(--teal-dark)} .btn-primary:active{transform:scale(0.98)}
        .hero-section{background:linear-gradient(160deg,#2B9D90 0%,#1F7269 55%,#174F4A 100%);padding:120px 32px 96px}
        .hero-inner{max-width:1200px;margin:0 auto;display:grid;grid-template-columns:1fr 1fr;gap:48px;align-items:start}
        .hero-eyebrow{display:inline-flex;align-items:center;gap:7px;font-size:10.5px;font-weight:700;letter-spacing:0.13em;text-transform:uppercase;color:rgba(255,255,255,0.45);margin-bottom:24px}
        .hero-dot{width:6px;height:6px;border-radius:50%;background:#4ADE80;flex-shrink:0}
        .hero-h1{font-size:clamp(36px,4.5vw,56px);font-weight:800;letter-spacing:-0.03em;line-height:1.05;color:#fff;margin-bottom:18px}
        .hero-h1 em{color:rgba(255,255,255,0.38);font-style:normal}
        .hero-sub{font-size:16px;color:rgba(255,255,255,0.55);line-height:1.7;margin-bottom:32px;font-weight:400}
        .hero-btns{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:52px}
        .btn-hero-primary{display:inline-flex;align-items:center;gap:8px;padding:13px 28px;border-radius:999px;font-size:15px;font-weight:600;font-family:inherit;background:#fff;color:var(--teal-dark);transition:opacity 0.15s,transform 0.1s;cursor:pointer;border:none} .btn-hero-primary:hover{opacity:0.92} .btn-hero-primary:active{transform:scale(0.98)}
        .btn-hero-ghost{display:inline-flex;align-items:center;gap:7px;padding:13px 24px;border-radius:999px;font-size:15px;font-weight:500;font-family:inherit;color:rgba(255,255,255,0.65);border:1px solid rgba(255,255,255,0.15);background:transparent;transition:color 0.15s,border-color 0.15s;cursor:pointer} .btn-hero-ghost:hover{color:rgba(255,255,255,0.9);border-color:rgba(255,255,255,0.3)}
        .hero-stats{display:grid;grid-template-columns:repeat(3,auto);border-top:1px solid rgba(255,255,255,0.1);padding-top:36px;width:fit-content;gap:0}
        .hero-stat{padding-right:40px} .hero-stat:not(:first-child){padding-left:40px;border-left:1px solid rgba(255,255,255,0.1)}
        .hero-stat-val{font-size:36px;font-weight:800;letter-spacing:-0.03em;color:#fff;line-height:1;margin-bottom:4px}
        .hero-stat-label{font-size:12px;color:rgba(255,255,255,0.38)}
        .hero-visual{display:flex;align-items:flex-start;justify-content:center;padding:0;margin-top:-12px}
        .hero-visual svg{width:100%;max-width:420px;filter:drop-shadow(0 24px 48px rgba(0,0,0,0.28))}
        .marquee-section{border-bottom:1px solid var(--line);padding:24px 0;overflow:hidden;position:relative;background:var(--white)}
        .marquee-eyebrow{text-align:center;font-size:10px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:var(--text-3);margin-bottom:18px}
        .mfade-l{position:absolute;left:0;top:0;bottom:0;width:72px;z-index:2;background:linear-gradient(to right,#fff,transparent);pointer-events:none}
        .mfade-r{position:absolute;right:0;top:0;bottom:0;width:72px;z-index:2;background:linear-gradient(to left,#fff,transparent);pointer-events:none}
        @keyframes marquee{from{transform:translateX(0)}to{transform:translateX(-50%)}}
        .marquee-track{display:flex;gap:10px;white-space:nowrap;animation:marquee 38s linear infinite}
        .int-chip{display:inline-flex;align-items:center;gap:10px;padding:9px 15px;border-radius:10px;border:1px solid var(--line);background:var(--bg);flex-shrink:0;transition:border-color 0.15s} .int-chip:hover{border-color:var(--teal-border)}
        .int-logo-wrap{
          width:32px;
          height:32px;
          border-radius:8px;
          display:flex;
          align-items:center;
          justify-content:center;
          flex-shrink:0;
          background:#fff;
          overflow:hidden;
          border:1px solid rgba(0,0,0,0.05);
        }

        .int-logo{
          width:22px;
          height:22px;
          object-fit:contain;
        }

        .int-fallback{
          width:100%;
          height:100%;
          border-radius:8px;
          display:flex;
          align-items:center;
          justify-content:center;
          background:var(--teal);
          color:#fff;
          font-size:11px;
          font-weight:800;
        }
        .int-name{font-size:12.5px;font-weight:600;color:var(--text);line-height:1.2} .int-cat{font-size:10.5px;color:var(--text-3)}
        .section{max-width:1120px;margin:0 auto;padding:88px 32px}
        .section-eyebrow{font-size:10.5px;font-weight:700;letter-spacing:0.13em;text-transform:uppercase;color:var(--teal-mid);margin-bottom:12px}
        .section-h2{font-size:clamp(28px,3.5vw,40px);font-weight:800;letter-spacing:-0.025em;line-height:1.1;color:var(--text);margin-bottom:40px}
        .section-sub{font-size:16px;color:var(--text-2);line-height:1.65;max-width:500px;margin-bottom:40px;margin-top:-24px}
        .hr{border:none;border-top:1px solid var(--line)}
        .steps{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
        @media(max-width:768px){.steps{grid-template-columns:1fr}}
        .step-card{background:var(--white);border:1px solid var(--line);border-radius:20px;padding:28px 28px 32px;transition:transform 0.2s,box-shadow 0.2s,border-color 0.2s;position:relative;overflow:hidden;display:flex;flex-direction:column;gap:0}
        .step-card::before{content:attr(data-step);position:absolute;top:-10px;right:20px;font-size:80px;font-weight:900;letter-spacing:-0.05em;color:var(--teal-light);line-height:1;pointer-events:none;user-select:none}
        .step-card:hover{transform:translateY(-3px);box-shadow:0 12px 32px rgba(43,157,144,0.12);border-color:var(--teal-border)}
        .step-num{font-size:10px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:var(--teal-mid);margin-bottom:16px}
        .step-anim{margin-bottom:20px;border-radius:12px;overflow:hidden;background:#F8FAF9;border:1px solid var(--line)}
        .step-card h3{font-size:16px;font-weight:800;letter-spacing:-0.02em;margin-bottom:8px;color:var(--text)}
        .step-card p{font-size:13.5px;color:var(--text-2);line-height:1.7}
        .feat-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
        @media(max-width:900px){.feat-grid{grid-template-columns:repeat(2,1fr)}}
        @media(max-width:560px){.feat-grid{grid-template-columns:1fr}}
        .feat-card{background:var(--white);border:1px solid var(--line);border-radius:20px;padding:32px 28px;transition:transform 0.2s,box-shadow 0.2s,border-color 0.2s;display:flex;flex-direction:column;gap:0}
        .feat-card:hover{transform:translateY(-3px);box-shadow:0 12px 32px rgba(43,157,144,0.12);border-color:var(--teal-border)}
        .feat-anim{margin-bottom:20px;border-radius:12px;overflow:hidden;background:#F8FAF9;border:1px solid var(--line)}
        .feat-card h3{font-size:14.5px;font-weight:800;letter-spacing:-0.015em;margin-bottom:8px;color:var(--text)}
        .feat-card p{font-size:13px;color:var(--text-2);line-height:1.65}
        .compare-grid{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--line);border-radius:14px;overflow:hidden}
        @media(max-width:640px){.compare-grid{grid-template-columns:1fr}}
        .compare-col{padding:40px 36px;background:var(--white)} .compare-col:first-child{border-right:1px solid var(--line);background:var(--bg)}
        .compare-label{font-size:10.5px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:24px}
        .compare-label.old{color:var(--text-3)} .compare-label.new{color:var(--teal-mid)}
        .compare-list{list-style:none;display:flex;flex-direction:column;gap:13px}
        .compare-item{display:flex;align-items:flex-start;gap:10px;font-size:13.5px;line-height:1.5}
        .compare-item.old{color:var(--text-3)} .compare-item.new{color:var(--text)}
        .ci-icon{width:17px;height:17px;border-radius:50%;flex-shrink:0;margin-top:1px;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700}
        .ci-icon.old{background:#EAEAEA;color:#AAAAAA} .ci-icon.new{background:var(--teal);color:#fff}
        .pricing-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;max-width:780px}
        @media(max-width:600px){.pricing-grid{grid-template-columns:1fr}}
        .plan{border:1px solid var(--line);border-radius:16px;padding:36px 32px;background:var(--white)} .plan.exec{background:var(--teal);border-color:var(--teal)}
        .plan-badge{display:inline-block;font-size:9.5px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;background:var(--teal-mid);color:#fff;padding:3px 9px;border-radius:20px;margin-bottom:18px}
        .plan-name{font-size:10.5px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:10px}
        .plan.exec .plan-name{color:rgba(255,255,255,0.4)} .plan:not(.exec) .plan-name{color:var(--text-3)}
        .plan-price{font-size:46px;font-weight:800;letter-spacing:-0.04em;line-height:1}
        .plan.exec .plan-price{color:#fff} .plan:not(.exec) .plan-price{color:var(--text)}
        .plan-per{font-size:13px;font-weight:400}
        .plan.exec .plan-per{color:rgba(255,255,255,0.35)} .plan:not(.exec) .plan-per{color:var(--text-3)}
        .plan-desc{font-size:13px;line-height:1.6;margin:14px 0 24px}
        .plan.exec .plan-desc{color:rgba(255,255,255,0.45)} .plan:not(.exec) .plan-desc{color:var(--text-2)}
        .plan-divider{border:none;border-top:1px solid;margin-bottom:20px}
        .plan.exec .plan-divider{border-color:rgba(255,255,255,0.1)} .plan:not(.exec) .plan-divider{border-color:var(--line)}
        .plan-feats{list-style:none;display:flex;flex-direction:column;gap:11px;margin-bottom:28px}
        .plan-feat{display:flex;align-items:center;gap:9px;font-size:13.5px}
        .plan.exec .plan-feat{color:rgba(255,255,255,0.7)} .plan:not(.exec) .plan-feat{color:var(--text-2)}
        .pf-check{width:15px;height:15px;flex-shrink:0}
        .plan.exec .pf-check{color:#4ADE80} .plan:not(.exec) .pf-check{color:var(--teal)}
        .plan-cta{display:block;width:100%;text-align:center;padding:12px;border-radius:999px;font-size:14px;font-weight:600;font-family:inherit;cursor:pointer;border:none;transition:opacity 0.15s,transform 0.1s} .plan-cta:active{transform:scale(0.98)}
        .plan.exec .plan-cta{background:var(--teal-mid);color:#fff} .plan.exec .plan-cta:hover{opacity:0.88}
        .plan:not(.exec) .plan-cta{background:var(--teal-light);color:var(--teal-dark)} .plan:not(.exec) .plan-cta:hover{opacity:0.8}
        .pricing-note{font-size:12.5px;color:var(--text-3);margin-top:16px}
        .cta-section{background:var(--teal);padding:80px 32px;text-align:center}
        .cta-inner{max-width:560px;margin:0 auto}
        .cta-section h2{font-size:clamp(26px,4vw,40px);font-weight:800;letter-spacing:-0.025em;color:#fff;margin-bottom:14px;line-height:1.1}
        .cta-section p{font-size:15px;color:rgba(255,255,255,0.5);line-height:1.65;margin-bottom:32px}
        .footer{border-top:1px solid var(--line);background:var(--bg)}
        .footer-inner{max-width:1120px;margin:0 auto;padding:32px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
        .footer-logo{display:flex;align-items:center;gap:8px} .footer-logo img{width:28px;height:28px;opacity:0.7}
        .footer-logo-name{font-size:14px;font-weight:800;letter-spacing:-0.02em;color:var(--text)}
        .footer-by{color:var(--text-3);font-weight:400;font-size:12px}
        .footer-links{display:flex;gap:20px} .footer-links a{font-size:12px;color:var(--text-3);transition:color 0.15s} .footer-links a:hover{color:var(--text)}
        .footer-copy{font-size:12px;color:var(--text-3)}
        @media(max-width:900px){.hero-inner{grid-template-columns:1fr}.hero-visual{width:100%}.nav-links{display:none}.hero-stats{grid-template-columns:1fr 1fr;gap:16px;width:100%;padding-top:28px}.hero-stat{padding-right:0}.hero-stat:not(:first-child){padding-left:0;border-left:none}.hero-stat-val{font-size:26px}}
        @media(max-width:480px){.hero-section{padding:100px 20px 64px}.section{padding:56px 20px}.nav-inner{padding:0 20px}.footer-inner{flex-direction:column;align-items:flex-start;gap:16px}.compare-col:first-child{border-right:none;border-bottom:1px solid var(--line)}}
      `}</style>

      <nav className="nav">
        <div className="nav-inner">
          <div className="nav-logo">
            <img src="/timetracker-icon.svg" alt="TimeTracker" />
            <div style={{display:"flex",alignItems:"baseline",gap:"6px"}}>
              <span className="nav-logo-name">TimeTracker</span>
              <span className="nav-logo-by">by MavOps</span>
            </div>
          </div>
          <div className="nav-links">
            {NAV_LINKS.map(({label,href})=>(<a key={label} href={href}>{label}</a>))}
          </div>
          <div className="nav-right">
            <Link to="/login" className="nav-signin">Sign in</Link>
            <a href="/request-access" className="btn-primary">Request Access <ChevronRight size={14}/></a>
          </div>
        </div>
      </nav>

      <section className="hero-section">
        <div className="hero-inner">
          <div>
            <div className="hero-eyebrow"><span className="hero-dot"/>Purpose-built for CPA firms</div>
            <h1 className="hero-h1">Recover hours.<br/>Reveal profit.<br/><em>Run smarter.</em></h1>
            <p className="hero-sub">TimeTracker is an AI-powered time intelligence platform that eliminates manual timesheets, captures every billable minute, and gives firm leaders the margin data to grow with confidence.</p>
            <div className="hero-btns">
              <a href="/request-access" className="btn-hero-primary">Get Started <ArrowRight size={16}/></a>
              <a href="#how-it-works" className="btn-hero-ghost">Learn How It Works</a>
            </div>
            <div className="hero-stats">
              {[{val:"2+ hrs",label:"Extra billable time / staff / day"},{val:"~98%",label:"Billable capture rate"},{val:"1-click",label:"Sync to QB & Xero"}].map(({val,label},i)=>(
                <div key={i} className="hero-stat"><div className="hero-stat-val">{val}</div><div className="hero-stat-label">{label}</div></div>
              ))}
            </div>
          </div>
          <div className="hero-visual" dangerouslySetInnerHTML={{__html:HERO_SVG}}/>
        </div>
      </section>

      <div className="marquee-section">
        <p className="marquee-eyebrow">Integrates with tools you already trust</p>
        <div style={{position:"relative"}}>
          <div className="mfade-l"/><div className="mfade-r"/>
            <div className="marquee-track">
              {[...INTEGRATIONS, ...INTEGRATIONS].map((int, i) => (
                <div key={`${int.name}-${i}`} className="int-chip">
                  <IntegrationLogo
                    domain={int.domain}
                    name={int.name}
                    fallback={int.fallback}
                  />
                <div><div className="int-name">{int.name}</div><div className="int-cat">{int.category}</div></div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <section id="how-it-works" className="section" style={{background:"#F8FAF9"}}>
        <p className="section-eyebrow">How It Works</p>
        <h2 className="section-h2">Effortless accuracy from day one</h2>
        <p className="section-sub">No setup hassle. No daily input. Just reliable billable time.</p>
        <div className="steps">
          {HOW_IT_WORKS.map(({anim,step,title,desc},i)=>(
            <div key={i} className="step-card" data-step={step}>
              <div className="step-num">Step {step}</div>
              <div className="step-anim">{anim}</div>
              <h3>{title}</h3><p>{desc}</p>
            </div>
          ))}
        </div>
      </section>
      <hr className="hr"/>

      <section id="features" className="section" style={{background:"#F8FAF9"}}>
        <p className="section-eyebrow">Features</p>
        <h2 className="section-h2">Everything a CPA firm needs</h2>
        <div className="feat-grid">
          {FEATURES.map(({anim,title,desc},i)=>(
            <div key={i} className="feat-card">
              <div className="feat-anim">{anim}</div>
              <h3>{title}</h3><p>{desc}</p>
            </div>
          ))}
        </div>
      </section>
      <hr className="hr"/>

      <section className="section" style={{background:"#F8FAF9"}}>
        <p className="section-eyebrow">The Difference</p>
        <h2 className="section-h2">Before vs. after TimeTracker</h2>
        <div className="compare-grid">
          <div className="compare-col">
            <p className="compare-label old">The old way</p>
            <ul className="compare-list">
              {["Manual time entry at end of day","Forgotten hours, guessed durations","Misattributed client work","Hours of monthly cleanup"].map((t,i)=>(
                <li key={i} className="compare-item old"><span className="ci-icon old">✕</span>{t}</li>
              ))}
            </ul>
          </div>
          <div className="compare-col">
            <p className="compare-label new">With TimeTracker</p>
            <ul className="compare-list">
              {["Automatic, real-time capture","100% of billable minutes recorded","AI maps every activity to the right client","One-click approval and sync"].map((t,i)=>(
                <li key={i} className="compare-item new"><span className="ci-icon new"><Check size={9}/></span>{t}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>
      <hr className="hr"/>

      <section id="pricing" className="section" style={{background:"#F8FAF9"}}>
        <p className="section-eyebrow">Pricing</p>
        <h2 className="section-h2">Simple per-seat pricing</h2>
        <div className="pricing-grid">
          {PRICING.map(({name,price,desc,features,highlighted})=>(
            <div key={name} className={`plan${highlighted?" exec":""}`}>
              {highlighted&&<span className="plan-badge">Most Popular</span>}
              <div className="plan-name">{name}</div>
              <div className="plan-price">${price}<span className="plan-per"> /seat/mo</span></div>
              <p className="plan-desc">{desc}</p>
              <hr className="plan-divider"/>
              <ul className="plan-feats">{features.map((f,fi)=>(<li key={fi} className="plan-feat"><Check className="pf-check" size={15}/>{f}</li>))}</ul>
              <a href="/request-access" className="plan-cta">Get Started</a>
            </div>
          ))}
        </div>
        <p className="pricing-note">No contracts. No setup fees. Cancel anytime.</p>
      </section>

      <section className="cta-section">
        <div className="cta-inner">
          <h2>Start capturing every billable minute</h2>
          <p>Join CPA firms that have eliminated manual timesheets and unlocked clearer profitability with TimeTracker.</p>
          <a href="/request-access" className="btn-hero-primary">Request Access <ArrowRight size={16}/></a>
        </div>
      </section>

      <footer className="footer">
        <div className="footer-inner">
          <div className="footer-logo">
            <img src="/timetracker-icon.svg" alt=""/>
            <span className="footer-logo-name">TimeTracker</span>
            <span className="footer-by">by MavOps AI</span>
          </div>
          <div className="footer-links">
            <a href="/privacy">Privacy</a><a href="/terms">Terms</a><a href="mailto:info@mavops.ai">Contact</a>
          </div>
          <p className="footer-copy">© 2025 MavOps AI</p>
        </div>
      </footer>
    </div>
  );
}