from typing import Literal

from pydantic import BaseModel


class RootCause(BaseModel):
    component: str
    failure_mode: str


class ScenarioLabel(BaseModel):
    scenario_id: str
    category: Literal["infra", "network", "app", "compound"]
    manifests: list[str]
    root_cause: RootCause
    expected_severity: Literal["critical", "warning"]
    expected_alerts: list[str]
    red_herring_signals: list[str]
    valid_remediations: list[str]
    duration_seconds: int
    notes: str | None = None
