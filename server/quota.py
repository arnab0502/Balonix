"""Daily request budget guard for API-Football's 100/day free tier.

Spending is split into ring-fenced buckets (core / live / detail) so a long
afternoon of live polling can never consume the allowance that standings and
fixtures depend on. State persists to disk, so restarting the server does not
reset the counter and let us blow through the real upstream limit.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .config import CACHE_DIR, settings

_STATE = CACHE_DIR / "quota.json"


class QuotaExceeded(RuntimeError):
    def __init__(self, bucket: str):
        super().__init__(f"daily {bucket} request budget exhausted")
        self.bucket = bucket


class Quota:
    def __init__(self) -> None:
        self.day = date.today().isoformat()
        self.spent: dict[str, int] = {"core": 0, "live": 0, "detail": 0, "other": 0}
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        try:
            raw = json.loads(Path(_STATE).read_text())
        except (OSError, ValueError):
            return
        if raw.get("day") == self.day:
            self.spent.update(raw.get("spent", {}))

    def _save(self) -> None:
        try:
            _STATE.write_text(json.dumps({"day": self.day, "spent": self.spent}))
        except OSError:
            pass

    def _rollover(self) -> None:
        today = date.today().isoformat()
        if today != self.day:
            self.day = today
            self.spent = {"core": 0, "live": 0, "detail": 0, "other": 0}
            self._save()

    # -- accounting --------------------------------------------------------
    @property
    def total_spent(self) -> int:
        self._rollover()
        return sum(self.spent.values())

    @property
    def remaining(self) -> int:
        return max(0, settings.daily_budget - settings.budget_reserve - self.total_spent)

    def remaining_in(self, bucket: str) -> int:
        self._rollover()
        return max(0, settings.budget_for(bucket) - self.spent.get(bucket, 0))

    def can_spend(self, bucket: str, n: int = 1) -> bool:
        self._rollover()
        return self.remaining_in(bucket) >= n and self.remaining >= n

    def spend(self, bucket: str, n: int = 1) -> None:
        self._rollover()
        if not self.can_spend(bucket, n):
            raise QuotaExceeded(bucket)
        self.spent[bucket] = self.spent.get(bucket, 0) + n
        self._save()

    def refund(self, bucket: str, n: int = 1) -> None:
        """Give budget back when a call never reached the upstream data.

        A 429 rejection costs us nothing on the daily allowance, so charging
        for it would silently shrink the day's real capacity.
        """
        self._rollover()
        self.spent[bucket] = max(0, self.spent.get(bucket, 0) - n)
        self._save()

    def suggested_poll_seconds(self) -> int:
        """Widen the live poll interval as the live bucket drains.

        With the default 55-call live bucket this keeps roughly a full evening
        of football covered instead of burning out inside the first hour.
        """
        left = self.remaining_in("live")
        if left <= 0:
            return 0  # stop polling; UI switches to cached/simulated
        if left > 40:
            return settings.live_poll_seconds
        if left > 20:
            return max(settings.live_poll_seconds, 240)
        if left > 8:
            return max(settings.live_poll_seconds, 420)
        return 900

    def snapshot(self) -> dict:
        self._rollover()
        return {
            "day": self.day,
            "plan_limit": settings.daily_budget,
            "reserve": settings.budget_reserve,
            "spent": dict(self.spent),
            "total_spent": self.total_spent,
            "remaining": self.remaining,
            "buckets": {
                b: {"limit": settings.budget_for(b),
                    "spent": self.spent.get(b, 0),
                    "remaining": self.remaining_in(b)}
                for b in ("core", "live", "detail")
            },
            "poll_seconds": self.suggested_poll_seconds(),
        }


quota = Quota()
