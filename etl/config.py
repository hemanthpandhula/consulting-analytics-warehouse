"""Shared configuration. Every path is derived from one project root so tests can run in a temp folder."""
from dataclasses import dataclass
from pathlib import Path
import datetime as dt

SEED = 20261108
WINDOW_START = dt.date(2025, 1, 1)
AS_OF = dt.date(2026, 10, 31)          # reporting date for ageing, WIP and utilization
OPEN_END = dt.date(9999, 12, 31)       # valid_to of the current dimension version
HOURS_PER_DAY = 8
MAX_DAILY_HOURS = 16                   # data-quality threshold for a single timesheet line


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "data" / "raw"

    @property
    def out(self) -> Path:
        return self.root / "output"

    @property
    def marts(self) -> Path:
        return self.root / "output" / "marts"

    @property
    def db(self) -> Path:
        return self.root / "output" / "warehouse.db"

    @property
    def sql(self) -> Path:
        return Path(__file__).resolve().parent.parent / "sql"


def default_paths() -> Paths:
    return Paths(Path(__file__).resolve().parent.parent)
