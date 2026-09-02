from pydantic import BaseModel
from typing import List, Literal, Optional


class RootCause(BaseModel):
    component: str
    failure_mode: str


class ScenarioLabel(BaseModel):
    scenario_id: str
    category: Literal["infra", "network", "app", "compound"]
    manifests: List[str]
    root_cause: RootCause
    expected_severity: Literal["critical", "warning"]
    expected_alerts: List[str]
    red_herring_signals: List[str]
    valid_remediations: List[str]
    duration_seconds: int
    notes: Optional[str] = None
