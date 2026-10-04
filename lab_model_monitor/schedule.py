"""Daily API diagnostics with independent settings."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any



WINDOWS_AI_REASONING_TASK_NAME = "LabModelMonitor-Daily"


@dataclass(frozen=True)
class AIReasoningSchedule:
    enabled: bool = False
    daily_time: str = "16:00"
    models: tuple[str, ...] = ("gpt-6-astra", "gpt-6.1-sol")
    attempts_per_model: int = 3
    reasoning_effort: str = "high"
    timeout_seconds: float = 300.0
    max_output_tokens: int = 32768

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("AI monitor enabled must be a boolean.")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", self.daily_time):
            raise ValueError("AI monitor time must use HH:MM format.")
        if (
            not self.models
            or len(self.models) > 10
            or any(
                not isinstance(model, str) or not model.strip() or len(model) > 200
                for model in self.models
            )
        ):
            raise ValueError("AI monitor requires 1 to 10 non-empty model names.")
        if len(set(self.models)) != len(self.models):
            raise ValueError("AI monitor model names must be unique.")
        if (
            isinstance(self.attempts_per_model, bool)
            or not isinstance(self.attempts_per_model, int)
            or not 1 <= self.attempts_per_model <= 5
        ):
            raise ValueError("AI monitor attempts must be an integer from 1 to 5.")
        if self.reasoning_effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("AI monitor reasoning effort is unsupported.")
        if not 1 <= self.timeout_seconds <= 600:
            raise ValueError("AI monitor timeout must be between 1 and 600 seconds.")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or not 25000 <= self.max_output_tokens <= 128000
        ):
            raise ValueError("AI monitor output budget must be 25000 to 128000 tokens.")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> AIReasoningSchedule:
        values = dict(payload or {})
        models = values.get("models", cls.models)
        if not isinstance(models, (list, tuple)):
            raise ValueError("AI monitor models must be a list.")
        return cls(
            enabled=values.get("enabled", False),
            daily_time=str(values.get("daily_time", "16:00")),
            models=tuple(models),
            attempts_per_model=values.get("attempts_per_model", 3),
            reasoning_effort=str(values.get("reasoning_effort", "high")),
            timeout_seconds=float(values.get("timeout_seconds", 300.0)),
            max_output_tokens=values.get("max_output_tokens", 32768),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["models"] = list(self.models)
        return result


