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
    desc: "See exactly which clients make you money — and which ones don't. Margin data by client, by staff member, by matter type.",
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
    cta: "Request Access",
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
    cta: "Request Access",
    highlighted: true,
  },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-background text-foreground">

      {/* ── Nav ── */}
      <nav className="fixed top-0 left-0 right-0 z-50 border-b border-border/40 bg-background/80 backdrop-blur-md">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
              <Clock className="w-4 h-4 text-white" />
            </div>
            <span className="text-[15px] font-bold text-foreground tracking-tight">TimeTracker</span>
            <span className="text-[11px] text-muted-foreground">by MavOps</span>
          </div>
          <div className="hidden md:flex items-center gap-8">
            {NAV_LINKS.map(({ label, href }) => (
              <a key={label} href={href} className="text-sm text-muted-foreground hover:text-foreground transition-colors font-medium">
                {label}
              </a>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <Link to="/login" className="text-sm font-semibold text-muted-foreground hover:text-foreground transition-colors">
              Sign in
            </Link>
            <a
              href="mailto:info@mavops.ai?subject=TimeTracker%20Access%20Request"
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary/90 transition-all shadow-sm shadow-primary/20"
            >
              Request Access <ChevronRight className="w-3.5 h-3.5" />
            </a>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section
        className="relative pt-32 pb-24 overflow-hidden"
        style={{ background: "linear-gradient(160deg, #0d9e91 0%, #0a7c70 50%, #085f57 100%)" }}
      >
        {/* Background blobs */}
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-0 right-0 w-[600px] h-[600px] rounded-full bg-white/[0.04] blur-3xl" />
          <div className="absolute bottom-0 left-0 w-[500px] h-[500px] rounded-full bg-black/[0.06] blur-3xl" />
        </div>

        <div className="relative z-10 max-w-6xl mx-auto px-6">
          <div className="max-w-3xl">
            {/* Eyebrow */}
            <div className="flex items-center gap-2 mb-8">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-300 animate-pulse" />
              <span className="text-[11px] font-bold tracking-[0.18em] uppercase text-white/55">
                Built exclusively for CPA firms
              </span>
            </div>

            {/* Headline */}
            <h1 className="text-[4rem] md:text-[5rem] font-black text-white leading-[1.0] tracking-tight mb-6">
              More revenue.<br />
              <span className="text-white/75">Less admin.</span><br />
              <span className="text-white/50">Smarter decisions.</span>
            </h1>

            <p className="text-[18px] text-white/65 leading-relaxed max-w-xl mb-10">
              TimeTracker is an AI-powered time intelligence platform that eliminates manual timesheets,
              captures every billable minute, and gives firm leaders real margin data to grow with confidence.
            </p>

            {/* CTAs */}
            <div className="flex flex-wrap items-center gap-4">
              <a
                href="mailto:info@mavops.ai?subject=TimeTracker%20Access%20Request&body=Hi%2C%20I%27d%20like%20to%20learn%20more%20about%20TimeTracker%20for%20my%20CPA%20firm."
                className="flex items-center gap-2 px-7 py-4 rounded-xl bg-white text-primary font-bold text-[15px] hover:bg-white/95 transition-all shadow-lg shadow-black/10"
              >
                Request Access <ArrowRight className="w-4 h-4" />
              </a>
              <a href="#how-it-works" className="flex items-center gap-2 px-7 py-4 rounded-xl border border-white/25 text-white font-semibold text-[15px] hover:bg-white/10 transition-all">
                See how it works
              </a>
            </div>
          </div>

          {/* Stats row */}
          <div className="grid grid-cols-3 gap-4 mt-20 max-w-2xl">
            {[
              { value: "2+ hrs", label: "Billable time recovered per staff, per day" },
              { value: "~98%", label: "Billable time captured vs ~75% industry average" },
              { value: "1-click", label: "QuickBooks & Xero invoice sync" },
            ].map(({ value, label }, i) => (
              <div key={i} className="space-y-1">
                <p className="text-[2rem] font-black text-white leading-none">{value}</p>
                <p className="text-[12px] text-white/45 leading-snug">{label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── How It Works ── */}
      <section id="how-it-works" className="py-24 bg-background">
        <div className="max-w-6xl mx-auto px-6">
          <div className="mb-16">
            <p className="text-[11px] font-bold tracking-[0.18em] uppercase text-primary mb-3">How it works</p>
            <h2 className="text-[2.5rem] font-black text-foreground tracking-tight leading-tight">
              Zero setup. Zero manual entry.<br />
              <span className="text-muted-foreground">Just accurate billable time.</span>
            </h2>
          </div>

          <div className="grid md:grid-cols-3 gap-8">
            {HOW_IT_WORKS.map(({ icon: Icon, step, title, desc }, i) => (
              <div key={i} className="relative">
                {i < HOW_IT_WORKS.length - 1 && (
                  <div className="hidden md:block absolute top-6 left-full w-full h-px bg-border/50 -translate-x-4 z-0" />
                )}
                <div className="relative z-10 space-y-4">
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center">
                      <Icon className="w-5 h-5 text-primary" />
                    </div>
                    <span className="text-[11px] font-black text-muted-foreground/40 tracking-widest">{step}</span>
                  </div>
                  <h3 className="text-[18px] font-bold text-foreground leading-tight">{title}</h3>
                  <p className="text-[14px] text-muted-foreground leading-relaxed">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Before / After ── */}
      <section className="py-24 bg-muted/30 border-y border-border/50">
        <div className="max-w-6xl mx-auto px-6">
          <div className="grid md:grid-cols-2 gap-16 items-center">
            <div className="space-y-6">
              <p className="text-[11px] font-bold tracking-[0.18em] uppercase text-primary">The problem</p>
              <h2 className="text-[2.2rem] font-black text-foreground tracking-tight leading-tight">
                The average CPA firm bills for less than 80% of the hours they actually work.
              </h2>
              <p className="text-[15px] text-muted-foreground leading-relaxed">
                The rest disappears into bad tracking, end-of-day guesswork, and manual timesheet corrections
                that eat up another hour of unbillable admin time every single day.
              </p>
              <p className="text-[15px] text-muted-foreground leading-relaxed">
                At a 10-person firm, that's <span className="font-bold text-foreground">over $750,000 in lost revenue annually.</span>
              </p>
            </div>

            <div className="space-y-6 bg-background rounded-2xl p-8 border border-border/50">
              <p className="text-[11px] font-bold tracking-[0.15em] uppercase text-muted-foreground">Billable time captured</p>
              <div className="space-y-5">
                <div className="space-y-2">
                  <div className="flex justify-between">
                    <span className="text-[14px] text-muted-foreground font-medium">Without TimeTracker</span>
                    <span className="text-[16px] text-muted-foreground font-black">~75%</span>
                  </div>
                  <div className="h-4 rounded-full bg-muted overflow-hidden">
                    <div className="w-[75%] h-full rounded-full bg-muted-foreground/30" />
                  </div>
                </div>
                <div className="space-y-2">
                  <div className="flex justify-between">
                    <span className="text-[16px] text-foreground font-bold">With TimeTracker</span>
                    <span className="text-[22px] text-primary font-black leading-none">~98%</span>
                  </div>
                  <div className="h-4 rounded-full bg-muted overflow-hidden">
                    <div className="w-[98%] h-full rounded-full bg-primary" />
                  </div>
                </div>
              </div>
              <p className="text-[13px] text-muted-foreground italic">
                That gap is real revenue walking out the door — every single day.
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
            <h2 className="text-[2.5rem] font-black text-foreground tracking-tight leading-tight">
              Time capture is just the start.<br />
              <span className="text-muted-foreground">The intelligence is where it gets powerful.</span>
            </h2>
          </div>

          <div className="grid md:grid-cols-3 gap-6">
            {FEATURES.map(({ icon: Icon, title, desc }, i) => (
              <div key={i} className="p-6 rounded-2xl border border-border/50 bg-background hover:border-primary/30 hover:bg-primary/[0.02] transition-all group">
                <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center mb-4 group-hover:bg-primary/15 transition-colors">
                  <Icon className="w-5 h-5 text-primary" />
                </div>
                <h3 className="text-[16px] font-bold text-foreground mb-2">{title}</h3>
                <p className="text-[13px] text-muted-foreground leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Testimonial ── */}
      <section className="py-20 bg-muted/20 border-y border-border/50">
        <div className="max-w-3xl mx-auto px-6 text-center space-y-6">
          <div className="flex justify-center gap-1">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="w-4 h-4 rounded-sm bg-primary/80" />
            ))}
          </div>
          <blockquote className="text-[1.4rem] font-semibold text-foreground leading-relaxed">
            "We were leaving hours of billable time on the table every week and didn't even know it.
            TimeTracker fixed that in the first month."
          </blockquote>
          <p className="text-[13px] text-muted-foreground font-bold tracking-wide uppercase">
            — Partner, Meridian CPA Group
          </p>
        </div>
      </section>

      {/* ── Pricing ── */}
      <section id="pricing" className="py-24 bg-background">
        <div className="max-w-6xl mx-auto px-6">
          <div className="mb-16 text-center">
            <p className="text-[11px] font-bold tracking-[0.18em] uppercase text-primary mb-3">Pricing</p>
            <h2 className="text-[2.5rem] font-black text-foreground tracking-tight">
              Simple, per-seat pricing.
            </h2>
            <p className="text-muted-foreground mt-3 text-[15px]">No contracts. No setup fees. Cancel anytime.</p>
          </div>

          <div className="grid md:grid-cols-2 gap-6 max-w-3xl mx-auto">
            {PRICING.map(({ name, price, desc, features, cta, highlighted }) => (
              <div
                key={name}
                className={`rounded-2xl p-8 border ${highlighted
                  ? "border-primary bg-primary text-white shadow-xl shadow-primary/20"
                  : "border-border/50 bg-background"
                }`}
              >
                {highlighted && (
                  <span className="inline-block px-3 py-1 rounded-full bg-white/20 text-white text-[11px] font-bold tracking-wide uppercase mb-4">
                    Most Popular
                  </span>
                )}
                <p className={`text-[13px] font-bold tracking-wide uppercase mb-1 ${highlighted ? "text-white/60" : "text-muted-foreground"}`}>{name}</p>
                <div className="flex items-baseline gap-1 mb-2">
                  <span className={`text-[3rem] font-black leading-none ${highlighted ? "text-white" : "text-foreground"}`}>{price}</span>
                  <span className={`text-[14px] font-medium ${highlighted ? "text-white/60" : "text-muted-foreground"}`}>/seat/month</span>
                </div>
                <p className={`text-[14px] mb-8 leading-relaxed ${highlighted ? "text-white/70" : "text-muted-foreground"}`}>{desc}</p>
                <div className="space-y-3 mb-8">
                  {features.map((f, i) => (
                    <div key={i} className="flex items-center gap-3">
                      <div className={`w-4 h-4 rounded-full flex items-center justify-center shrink-0 ${highlighted ? "bg-white/20" : "bg-primary/10"}`}>
                        <Check className={`w-2.5 h-2.5 ${highlighted ? "text-white" : "text-primary"}`} strokeWidth={3} />
                      </div>
                      <span className={`text-[13px] font-medium ${highlighted ? "text-white/85" : "text-foreground"}`}>{f}</span>
                    </div>
                  ))}
                </div>
                <a
                  href="mailto:info@mavops.ai?subject=TimeTracker%20Access%20Request"
                  className={`w-full flex items-center justify-center gap-2 py-3.5 rounded-xl font-semibold text-[14px] transition-all ${highlighted
                    ? "bg-white text-primary hover:bg-white/95"
                    : "bg-primary text-white hover:bg-primary/90"
                  }`}
                >
                  {cta} <ArrowRight className="w-4 h-4" />
                </a>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Final CTA ── */}
      <section
        className="py-24 relative overflow-hidden"
        style={{ background: "linear-gradient(145deg, #0d9e91 0%, #085f57 100%)" }}
      >
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-0 right-0 w-96 h-96 rounded-full bg-white/[0.05] blur-3xl" />
          <div className="absolute bottom-0 left-0 w-96 h-96 rounded-full bg-black/[0.07] blur-3xl" />
        </div>
        <div className="relative z-10 max-w-3xl mx-auto px-6 text-center space-y-8">
          <h2 className="text-[3rem] font-black text-white leading-tight tracking-tight">
            Ready to recover your<br />lost revenue?
          </h2>
          <p className="text-[17px] text-white/65 leading-relaxed">
            TimeTracker is available by invitation to CPA firms. Reach out and we'll get you set up.
          </p>
          <a
            href="mailto:info@mavops.ai?subject=TimeTracker%20Access%20Request&body=Hi%2C%20I%27d%20like%20to%20learn%20more%20about%20TimeTracker%20for%20my%20CPA%20firm."
            className="inline-flex items-center gap-2 px-8 py-4 rounded-xl bg-white text-primary font-bold text-[16px] hover:bg-white/95 transition-all shadow-lg shadow-black/10"
          >
            Request Access <ArrowRight className="w-4 h-4" />
          </a>
          <p className="text-[12px] text-white/35">
            Questions? Email <a href="mailto:info@mavops.ai" className="text-white/60 hover:text-white/80 underline transition-colors">info@mavops.ai</a>
          </p>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="py-8 border-t border-border/50 bg-background">
        <div className="max-w-6xl mx-auto px-6 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-md bg-primary flex items-center justify-center">
              <Clock className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="text-[13px] font-bold text-foreground">TimeTracker</span>
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