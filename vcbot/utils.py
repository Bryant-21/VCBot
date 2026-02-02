from datetime import datetime, timezone
from typing import Optional
import base64
import json


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_from_epoch(value: Optional[int]) -> Optional[str]:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def bethesda_image_url(s3bucket: Optional[str], s3key: Optional[str]) -> Optional[str]:
    if not s3bucket or not s3key:
        return None
    payload = {
        "bucket": s3bucket,
        "key": s3key,
        "edits": {"resize": {}},
        "outputFormat": "webp",
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    token = base64.b64encode(raw).decode("ascii")
    return f"https://ugcmods.bethesda.net/image/{token}"
