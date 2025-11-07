# throttles.py
from rest_framework.throttling import (
    ScopedRateThrottle,
    UserRateThrottle,
    AnonRateThrottle,
)

class AgentIngestThrottle(ScopedRateThrottle):
    scope = "agent_ingest"

class UIReadThrottle(ScopedRateThrottle):
    scope = "ui_read"

class UIWriteThrottle(ScopedRateThrottle):
    scope = "ui_write"

class AIGenerateThrottle(ScopedRateThrottle):
    scope = "ai_generate"

class PublicHelloThrottle(ScopedRateThrottle):
    scope = "public_hello"

class PairIssueRate(UserRateThrottle):
    rate = "10/hour"

class PairClaimRate(AnonRateThrottle):
    rate = "60/hour"