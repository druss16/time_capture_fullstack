"""
TimeTracker Analytics v2 — query-driven dashboard backend.

Architecture overview (read /tracker/analytics_v2/README.md for the full story):

    Request → Scope + Lens + Time + Compare
    ↓
    Permission gate (role × scope)
    ↓
    Lens.assemble() → list of Sections (KPIRow / ChartCard / DataTable)
    ↓
    Each tile's Metric.compute(scope, time) → MetricValue
    ↓
    Response: typed primitives the frontend renders 1:1

Public entry point: /api/analytics/query/  (see views_analytics_v2.executive_query)
"""

VERSION = "2.0.0-alpha.1"
