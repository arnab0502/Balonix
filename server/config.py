"""Runtime configuration, loaded from environment / .env."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
CACHE_DIR = ROOT / ".cache"


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split("#")[0].strip()
        os.environ.setdefault(key.strip(), value)


_load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


class Settings:
    provider: str = (os.environ.get("TF_PROVIDER") or "mock").lower()
    api_key: str = os.environ.get("TF_API_FOOTBALL_KEY", "").strip()
    api_host: str = os.environ.get("TF_API_FOOTBALL_HOST", "v3.football.api-sports.io").strip()

    # Ring-fenced daily request buckets. Live polling can never starve the
    # core data pulls, which is what makes the 100/day free tier usable.
    daily_budget: int = _int("TF_DAILY_BUDGET", 100)
    budget_core: int = _int("TF_BUDGET_CORE", 20)
    budget_live: int = _int("TF_BUDGET_LIVE", 55)
    budget_detail: int = _int("TF_BUDGET_DETAIL", 20)
    budget_reserve: int = _int("TF_BUDGET_RESERVE", 5)

    live_poll_seconds: int = _int("TF_LIVE_POLL_SECONDS", 180)
    # API-Football rejects bursts. Free tops out near 10/min, Pro near 450.
    rate_limit_per_min: int = _int("TF_RATE_LIMIT_PER_MIN", 9)

    @property
    def unrestricted(self) -> bool:
        """Paid plans have no season/date gate, so real data can back every view."""
        return self.daily_budget > 100

    # Podcast tab. Accepts "@handle", a UC... id, or a full channel URL.
    youtube_channel: str = os.environ.get("TF_YOUTUBE_CHANNEL", "").strip()
    youtube_api_key: str = os.environ.get("TF_YOUTUBE_API_KEY", "").strip()
    youtube_title: str = os.environ.get("TF_YOUTUBE_TITLE", "").strip()

    transfer_source: str = (os.environ.get("TF_TRANSFER_SOURCE") or "mock").lower()
    transfer_sweep_size: int = _int("TF_TRANSFER_SWEEP_SIZE", 12)
    # The raw feed reaches back to the 1920s; keep only what the UI can query.
    transfer_retention_days: int = _int("TF_TRANSFER_RETENTION_DAYS", 1095)

    # Optional HTTP basic auth. Set both to lock the app down before hosting it.
    auth_user: str = os.environ.get("TF_AUTH_USER", "").strip()
    auth_pass: str = os.environ.get("TF_AUTH_PASS", "").strip()

    @property
    def auth_enabled(self) -> bool:
        return bool(self.auth_user and self.auth_pass)

    ttl_live: int = _int("TF_TTL_LIVE", 170)
    ttl_fixtures: int = _int("TF_TTL_FIXTURES", 86400)
    ttl_standings: int = _int("TF_TTL_STANDINGS", 86400)
    ttl_transfers: int = _int("TF_TTL_TRANSFERS", 21600)
    ttl_squads: int = _int("TF_TTL_SQUADS", 604800)
    ttl_videos: int = _int("TF_TTL_VIDEOS", 1800)
    ttl_rumours: int = _int("TF_TTL_RUMOURS", 900)
    ttl_socials: int = _int("TF_TTL_SOCIALS", 900)

    # Nitter mirrors X timelines as RSS without a key. Instances come and go,
    # so this is a fallback list tried in order.
    nitter_hosts: str = os.environ.get(
        "TF_NITTER_HOSTS", "https://nitter.net,https://nitter.privacydev.net").strip()

    host: str = os.environ.get("TF_HOST", "127.0.0.1")
    port: int = _int("TF_PORT", 0) or _int("PORT", 8000)

    @property
    def effective_provider(self) -> str:
        if self.provider == "apifootball" and not self.api_key:
            return "mock"
        return self.provider

    @property
    def is_live(self) -> bool:
        return self.effective_provider != "mock"

    def budget_for(self, bucket: str) -> int:
        return {
            "core": self.budget_core,
            "live": self.budget_live,
            "detail": self.budget_detail,
        }.get(bucket, 0)


settings = Settings()
CACHE_DIR.mkdir(exist_ok=True)
