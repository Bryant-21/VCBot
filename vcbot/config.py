import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import os
from typing import Optional

from dotenv import load_dotenv


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Product(str, Enum):
    FALLOUT4 = "FALLOUT4"
    SKYRIM = "SKYRIM"
    STARFIELD = "STARFIELD"


@dataclass(frozen=True)
class Config:
    product: str
    sort: str
    time_period: str
    size: int
    page: int
    counts_platform: str
    database_path: Path
    post_template_path: Path
    request_timeout_seconds: float
    bethesda_core_url: str
    bethesda_content_url: str
    bethesda_bnet_key: Optional[str]
    bethesda_bearer: Optional[str]
    mod_url_template: Optional[str]
    reddit_client_id: Optional[str]
    reddit_client_secret: Optional[str]
    reddit_username: Optional[str]
    reddit_password: Optional[str]
    reddit_user_agent: Optional[str]
    reddit_subreddit: Optional[str]
    reddit_redirect_uri: Optional[str]
    reddit_oauth_scope: Optional[str]
    reddit_session_cookies: Optional[str]
    reddit_csrf_token: Optional[str]
    reddit_fallout4_flair_id: Optional[str]
    reddit_skyrim_flair_id: Optional[str]
    reddit_starfield_flair_id: Optional[str]
    discord_webhook_url: Optional[str]
    discord_template_path: Path
    wiki_template_path: Path
    fallout4_hard_stop: str
    skyrim_hard_stop: str
    starfield_hard_stop: str
    bgs_ignore_before: str
    synthetic_last_seen_first_ptime: Optional[str]
    bethesda_origin: Optional[str]
    bethesda_referer: Optional[str]
    bethesda_user_agent: Optional[str]
    dry_run: bool


def _resolve_template_path(env_name: str, default_rel: str) -> Path:
    env_val = os.getenv(env_name)
    if env_val:
        return Path(env_val)
    
    # Try next to executable
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).parent / default_rel
        if exe_path.exists():
            return exe_path
            
    # Try relative to CWD
    cwd_path = Path.cwd() / default_rel
    if cwd_path.exists():
        return cwd_path
        
    # Fallback to relative to this file's parent (dev mode)
    return Path(__file__).resolve().parents[1] / default_rel


def load_config(env_path: Optional[Path] = None) -> Config:
    load_dotenv(env_path)

    database_path = Path(_env("DATABASE_PATH", "data/vcbot.db"))
    post_template_path = _resolve_template_path("POST_TEMPLATE_PATH", "templates/post.md")
    return Config(
        product=_env("BETHESDA_PRODUCT", Product.FALLOUT4.value),
        sort=_env("BETHESDA_SORT", "first_ptime"),
        time_period=_env("BETHESDA_TIME_PERIOD", "all_time"),
        size=_env_int("BETHESDA_SIZE", 20),
        page=_env_int("BETHESDA_PAGE", 1),
        counts_platform=_env("BETHESDA_COUNTS_PLATFORM", "ALL"),
        database_path=database_path,
        post_template_path=post_template_path,
        request_timeout_seconds=_env_float("REQUEST_TIMEOUT_SECONDS", 30.0),
        bethesda_core_url=_env("BETHESDA_CORE_URL", "https://cdn.bethesda.net/data/core"),
        bethesda_content_url=_env("BETHESDA_CONTENT_URL", "https://api.bethesda.net/ugcmods/v2/content"),
        bethesda_bnet_key=_env("BETHESDA_BNET_KEY"),
        bethesda_bearer=_env("BETHESDA_BEARER"),
        mod_url_template=_env("BETHESDA_MOD_URL_TEMPLATE"),
        reddit_client_id=_env("REDDIT_CLIENT_ID"),
        reddit_client_secret=_env("REDDIT_CLIENT_SECRET"),
        reddit_username=_env("REDDIT_USERNAME"),
        reddit_password=_env("REDDIT_PASSWORD"),
        reddit_user_agent=_env("REDDIT_USER_AGENT"),
        reddit_subreddit=_env("REDDIT_SUBREDDIT"),
        reddit_redirect_uri=_env("REDDIT_REDIRECT_URI", "http://localhost:8080/callback"),
        reddit_oauth_scope=_env("REDDIT_OAUTH_SCOPE", "identity submit"),
        reddit_session_cookies=_env("REDDIT_SESSION_COOKIES"),
        reddit_csrf_token=_env("REDDIT_CSRF_TOKEN"),
        reddit_fallout4_flair_id=_env("REDDIT_FALLOUT4_FLAIR_ID"),
        reddit_skyrim_flair_id=_env("REDDIT_SKYRIM_FLAIR_ID"),
        reddit_starfield_flair_id=_env("REDDIT_STARFIELD_FLAIR_ID"),
        discord_webhook_url=_env("DISCORD_WEBHOOK_URL"),
        discord_template_path=_resolve_template_path("DISCORD_TEMPLATE_PATH", "templates/discord_post.md"),
        wiki_template_path=_resolve_template_path("WIKI_TEMPLATE_PATH", "templates/wiki_post.txt"),
        fallout4_hard_stop=_env("FALLOUT4_HARD_STOP", "2025-11-01T00:00:00+00:00"),
        skyrim_hard_stop=_env("SKYRIM_HARD_STOP", "2023-12-01T00:00:00+00:00"),
        starfield_hard_stop=_env("STARFIELD_HARD_STOP", "2024-06-01T00:00:00+00:00"),
        bgs_ignore_before=_env("BGS_IGNORE_BEFORE", "2025-01-01T00:00:00+00:00"),
        synthetic_last_seen_first_ptime=_env("SYNTHETIC_LAST_SEEN_FIRST_PTIME"),
        bethesda_origin=_env("BETHESDA_ORIGIN"),
        bethesda_referer=_env("BETHESDA_REFERER"),
        bethesda_user_agent=_env("BETHESDA_USER_AGENT"),
        dry_run=_env_bool("DRY_RUN", False),
    )
