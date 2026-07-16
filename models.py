from __future__ import annotations

from dataclasses import dataclass, field

@dataclass(slots=True)
class Company:
    domain: str
    name: str
    grade: str = ""
    score: int | None = None


@dataclass(slots=True)
class PortfolioPlan:
    to_add: list[str]
    to_remove: list[str]


@dataclass(slots=True)
class CycleApplyReport:
    removed_ok: list[str] = field(default_factory=list)
    removed_failed: list[tuple[str, str]] = field(default_factory=list)

    added_ok: list[str] = field(default_factory=list)
    added_failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return bool(self.removed_failed or self.added_failed)