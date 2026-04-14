"""审计事件 Schema 定义"""

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import AuditAction, RiskLevel


class AuditEvent(BaseModel):
    """审计事件记录"""

    event_id: str
    action: AuditAction
    risk_level: RiskLevel
    timestamp: datetime = Field(default_factory=datetime.now)
    source: str = "hermes-yachiyo"
    detail: dict | None = None
