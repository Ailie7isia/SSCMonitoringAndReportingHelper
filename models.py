from __future__ import annotations

from dataclasses import dataclass, field


# -----------------------------------------------------------------------------
# Data models used throughout the project.
#
# This file defines the objects used to store and organize application
# data, such as company information, portfolio changes, and operation
# results.
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# This object is used throughout the project when reading, processing, or 
# displaying portfolio data. Only the domain and company name are required

# slots=True is used to reduce memory usage and prevent accidental
# creation of new attributes.

@dataclass(slots=True)
class Company:
    domain: str         # Company's internet domain (used as the primary identifier).
    name: str           # Display name of the company.
    grade: str = ""     # SecurityScorecard letter grade (e.g. A, B, C).
    score: int | None = None    # Numeric SecurityScorecard score.


# -----------------------------------------------------------------------------
# This object determines:
# - which domains should be added
# - which domains should be removed

# It is passed into the portfolio update process before any API calls are made.

@dataclass(slots=True)
class PortfolioPlan:
    to_add: list[str]
    to_remove: list[str]

# -----------------------------------------------------------------------------
# This object stores the outcome after applying a PortfolioPlan.

@dataclass(slots=True)
class CycleApplyReport:
    # Domains successfully removed.
    removed_ok: list[str] = field(default_factory=list) 
    # Failed removals:
    removed_failed: list[tuple[str, str]] = field(default_factory=list)
    # Domains successfully added.
    added_ok: list[str] = field(default_factory=list)
    # Failed additions:
    added_failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return bool(self.removed_failed or self.added_failed)