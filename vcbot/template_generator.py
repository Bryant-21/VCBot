import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


PLATFORM_DISPLAY = {
    "ALL": "All Platforms",
    "WINDOWS": "Windows",
    "XBOXONE": "Xbox One",
    "XBOXSERIESX": "Xbox Series X|S",
    "PLAYSTATION4": "PlayStation 4",
    "PLAYSTATION5": "PlayStation 5",
}


@dataclass(frozen=True)
class TemplateEntry:
    name: str
    path: Path
    is_dir: bool


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def resolve_templates_dir() -> Path:
    env_override = os.getenv("VCBOT_TEMPLATES_DIR")
    candidates = []
    if env_override:
        candidates.append(Path(env_override))
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / "templates")
    candidates.append(Path.cwd() / "templates")
    candidates.append(Path(__file__).resolve().parents[1] / "templates")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0] if candidates else Path.cwd() / "templates"


def list_template_entries(templates_dir: Path) -> List[TemplateEntry]:
    if not templates_dir.exists():
        return []
    entries: List[TemplateEntry] = []
    for child in sorted(templates_dir.iterdir(), key=lambda p: p.name.lower()):
        if child.is_dir():
            if any(p.is_file() for p in child.rglob("*")):
                entries.append(TemplateEntry(child.name, child, True))
        elif child.is_file():
            entries.append(TemplateEntry(child.name, child, False))
    return entries


def validate_date(value: str) -> Tuple[bool, str]:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False, "Use YYYY-MM-DD."
    return True, ""


def build_template_data(date_value: str, platform: str) -> Dict[str, str]:
    parsed = datetime.strptime(date_value, "%Y-%m-%d")
    platform = platform.upper()
    platform_display = PLATFORM_DISPLAY.get(platform, platform)
    return {
        "date": date_value,
        "date_compact": parsed.strftime("%Y%m%d"),
        "year": parsed.strftime("%Y"),
        "month": parsed.strftime("%m"),
        "day": parsed.strftime("%d"),
        "platform": platform,
        "platform_lower": platform.lower(),
        "platform_upper": platform.upper(),
        "platform_display": platform_display,
    }


def generate_from_template(
    entry: TemplateEntry,
    output_root: Path,
    data: Dict[str, str],
) -> Tuple[Path, List[Path]]:
    output_root.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_name(entry.name)
    output_dir = output_root / safe_name / f"{data['date']}_{data['platform']}"

    created: List[Path] = []
    for source in _iter_template_files(entry):
        relative = _relative_template_path(entry, source)
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)

        payload = source.read_bytes()
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            destination.write_bytes(payload)
        else:
            rendered = text.format_map(_SafeDict(data))
            destination.write_text(rendered, encoding="utf-8")
        created.append(destination)
    return output_dir, created


def _iter_template_files(entry: TemplateEntry) -> Iterable[Path]:
    if entry.is_dir:
        return [p for p in entry.path.rglob("*") if p.is_file()]
    return [entry.path]


def _relative_template_path(entry: TemplateEntry, source: Path) -> Path:
    if entry.is_dir:
        return source.relative_to(entry.path)
    return Path(source.name)


def _sanitize_name(value: str) -> str:
    return "".join(
        ch if ch.isalnum() or ch in ("-", "_", ".") else "_"
        for ch in value.strip()
    )
