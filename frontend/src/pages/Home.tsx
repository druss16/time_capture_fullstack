// Home.tsx — TimeTracker marketing landing page
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
    title: "Runs silently in the background",
    desc: "Install once on Mac or Windows. TimeTracker monitors activity automatically — no timers to start, no entries to make.",
  },
  {
    icon: Clock,
    step: "02",
    title: "AI maps every minute to a client",
    desc: "Our AI engine categorizes work by client in real time, using your firm's context to get it right without any manual correction.",
  },
  {
    icon: FileText,
    step: "03",
    title: "Approve and sync to QuickBooks",
    desc: "Review AI-generated timesheets, approve with one click, and push billable time directly to QuickBooks or Xero.",
  },
];

const FEATURES = [
  {
    icon: BarChart3,
    title: "Client profitability dashboard",
    desc: "See exactly which clients make you money — and which ones don't. Margin data by client, by staff, by matter type.",
  },
  {
    icon: Clock,
    title: "Automatic time capture",
    desc: "Every minute of work is captured and categorized. No more end-of-day reconstruction. No more guessing.",
  },
  {
    icon: Check,
    title: "Approval workflow",
    desc: "Staff submit. Managers approve. Invoices generate. The entire billing workflow in one place.",
  },
  {
    icon: Zap,
    title: "QuickBooks & Xero sync",
    desc: "Two-way sync keeps your billing data in perfect alignment. No duplicate entry, no manual exports.",
  },
  {
    icon: FileText,
    title: "AI firm analysis",
    desc: "Weekly insights on firm performance, billing efficiency, and staffing utilization — delivered automatically.",
  },
  {
    icon: BarChart3,
    title: "Works everywhere",
    desc: "Native Mac and Windows agents. Runs silently, stays out of the way, and never misses a minute.",
  },
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
    price: "$29.99",
    desc: "For growing CPA firms ready to automate time tracking.",
    features: [
      "Automatic time capture",
      "AI client categorization",
      "QuickBooks & Xero sync",
      "Approval workflow",
      "Basic reporting",
    ],
    highlighted: false,
  },
  {
    name: "Executive",
    price: "$49.99",
    desc: "For firm leaders who need deep intelligence on their business.",
    features: [
      "Everything in Professional",
      "Client profitability dashboard",
      "AI firm analysis & insights",
      "Staff utilization reporting",
      "Priority support",
    ],
    highlighted: true,
  },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-background text-foreground">

      {/* ── Nav ── */}
      <nav className="fixed top-0 left-0 right-0 z-50 border-b border-border/40 bg-background/90 backdrop-blur-md">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-1">
            <img src="/timetracker-icon.svg" alt="TimeTracker" className="w-8 h-8" />
            <span className="text-[15px] font-bold tracking-tight">TimeTracker</span>
            <span className="text-[11px] text-muted-foreground hidden sm:block">by MavOps</span>
          </div>
          <div className="hidden md:flex items-center gap-8">
            {NAV_LINKS.map(({ label, href }) => (
              <a key={label} href={href} className="text-sm text-muted-foreground hover:text-foreground transition-colors font-medium">
                {label}
              </a>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <Link to="/login" className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors hidden sm:block">
              Sign in
            </Link>
            <a
              href="mailto:info@mavops.ai?subject=TimeTracker%20Access%20Request"
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary/90 transition-all"
            >
              Request Access <ChevronRight className="w-3.5 h-3.5" />
            </a>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section
        className="relative pt-36 pb-28 overflow-hidden"
        style={{ background: "linear-gradient(160deg, #0d9e91 0%, #0a7c70 50%, #074f47 100%)" }}
      >
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute -top-20 right-0 w-[700px] h-[700px] rounded-full bg-white/[0.03] blur-3xl" />
          <div className="absolute bottom-0 -left-20 w-[500px] h-[500px] rounded-full bg-black/[0.06] blur-3xl" />
        </div>

        <div className="relative z-10 max-w-6xl mx-auto px-6">
          <div className="max-w-3xl">
            <div className="flex items-center gap-2 mb-7">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-300 animate-pulse" />
              <span className="text-[11px] font-bold tracking-[0.18em] uppercase text-white/50">
                Built exclusively for CPA firms
              </span>
            </div>

            <h1 className="text-[4.5rem] font-black text-white leading-[1.0] tracking-tight mb-6">
              More revenue.<br />
              <span className="text-white/70">Less admin.</span><br />
              <span className="text-white/45">Smarter decisions.</span>
            </h1>

            <p className="text-[17px] text-white/60 leading-relaxed max-w-lg mb-10">
              TimeTracker is an AI-powered time intelligence platform that eliminates manual timesheets,
              captures every billable minute, and gives firm leaders the margin data to grow with confidence.
            </p>

            <div className="flex flex-wrap items-center gap-4">
              <a
                href="mailto:info@mavops.ai?subject=TimeTracker%20Access%20Request"
                className="flex items-center gap-2 px-7 py-4 rounded-xl bg-white text-primary font-bold text-[15px] hover:bg-white/95 transition-all shadow-lg shadow-black/10"
              >
                Request Access <ArrowRight className="w-4 h-4" />
              </a>
              <a
                href="#how-it-works"
                className="flex items-center gap-2 px-7 py-4 rounded-xl border border-white/20 text-white/80 font-semibold text-[15px] hover:bg-white/10 hover:text-white transition-all"
              >
                See how it works
              </a>
            </div>
          </div>

          {/* Stats */}
          <div className="flex flex-wrap gap-12 mt-20 pt-12 border-t border-white/15">
            {[
              { value: "2+ hrs", label: "Billable time recovered per staff, per day" },
              { value: "~98%", label: "Billable time captured vs ~75% without TimeTracker" },
              { value: "1-click", label: "Invoice sync to QuickBooks & Xero" },
            ].map(({ value, label }, i) => (
              <div key={i} className="space-y-1">
                <p className="text-[2.2rem] font-black text-white leading-none">{value}</p>
                <p className="text-[12px] text-white/40 max-w-[160px] leading-snug">{label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Integrations carousel ── */}
      <section className="py-14 border-b border-border/50 bg-muted/20 overflow-hidden">
        <div className="max-w-6xl mx-auto px-6 mb-8">
          <p className="text-[11px] font-bold tracking-[0.18em] uppercase text-muted-foreground/60 text-center">
            Works with the tools your firm already uses
          </p>
        </div>
        <div className="relative">
          {/* Fade edges */}
          <div className="absolute left-0 top-0 bottom-0 w-24 bg-gradient-to-r from-background/80 to-transparent z-10 pointer-events-none" />
          <div className="absolute right-0 top-0 bottom-0 w-24 bg-gradient-to-l from-background/80 to-transparent z-10 pointer-events-none" />
          {/* Scrolling track */}
          <div
            className="flex gap-3"
            style={{
              animation: "marquee 28s linear infinite",
              width: "max-content",
            }}
          >
            {[...INTEGRATIONS, ...INTEGRATIONS].map(({ name, abbr, color, bg, category }, i) => (
              <div
                key={`${name}-${i}`}
                className="flex items-center gap-3 px-5 py-3.5 rounded-xl bg-background border border-border/60 shrink-0"
              >
                <div
                  className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0 text-[12px] font-black"
                  style={{ backgroundColor: bg, color }}
                >
                  {abbr}
                </div>
                <div>
                  <p className="text-[14px] font-semibold text-foreground leading-none">{name}</p>
                  <p className="text-[11px] text-muted-foreground mt-0.5">{category}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
        <p className="text-center text-[12px] text-muted-foreground/40 mt-6">
          + works alongside any browser-based or desktop accounting software
        </p>
        <style>{`
          @keyframes marquee {
            from { transform: translateX(0); }
            to { transform: translateX(-50%); }
          }
        `}</style>
      </section>

      {/* ── How It Works ── */}
      <section id="how-it-works" className="py-24 bg-background">
        <div className="max-w-6xl mx-auto px-6">
          <div className="mb-16">
            <p className="text-[11px] font-bold tracking-[0.18em] uppercase text-primary mb-3">How it works</p>
            <h2 className="text-[2.4rem] font-black text-foreground tracking-tight leading-tight">
              Zero setup. Zero manual entry.<br />
              <span className="text-muted-foreground font-semibold">Just accurate billable time.</span>
            </h2>
          </div>

          <div className="grid md:grid-cols-3 gap-10">
            {HOW_IT_WORKS.map(({ icon: Icon, step, title, desc }, i) => (
              <div key={i} className="space-y-4">
                <div className="flex items-center gap-3">
                  <div className="w-11 h-11 rounded-xl bg-primary/10 border border-primary/15 flex items-center justify-center">
                    <Icon className="w-5 h-5 text-primary" />
                  </div>
                  <span className="text-[11px] font-black text-muted-foreground/30 tracking-widest">{step}</span>
                </div>
                <h3 className="text-[17px] font-bold text-foreground leading-tight">{title}</h3>
                <p className="text-[14px] text-muted-foreground leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Before / After ── */}
      <section className="py-24 bg-muted/25 border-y border-border/40">
        <div className="max-w-6xl mx-auto px-6">
          <div className="grid md:grid-cols-2 gap-16 items-center">
            <div className="space-y-5">
              <p className="text-[11px] font-bold tracking-[0.18em] uppercase text-primary">The problem</p>
              <h2 className="text-[2.2rem] font-black text-foreground tracking-tight leading-tight">
                The average CPA firm bills for less than 80% of the hours they actually work.
              </h2>
              <p className="text-[15px] text-muted-foreground leading-relaxed">
                The rest disappears into bad tracking, end-of-day guesswork, and manual corrections
                that eat up another hour of unbillable admin time — every single day.
              </p>
              <p className="text-[15px] text-muted-foreground leading-relaxed">
                At a 10-person firm, that's{" "}
                <span className="font-bold text-foreground">over $750,000 in lost revenue annually.</span>
              </p>
            </div>

            <div className="bg-background rounded-2xl p-8 border border-border/50 space-y-6">
              <p className="text-[11px] font-bold tracking-[0.15em] uppercase text-muted-foreground">Billable time captured</p>
              <div className="space-y-5">
                <div className="space-y-2">
                  <div className="flex justify-between items-baseline">
                    <span className="text-[13px] text-muted-foreground font-medium">Without TimeTracker</span>
                    <span className="text-[17px] text-muted-foreground font-black">~75%</span>
                  </div>
                  <div className="h-3.5 rounded-full bg-muted overflow-hidden">
                    <div className="w-[75%] h-full rounded-full bg-muted-foreground/25" />
                  </div>
                </div>
                <div className="space-y-2">
                  <div className="flex justify-between items-baseline">
                    <span className="text-[15px] text-foreground font-bold">With TimeTracker</span>
                    <span className="text-[24px] text-primary font-black leading-none">~98%</span>
                  </div>
                  <div className="h-3.5 rounded-full bg-muted overflow-hidden">
                    <div className="w-[98%] h-full rounded-full bg-primary" />
                  </div>
                </div>
              </div>
              <p className="text-[13px] text-muted-foreground/60 italic">
                That gap is real revenue walking out the door — every day.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Features ── */}
      <section id="features" className="py-24 bg-background">
        <div className="max-w-6xl mx-auto px-6">
          <div className="mb-16">
            <p className="text-[11px] font-bold tracking-[0.18em] uppercase text-primary mb-3">Features</p>
            <h2 className="text-[2.4rem] font-black text-foreground tracking-tight leading-tight">
              Time capture is just the start.<br />
              <span className="text-muted-foreground font-semibold">The intelligence is where it gets powerful.</span>
            </h2>
          </div>

          <div className="grid md:grid-cols-3 gap-5">
            {FEATURES.map(({ icon: Icon, title, desc }, i) => (
              <div
                key={i}
                className="p-6 rounded-2xl border border-border/50 hover:border-primary/25 hover:bg-primary/[0.02] transition-all group cursor-default"
              >
                <div className="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center mb-4 group-hover:bg-primary/15 transition-colors">
                  <Icon className="w-4 h-4 text-primary" />
                </div>
                <h3 className="text-[15px] font-bold text-foreground mb-2">{title}</h3>
                <p className="text-[13px] text-muted-foreground leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Testimonial ── */}
      <section className="py-20 border-y border-border/40 bg-muted/20">
        <div className="max-w-2xl mx-auto px-6 text-center space-y-5">
          <div className="flex justify-center gap-1.5">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="w-3.5 h-3.5 rounded-sm bg-primary/70" />
            ))}
          </div>
          <blockquote className="text-[1.3rem] font-semibold text-foreground leading-relaxed">
            "We were leaving hours of billable time on the table every week and didn't even know it.
            TimeTracker fixed that in the first month."
          </blockquote>
          <p className="text-[12px] text-muted-foreground font-bold tracking-widest uppercase">
            — Partner, Meridian CPA Group
          </p>
        </div>
      </section>

      {/* ── Pricing ── */}
      <section id="pricing" className="py-24 bg-background">
        <div className="max-w-6xl mx-auto px-6">
          <div className="mb-14 text-center">
            <p className="text-[11px] font-bold tracking-[0.18em] uppercase text-primary mb-3">Pricing</p>
            <h2 className="text-[2.4rem] font-black text-foreground tracking-tight">Simple, per-seat pricing.</h2>
            <p className="text-muted-foreground mt-2 text-[15px]">No contracts. No setup fees. Cancel anytime.</p>
          </div>

          <div className="grid md:grid-cols-2 gap-5 max-w-3xl mx-auto">
            {PRICING.map(({ name, price, desc, features, highlighted }) => (
              <div
                key={name}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  borderRadius: "1rem",
                  padding: "2rem",
                  border: highlighted ? "2px solid #0d9e91" : "2px solid #e2e8f0",
                  background: highlighted ? "#0d9e91" : "#ffffff",
                  boxShadow: highlighted ? "0 20px 40px rgba(13,158,145,0.2)" : "none",
                }}
              >
                <div style={{ flex: 1 }}>
                  {highlighted ? (
                    <span style={{ display: "inline-block", padding: "4px 12px", borderRadius: "999px", background: "rgba(255,255,255,0.2)", color: "white", fontSize: "10px", fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "1rem" }}>
                      Most Popular
                    </span>
                  ) : (
                    <div style={{ height: "29px", marginBottom: "1rem" }} />
                  )}
                  <p style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: highlighted ? "rgba(255,255,255,0.5)" : "#94a3b8", marginBottom: "4px" }}>{name}</p>
                  <div style={{ display: "flex", alignItems: "baseline", gap: "4px", marginBottom: "8px" }}>
                    <span style={{ fontSize: "3rem", fontWeight: 900, lineHeight: 1, color: highlighted ? "white" : "#0f172a" }}>{price}</span>
                    <span style={{ fontSize: "13px", color: highlighted ? "rgba(255,255,255,0.5)" : "#94a3b8" }}>/seat/month</span>
                  </div>
                  <p style={{ fontSize: "13px", lineHeight: 1.6, color: highlighted ? "rgba(255,255,255,0.65)" : "#64748b", marginBottom: "1.75rem" }}>{desc}</p>
                  <div style={{ display: "flex", flexDirection: "column", gap: "12px", marginBottom: "2rem" }}>
                    {features.map((f, i) => (
                      <div key={i} style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                        <div style={{ width: "18px", height: "18px", borderRadius: "50%", background: highlighted ? "rgba(255,255,255,0.2)" : "rgba(13,158,145,0.1)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                          <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M2 5l2 2 4-4" stroke={highlighted ? "white" : "#0d9e91"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                        </div>
                        <span style={{ fontSize: "13px", color: highlighted ? "rgba(255,255,255,0.85)" : "#1e293b" }}>{f}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <a
                  href="mailto:info@mavops.ai?subject=TimeTracker%20Access%20Request"
                  style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "8px", padding: "14px", borderRadius: "12px", fontWeight: 600, fontSize: "14px", textDecoration: "none", background: highlighted ? "white" : "#0d9e91", color: highlighted ? "#0d9e91" : "white", transition: "opacity 0.15s" }}
                  onMouseOver={e => (e.currentTarget.style.opacity = "0.9")}
                  onMouseOut={e => (e.currentTarget.style.opacity = "1")}
                >
                  Request Access <ArrowRight size={16} />
                </a>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Final CTA ── */}
      <section
        className="py-24 relative overflow-hidden"
        style={{ background: "linear-gradient(145deg, #0d9e91 0%, #074f47 100%)" }}
      >
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-0 right-0 w-96 h-96 rounded-full bg-white/[0.04] blur-3xl" />
          <div className="absolute bottom-0 left-0 w-96 h-96 rounded-full bg-black/[0.06] blur-3xl" />
        </div>
        <div className="relative z-10 max-w-2xl mx-auto px-6 text-center space-y-7">
          <h2 className="text-[3rem] font-black text-white leading-tight tracking-tight">
            Ready to recover your lost revenue?
          </h2>
          <p className="text-[16px] text-white/60 leading-relaxed">
            TimeTracker is available by invitation to CPA firms. Reach out and we'll get you set up.
          </p>
          <a
            href="mailto:info@mavops.ai?subject=TimeTracker%20Access%20Request&body=Hi%2C%20I%27d%20like%20to%20learn%20more%20about%20TimeTracker%20for%20my%20CPA%20firm."
            className="inline-flex items-center gap-2 px-8 py-4 rounded-xl bg-white text-primary font-bold text-[15px] hover:bg-white/95 transition-all shadow-lg shadow-black/10"
          >
            Request Access <ArrowRight className="w-4 h-4" />
          </a>
          <p className="text-[12px] text-white/30">
            Questions?{" "}
            <a href="mailto:info@mavops.ai" className="text-white/50 hover:text-white/70 underline transition-colors">
              info@mavops.ai
            </a>
          </p>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="py-8 border-t border-border/50 bg-background">
        <div className="max-w-6xl mx-auto px-6 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <img src="/timetracker-icon.svg" alt="TimeTracker" className="w-7 h-7" />
            <span className="text-[13px] font-bold">TimeTracker</span>
            <span className="text-[11px] text-muted-foreground">by MavOps</span>
          </div>
          <p className="text-[12px] text-muted-foreground">© {new Date().getFullYear()} MavOps. All rights reserved.</p>
          <Link to="/login" className="text-[12px] text-muted-foreground hover:text-foreground transition-colors font-medium">
            Client Login →
          </Link>
        </div>
      </footer>

    </div>
  );
}