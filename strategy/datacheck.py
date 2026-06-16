"""Pure data-quality helpers (no LEAN, no network) so freshness/coverage can be
asserted in tests and wired into ingest/backtests. Encodes the data rule:
never trust stale data (the SPY-ended-2021 bug)."""
from __future__ import annotations

from datetime import date


def _to_date(yyyymmdd: str) -> date:
    s = str(yyyymmdd)
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


def is_stale(last_bar: str, required_end: str, max_gap_days: int = 10) -> bool:
    """True if a symbol's last bar is more than `max_gap_days` before the date we
    need data through. last_bar / required_end are 'YYYYMMDD' strings."""
    gap = (_to_date(required_end) - _to_date(last_bar)).days
    return gap > max_gap_days
