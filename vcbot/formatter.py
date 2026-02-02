from pathlib import Path
from typing import Any, Dict, List, Tuple

from .bethesda import Mod
from .utils import bethesda_image_url


PLATFORM_EMOJI = {
    "XBOXONE": ":xbox:",
    "XBOXSERIESX": ":xbox:",
    "PLAYSTATION4": ":playstation:",
    "PLAYSTATION5": ":playstation:",
    "WINDOWS": ":pc:",
    "ALL": ":globe_with_meridians:",
}
PLATFORM_FULL_NAME = {
    "XBOXONE": "Xbox One",
    "XBOXSERIESX": "Xbox Series X|S",
    "PLAYSTATION4": "PlayStation 4",
    "PLAYSTATION5": "PlayStation 5",
    "WINDOWS": "Windows",
    "ALL": "All Platforms",
}
MAX_TITLE_FLAIRS = 10
PRICE_EMOJI = ":credits:"


def _product_label(mod: Mod) -> str:
    return mod.product_title or mod.product or "MOD"


def _join_list(items: List[str]) -> str:
    return ", ".join(items) if items else "N/A"


def _summary_text(mod: Mod) -> str:
    if mod.overview:
        return mod.overview.strip()
    if mod.description:
        return mod.description.strip().splitlines()[0]
    return "No summary provided."


def _platform_emojis(platforms: List[str]) -> str:
    tokens = []
    for platform in platforms:
        emoji = PLATFORM_EMOJI.get(platform)
        if emoji and emoji not in tokens:
            tokens.append(emoji)
    return " ".join(tokens[:MAX_TITLE_FLAIRS]) if tokens else ""


def _platform_full_names(platforms: List[str]) -> str:
    if not platforms:
        return "N/A"
    return ", ".join(PLATFORM_FULL_NAME.get(p, p) for p in platforms)


def _format_value(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) if value else "N/A"
    if isinstance(value, dict):
        if not value:
            return "N/A"
        return ", ".join(f"{key}={value[key]}" for key in sorted(value))
    return str(value)


def _release_notes_text(mod: Mod) -> str:
    if not mod.release_notes:
        return "N/A"
    parts: List[str] = []
    for entry in mod.release_notes:
        platform = entry.get("hardware_platform") or "UNKNOWN"
        notes = entry.get("release_notes") or []
        if not notes:
            parts.append(f"- {platform}: N/A")
            continue
        for note in notes:
            version = note.get("version_name") or "Unknown version"
            text = note.get("note") or ""
            parts.append(f"- {platform} {version}: {text}".strip())
    return "\n".join(parts) if parts else "N/A"


def _totals(mod: Mod) -> Dict[str, Any]:
    totals = mod.stats.get("totals") if isinstance(mod.stats, dict) else None
    return totals if isinstance(totals, dict) else {}


def _price_text(mod: Mod) -> str:
    if not mod.prices:
        return "N/A"
    parts = []
    for price in mod.prices:
        amount = price.get("amount")
        if amount is None:
            continue
        parts.append(f"{PRICE_EMOJI} {amount}")
    if not parts:
        return "N/A"
    return parts[0]


def _image_urls(mod: Mod) -> str:
    urls: List[str] = []
    cover_url = _non_banner_cover_url(mod)
    for url in (cover_url, mod.preview_image_url):
        if url and url not in urls:
            urls.append(url)
    for image in mod.screenshot_images:
        if _is_banner_image(image):
            continue
        url = image.get("url") or image.get("uri") or image.get("path") or image.get("link")
        if not url:
            s3bucket = image.get("s3bucket")
            s3key = image.get("s3key")
            if s3bucket and s3key:
                url = bethesda_image_url(s3bucket, s3key)
        if url and url not in urls:
            urls.append(url)
    return "\n".join(f"- {url}" for url in urls) if urls else "N/A"


def _is_banner_image(image: Dict[str, Any]) -> bool:
    if not image:
        return False
    classification = str(image.get("classification") or "").lower()
    filename = str(image.get("filename") or "").lower()
    s3key = str(image.get("s3key") or "").lower()
    return "banner" in classification or "banner" in filename or "/banner" in s3key


def _banner_url(mod: Mod) -> str:
    if _is_banner_image(mod.cover_image):
        s3bucket = mod.cover_image.get("s3bucket")
        s3key = mod.cover_image.get("s3key")
        url = bethesda_image_url(s3bucket, s3key) if s3bucket and s3key else None
        return url or "N/A"
    return "N/A"


def _non_banner_cover_url(mod: Mod) -> str:
    if _is_banner_image(mod.cover_image):
        return None
    return mod.cover_image_url


def build_post_title(mod: Mod, post_type: str) -> str:
    if post_type == "update":
        date_hint = mod.updated_at[:10] if mod.updated_at else "Update"
        return f"[{_product_label(mod)}] Update: {mod.title} ({date_hint})"
    creator = mod.author_displayname or "Unknown Creator"
    emojis = _platform_emojis(mod.hardware_platforms)
    suffix = f" {emojis}" if emojis else ""
    return f"{creator} presents {mod.title}{suffix}"


def render_post_body(mod: Mod, post_type: str, template_path: Path) -> str:
    template = template_path.read_text(encoding="utf-8")
    author = mod.author_displayname or "Unknown"
    author_url = (
        f"https://creations.bethesda.net/en/{mod.product.lower()}/all"
        f"?author_displayname={author}"
        if mod.product and author != "Unknown"
        else "N/A"
    )
    data: Dict[str, Any] = {
        "post_type": post_type,
        "title": mod.title,
        "summary": _summary_text(mod),
        "author": author,
        "author_url": author_url,
        "product": mod.product_title or mod.product,
        "platforms": _join_list(mod.hardware_platforms),
        "platform_full_names": _platform_full_names(mod.hardware_platforms),
        "platform_emojis": _platform_emojis(mod.hardware_platforms),
        "categories": _join_list(mod.categories),
        "prices": _price_text(mod),
        "details_url": mod.details_url or "N/A",
        "preview_image_url": mod.preview_image_url or "N/A",
        "cover_image_url": _non_banner_cover_url(mod) or "N/A",
        "banner_image_url": _banner_url(mod),
        "image_urls": _image_urls(mod),
        "mod_id": mod.mod_id,
    }
    return template.format_map(_SafeDict(data))


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "N/A"
