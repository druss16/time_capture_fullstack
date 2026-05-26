"""
Importing this package triggers @register_metric decorators on all metric
modules so the registry is populated. Always import via:

    from tracker.analytics_v2.metrics import all_metric_ids, get_metric

…not by importing individual metric modules directly.
"""
from .base import Metric, ThresholdRange, all_metric_ids, get_metric, register_metric  # noqa: F401

# Side-effect imports — register all concrete metrics
from . import realization  # noqa: F401
from . import utilization  # noqa: F401
from . import profitability  # noqa: F401
from . import wip  # noqa: F401
from . import compliance  # noqa: F401
