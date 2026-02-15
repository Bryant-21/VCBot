import logging
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
import threading
import concurrent.futures
import requests
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .bethesda import BethesdaClient, Mod, compute_mod_hash
from .config import Config
from .db import NullStore, SQLiteStore
from .formatter import _image_urls, build_post_title, render_post_body
from .reddit_client import RedditClient
from .discord_client import DiscordClient
from .utils import parse_iso, utc_now_iso, download_image

logger = logging.getLogger(__name__)


def _is_update_due(existing: dict, mod: Mod, mod_hash: str) -> bool:
    existing_hash = existing.get("last_known_hash")
    changed = not existing_hash or existing_hash != mod_hash

    updated_at = parse_iso(mod.published_at) or parse_iso(mod.updated_at)
    last_update_posted_at = parse_iso(
        existing.get("last_update_posted_at") or existing.get("last_posted_at")
    )

    if updated_at and last_update_posted_at:
        return updated_at > last_update_posted_at
    if updated_at and not last_update_posted_at:
        return True
    return changed


def _determine_action(
    existing: Optional[dict],
    mod: Mod,
    mod_hash: str,
    post_new: bool,
    post_updates: bool,
    config: Config,
) -> Optional[str]:
    if existing is None:
        return "new" if post_new and _is_new_creation(mod, config) else None

    if post_updates and _is_update_due(existing, mod, mod_hash):
        return "update"

    return None


def _is_new_creation(mod: Mod, config: Config) -> bool:
    author = mod.author_displayname or "Unknown"
    if not _passes_hard_stop(mod, config):
        logger.debug("Skip %s (%s): before hard stop", mod.mod_id, author)
        return False
    if not _passes_bgs_ignore(mod, config):
        logger.debug("Skip %s (%s): BGS ignore cutoff", mod.mod_id, author)
        return False
    if not mod.author_verified:
        logger.debug("Skip %s (%s): author not verified", mod.mod_id, author)
        return False
    if not mod.prices:
        if (mod.author_displayname or "").lower() != "bethesdagamestudios":
            logger.debug("Skip %s (%s): missing prices", mod.mod_id, author)
            return False
        logger.debug("Allow %s (%s): BGS zero price", mod.mod_id, author)
        return True
    if not _has_paid_price(mod.prices):
        if (mod.author_displayname or "").lower() != "bethesdagamestudios":
            logger.debug("Skip %s (%s): no paid price", mod.mod_id, author)
            return False
        logger.debug("Allow %s (%s): BGS zero price", mod.mod_id, author)
        return True
    return True


def _has_paid_price(prices: List[dict]) -> bool:
    for price in prices:
        amount = price.get("amount")
        try:
            if amount is not None and float(amount) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _passes_hard_stop(mod: Mod, config: Config) -> bool:
    if mod.product == "FALLOUT4":
        cutoff = parse_iso(config.fallout4_hard_stop)
    elif mod.product == "SKYRIM":
        cutoff = parse_iso(config.skyrim_hard_stop)
    elif mod.product == "STARFIELD":
        cutoff = parse_iso(config.starfield_hard_stop)
    else:
        return True
    mod_date = parse_iso(mod.first_published_at) or parse_iso(mod.published_at)
    if not cutoff or not mod_date:
        return True
    return mod_date >= cutoff


def _passes_bgs_ignore(mod: Mod, config: Config) -> bool:
    if (mod.author_displayname or "").lower() != "bethesdagamestudios":
        return True
    cutoff = parse_iso(config.bgs_ignore_before)
    mod_date = parse_iso(mod.first_published_at) or parse_iso(mod.published_at)
    if not cutoff or not mod_date:
        return True
    return mod_date >= cutoff


def _attempt_id() -> str:
    return uuid.uuid4().hex


def _safe_filename(value: str) -> str:
    cleaned = []
    for ch in value:
        if ch.isalnum() or ch in {"-", "_"}:
            cleaned.append(ch)
        else:
            cleaned.append("_")
    return "".join(cleaned).strip("_")


def _meta_key_first_ptime(product: str) -> str:
    return f"last_seen_first_ptime:{product}"


def _resolve_first_ptime_cutoff(
    config: Config, store: SQLiteStore, dry_run: bool
) -> Optional[str]:
    if config.synthetic_last_seen_first_ptime:
        return config.synthetic_last_seen_first_ptime
    if dry_run:
        return config.synthetic_last_seen_first_ptime
    return store.get_meta(_meta_key_first_ptime(config.product))


def _is_before_or_equal_first_ptime(mod: Mod, cutoff: str) -> bool:
    mod_time = parse_iso(mod.first_published_at) or parse_iso(mod.published_at)
    cutoff_time = parse_iso(cutoff)
    if not mod_time or not cutoff_time:
        return False
    return mod_time <= cutoff_time


def _hard_stop_for_product(config: Config) -> Optional[str]:
    if config.product == "FALLOUT4":
        return config.fallout4_hard_stop
    if config.product == "SKYRIM":
        return config.skyrim_hard_stop
    if config.product == "STARFIELD":
        return config.starfield_hard_stop
    return None


def _flair_id_for_product(mod: Mod, config: Config) -> Optional[str]:
    if mod.product == "FALLOUT4":
        return config.reddit_fallout4_flair_id
    elif mod.product == "SKYRIM":
        return config.reddit_skyrim_flair_id
    elif mod.product == "STARFIELD":
        return config.reddit_starfield_flair_id
    return None


def _max_iso(left: Optional[str], right: Optional[str]) -> Optional[str]:
    left_time = parse_iso(left) if left else None
    right_time = parse_iso(right) if right else None
    if left_time and right_time:
        return left if left_time >= right_time else right
    return left or right


def generate_sample_post(
    config: Config,
    output_path: str,
    discord_output_path: str,
    max_pages: int,
) -> None:
    client = BethesdaClient(
        core_url=config.bethesda_core_url,
        content_url=config.bethesda_content_url,
        bnet_key=config.bethesda_bnet_key,
        bearer=config.bethesda_bearer,
        timeout_seconds=config.request_timeout_seconds,
    )

    start_page = max(config.page, 1)
    max_pages = max(1, min(max_pages, 10))
    logger.info(
        "Sample scan starting at page %s for %s (max pages %s)",
        start_page,
        config.product,
        max_pages,
    )
    found_any = False
    reddit_entries: List[str] = []
    discord_entries: List[str] = []
    for offset in range(max_pages):
        page = start_page + offset
        logger.info("Fetching page %s", page)
        mods = client.fetch_mods(
            product=config.product,
            sort=config.sort,
            time_period=config.time_period,
            size=config.size,
            page=page,
            counts_platform=config.counts_platform,
            mod_url_template=config.mod_url_template,
        )
        logger.info("Fetched %s mods", len(mods))
        for mod in mods:
            logger.debug(
                "Sample scan: id=%s title=%s author_verified=%s prices=%s",
                mod.mod_id,
                mod.title,
                mod.author_verified,
                len(mod.prices),
            )
            if _is_new_creation(mod, config):
                title = build_post_title(mod, "new", include_emojis=False)
                body = render_post_body(mod, "new", config.post_template_path)
                reddit_entries.append(f"# {title}\n\n{body}")
                discord_entries.append(
                    render_post_body(mod, "new", config.discord_template_path)
                )
                found_any = True

    if not found_any:
        raise RuntimeError("No eligible creations found for sample post.")

    Path(output_path).write_text(
        "\n\n---\n\n".join(reddit_entries) + "\n", encoding="utf-8"
    )
    Path(discord_output_path).write_text(
        "\n\n---\n\n".join(discord_entries) + "\n", encoding="utf-8"
    )


def sync_mods(
    config: Config,
    store: SQLiteStore,
    client: BethesdaClient,
    post_new: bool,
    post_updates: bool,
    dry_run: bool,
    action_handler: Optional[Callable[[str, Mod], None]] = None,
    emit_eligible: bool = False,
) -> Tuple[List[Tuple[str, Mod]], int]:
    cutoff = _resolve_first_ptime_cutoff(config, store, dry_run)
    hard_stop = _hard_stop_for_product(config)
    effective_cutoff = _max_iso(cutoff, hard_stop)
    logger.info("Effective first_ptime cutoff: %s", effective_cutoff or "None")
    page = max(config.page, 1)
    total_seen = 0
    max_first_ptime: Optional[str] = None
    actions: List[Tuple[str, Mod]] = []
    now = utc_now_iso()

    while True:
        mods = client.fetch_mods(
            product=config.product,
            sort=config.sort,
            time_period=config.time_period,
            size=config.size,
            page=page,
            counts_platform=config.counts_platform,
            mod_url_template=config.mod_url_template,
        )
        logger.info("Fetched %s mods (page %s)", len(mods), page)
        total_seen += len(mods)
        stop = False
        page_last_first_ptime: Optional[str] = None

        for mod in mods:
            if not mod.mod_id:
                logger.warning("Skipping mod with missing content_id")
                continue
            if effective_cutoff and _is_before_or_equal_first_ptime(mod, effective_cutoff):
                logger.info(
                    "Stopping at mod %s first_ptime=%s cutoff=%s",
                    mod.mod_id,
                    mod.first_published_at or mod.published_at,
                    effective_cutoff,
                )
                stop = True

            mod_hash = compute_mod_hash(mod)
            existing = store.get_mod(mod.mod_id)
            action = _determine_action(
                existing, mod, mod_hash, post_new, post_updates, config
            )
            eligible = _is_new_creation(mod, config)
            logger.debug(
                "Decision %s: action=%s eligible=%s",
                mod.mod_id,
                action,
                eligible,
            )
            store.upsert_mod(mod, last_seen_at=now, mod_hash=mod_hash)
            if action:
                if action_handler:
                    action_handler(action, mod)
                else:
                    actions.append((action, mod))
            elif emit_eligible and eligible:
                if action_handler:
                    action_handler("new", mod)
                else:
                    actions.append(("new", mod))
            if mod.first_published_at and (
                max_first_ptime is None or mod.first_published_at > max_first_ptime
            ):
                max_first_ptime = mod.first_published_at
            if mod.first_published_at and (
                page_last_first_ptime is None
                or mod.first_published_at < page_last_first_ptime
            ):
                page_last_first_ptime = mod.first_published_at

        if page_last_first_ptime:
            logger.info(
                "Page %s oldest first_ptime: %s", page, page_last_first_ptime
            )

        if stop or not mods:
            break
        page += 1

    if max_first_ptime and not dry_run:
        store.set_meta(_meta_key_first_ptime(config.product), max_first_ptime)
        logger.info("Updated last_seen_first_ptime to %s", max_first_ptime)

    return actions, total_seen


def run(
    config: Config,
    post_new: bool = True,
    post_updates: bool = True,
    dry_run: bool = False,
    max_posts: Optional[int] = None,
    manual_output_dir: Optional[str] = None,
    ignore_db: bool = False,
) -> None:
    store = NullStore() if ignore_db else SQLiteStore(config.database_path)
    client = BethesdaClient(
        core_url=config.bethesda_core_url,
        content_url=config.bethesda_content_url,
        bnet_key=config.bethesda_bnet_key,
        bearer=config.bethesda_bearer,
        timeout_seconds=config.request_timeout_seconds,
    )

    try:
        if ignore_db and not manual_output_dir:
            dry_run = True
        logger.info("Manual output dir: %s", manual_output_dir or "None")
        post_count = 0
        dry_run_count = 0
        reddit = None
        discord = None

        if not dry_run and not manual_output_dir and not ignore_db:
            reddit_refresh_token = store.get_meta("reddit_refresh_token")
            reddit = RedditClient(
                client_id=config.reddit_client_id,
                client_secret=config.reddit_client_secret,
                username=config.reddit_username,
                password=config.reddit_password,
                user_agent=config.reddit_user_agent,
                subreddit=config.reddit_subreddit,
                refresh_token=reddit_refresh_token,
                session_cookies=config.reddit_session_cookies,
                csrf_token=config.reddit_csrf_token,
                flair_id=config.reddit_flair_id,
            )
            if config.discord_webhook_url:
                discord = DiscordClient(config.discord_webhook_url)

        def handle_action(action: str, mod: Mod) -> None:
            nonlocal post_count, dry_run_count
            if max_posts is not None and post_count >= max_posts:
                return
            if action == "update":
                logger.info("Update stub (no post sent): %s", mod.title)
                return
            title = build_post_title(mod, action, include_emojis=False)

            if dry_run:
                body = render_post_body(mod, action, config.post_template_path)
                logger.info("DRY RUN %s: %s", action.upper(), title)
                logger.debug(body)
                dry_run_count += 1
                return

            if manual_output_dir:
                output_dir = Path(manual_output_dir)
                reddit_dir = output_dir / "reddit"
                discord_dir = output_dir / "discord"
                wiki_dir = output_dir / "wiki"
                reddit_dir.mkdir(parents=True, exist_ok=True)
                discord_dir.mkdir(parents=True, exist_ok=True)
                wiki_dir.mkdir(parents=True, exist_ok=True)
                logger.info("Manual output directory: %s", output_dir.resolve())
                reddit_body = render_post_body(mod, action, config.post_template_path)
                discord_body = render_post_body(
                    mod, action, config.discord_template_path
                )
                wiki_body = render_post_body(mod, action, config.wiki_template_path)
                base_name = _safe_filename(
                    f"{(mod.first_published_at or 'unknown')[:10]}_{mod.author_displayname or 'Unknown'}_{mod.title}"
                )

                # Reddit subfolder and images
                post_reddit_dir = reddit_dir / base_name
                post_reddit_dir.mkdir(parents=True, exist_ok=True)
                (post_reddit_dir / f"{base_name}.md").write_text(
                    f"# {title}\n\n{reddit_body}\n", encoding="utf-8"
                )
                logger.info(
                    "Wrote %s", (post_reddit_dir / f"{base_name}.md").resolve()
                )
                if mod.preview_image_url:
                    download_image(mod.preview_image_url, post_reddit_dir / "image_00_preview.jpg", convert_to_jpg=True)
                
                gallery_urls = _image_urls(mod)
                for i, url in enumerate(gallery_urls):
                    download_image(url, post_reddit_dir / f"image_{i+1:02d}.jpg", convert_to_jpg=True)

                (discord_dir / f"{base_name}.md").write_text(
                    discord_body + "\n", encoding="utf-8"
                )
                logger.info(
                    "Wrote %s", (discord_dir / f"{base_name}.md").resolve()
                )
                (wiki_dir / f"{base_name}.txt").write_text(
                    wiki_body + "\n", encoding="utf-8"
                )
                logger.info("Wrote %s", (wiki_dir / f"{base_name}.txt").resolve())
                post_count += 1
                return

            post_count += 1
            try:
                image_paths = []
                # Use a temporary directory or data folder for transient images
                # For simplicity in 'run' mode, let's reuse the logic but clean up or use a specific folder
                temp_img_dir = Path("data/temp_images") / mod.mod_id
                temp_img_dir.mkdir(parents=True, exist_ok=True)
                
                if mod.preview_image_url:
                    img_path = temp_img_dir / "preview.jpg"
                    if download_image(mod.preview_image_url, img_path, convert_to_jpg=True):
                        image_paths.append(img_path)
                
                gallery_urls = _image_urls(mod)
                for i, url in enumerate(gallery_urls):
                    img_path = temp_img_dir / f"image_{i+1:02d}.jpg"
                    if download_image(url, img_path, convert_to_jpg=True):
                        image_paths.append(img_path)

                post_id, post_url = reddit.submit_post(
                    title, 
                    render_post_body(mod, action, config.post_template_path),
                    flair_id=_flair_id_for_product(mod, config),
                    image_paths=image_paths
                )
                store.mark_posted(
                    mod_id=mod.mod_id,
                    post_type=action,
                    post_id=post_id,
                    posted_at=utc_now_iso(),
                    title=title,
                    url=post_url,
                    target="reddit",
                    success=True,
                )
                logger.info("Posted %s: %s", action, post_url)
            except Exception as exc:
                store.mark_posted(
                    mod_id=mod.mod_id,
                    post_type=action,
                    post_id=_attempt_id(),
                    posted_at=utc_now_iso(),
                    title=title,
                    url=None,
                    target="reddit",
                    success=False,
                    error_message=str(exc),
                )
                logger.exception("Reddit post failed for %s", mod.mod_id)

            if discord:
                discord_body = render_post_body(mod, action, config.discord_template_path)
                try:
                    discord.send_message(discord_body)
                    store.mark_posted(
                        mod_id=mod.mod_id,
                        post_type=action,
                        post_id=_attempt_id(),
                        posted_at=utc_now_iso(),
                        title=title,
                        url=None,
                        target="discord",
                        success=True,
                    )
                    logger.info("Posted to Discord for %s", mod.mod_id)
                except Exception as exc:
                    store.mark_posted(
                        mod_id=mod.mod_id,
                        post_type=action,
                        post_id=_attempt_id(),
                        posted_at=utc_now_iso(),
                        title=title,
                        url=None,
                        target="discord",
                        success=False,
                        error_message=str(exc),
                    )
                    logger.exception("Discord post failed for %s", mod.mod_id)

        actions, fetched = sync_mods(
            config,
            store,
            client,
            post_new,
            post_updates,
            dry_run,
            action_handler=handle_action,
            emit_eligible=bool(manual_output_dir),
        )
        logger.info("Processed %s mods", fetched)

        if not actions and post_count == 0 and dry_run_count == 0:
            logger.info("No posts due")
            return
    finally:
        store.close()


def retry_failed_posts(config: Config, dry_run: bool = False) -> None:
    store = SQLiteStore(config.database_path)
    reddit = None
    discord = None
    if config.reddit_client_id or (config.reddit_session_cookies and config.reddit_csrf_token):
        try:
            reddit_refresh_token = store.get_meta("reddit_refresh_token")
            reddit = RedditClient(
                client_id=config.reddit_client_id,
                client_secret=config.reddit_client_secret,
                username=config.reddit_username,
                password=config.reddit_password,
                user_agent=config.reddit_user_agent,
                subreddit=config.reddit_subreddit,
                refresh_token=reddit_refresh_token,
                session_cookies=config.reddit_session_cookies,
                csrf_token=config.reddit_csrf_token,
                flair_id=config.reddit_flair_id,
            )
        except Exception as exc:
            logger.warning("Reddit client init failed: %s", exc)
    if config.discord_webhook_url:
        try:
            discord = DiscordClient(config.discord_webhook_url)
        except Exception as exc:
            logger.warning("Discord client init failed: %s", exc)

    try:
        if reddit:
            failed = store.get_failed_posts("reddit")
            logger.info("Retrying %s failed Reddit posts", len(failed))
            for entry in failed:
                mod = store.get_mod_model(entry["mod_id"])
                if not mod:
                    logger.warning("Missing mod for retry: %s", entry["mod_id"])
                    continue
                title = build_post_title(mod, entry["post_type"])
                body = render_post_body(mod, entry["post_type"], config.post_template_path)
                if dry_run:
                    logger.info("DRY RUN retry reddit: %s", title)
                    continue
                try:
                    image_paths = []
                    temp_img_dir = Path("data/temp_images") / mod.mod_id
                    temp_img_dir.mkdir(parents=True, exist_ok=True)
                    if mod.preview_image_url:
                        img_path = temp_img_dir / "preview.jpg"
                        if download_image(mod.preview_image_url, img_path, convert_to_jpg=True):
                            image_paths.append(img_path)
                    gallery_urls = _image_urls(mod)
                    for i, url in enumerate(gallery_urls):
                        img_path = temp_img_dir / f"image_{i+1:02d}.jpg"
                        if download_image(url, img_path, convert_to_jpg=True):
                            image_paths.append(img_path)

                    post_id, post_url = reddit.submit_post(
                        title, 
                        body, 
                        flair_id=_flair_id_for_product(mod, config),
                        image_paths=image_paths
                    )
                    store.mark_posted(
                        mod_id=mod.mod_id,
                        post_type=entry["post_type"],
                        post_id=post_id,
                        posted_at=utc_now_iso(),
                        title=title,
                        url=post_url,
                        target="reddit",
                        success=True,
                    )
                    logger.info("Retried Reddit post: %s", post_url)
                except Exception as exc:
                    store.mark_posted(
                        mod_id=mod.mod_id,
                        post_type=entry["post_type"],
                        post_id=_attempt_id(),
                        posted_at=utc_now_iso(),
                        title=title,
                        url=None,
                        target="reddit",
                        success=False,
                        error_message=str(exc),
                    )
                    logger.exception("Retry Reddit failed for %s", mod.mod_id)

        if discord:
            failed = store.get_failed_posts("discord")
            missing = store.get_missing_discord_posts()
            retries = failed + missing
            logger.info("Retrying %s Discord posts", len(retries))
            for entry in retries:
                mod = store.get_mod_model(entry["mod_id"])
                if not mod:
                    logger.warning("Missing mod for retry: %s", entry["mod_id"])
                    continue
                body = render_post_body(
                    mod, entry["post_type"], config.discord_template_path
                )
                if dry_run:
                    logger.info("DRY RUN retry discord: %s", mod.mod_id)
                    continue
                try:
                    discord.send_message(body)
                    store.mark_posted(
                        mod_id=mod.mod_id,
                        post_type=entry["post_type"],
                        post_id=_attempt_id(),
                        posted_at=utc_now_iso(),
                        title=mod.title,
                        url=None,
                        target="discord",
                        success=True,
                    )
                    logger.info("Retried Discord post for %s", mod.mod_id)
                except Exception as exc:
                    store.mark_posted(
                        mod_id=mod.mod_id,
                        post_type=entry["post_type"],
                        post_id=_attempt_id(),
                        posted_at=utc_now_iso(),
                        title=mod.title,
                        url=None,
                        target="discord",
                        success=False,
                        error_message=str(exc),
                    )
                    logger.exception("Retry Discord failed for %s", mod.mod_id)
    finally:
        store.close()


def generate_template_files(
    config: Config,
    output_dir: str,
    template_kind: str,
    cutoff_date: str,
) -> Tuple[int, List[Tuple[str, str, List[str], str, Optional[str]]]]:
    client = BethesdaClient(
        core_url=config.bethesda_core_url,
        content_url=config.bethesda_content_url,
        bnet_key=config.bethesda_bnet_key,
        bearer=config.bethesda_bearer,
        timeout_seconds=config.request_timeout_seconds,
    )
    cutoff = parse_iso(cutoff_date)
    if not cutoff:
        raise ValueError("Invalid cutoff_date format")

    template_map = {
        "reddit": config.post_template_path,
        "discord": config.discord_template_path,
        "wiki": config.wiki_template_path,
    }
    template_path = template_map.get(template_kind.lower())
    if not template_path:
        raise ValueError("template_kind must be reddit, discord, or wiki")

    out_base = Path(output_dir)
    out_dir = out_base / template_kind.lower()
    out_dir.mkdir(parents=True, exist_ok=True)

    page = max(config.page, 1)
    total_written = 0
    generated_posts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        while True:
            mods = client.fetch_mods(
                product=config.product,
                sort=config.sort,
                time_period=config.time_period,
                size=config.size,
                page=page,
                counts_platform=config.counts_platform,
                mod_url_template=config.mod_url_template,
            )
            logger.info("Fetched %s mods (page %s)", len(mods), page)
            if not mods:
                break

            stop = False
            futures = []
            for mod in mods:
                mod_time = parse_iso(mod.first_published_at) or parse_iso(mod.published_at)
                if mod_time and mod_time <= cutoff:
                    stop = True
                    continue
                if not _is_new_creation(mod, config):
                    continue

                futures.append(executor.submit(
                    _write_template_task,
                    mod=mod,
                    template_kind=template_kind,
                    template_path=template_path,
                    out_dir=out_dir,
                    config=config
                ))

            for future in concurrent.futures.as_completed(futures):
                try:
                    res = future.result()
                    if res:
                        total_written += 1
                        generated_posts.append(res)
                except Exception as exc:
                    logger.error("Error in template task: %s", exc)

            if stop:
                break
            page += 1

    logger.info("Wrote %s %s templates", total_written, template_kind)
    return total_written, generated_posts


def _write_template_task(
    mod: Mod,
    template_kind: str,
    template_path: Path,
    out_dir: Path,
    config: Config
) -> Optional[Tuple[str, str, List[str], str, Optional[str]]]:
    try:
        title = build_post_title(mod, "new", include_emojis=False)
        body = render_post_body(mod, "new", template_path)
        pub_date = mod.first_published_at or mod.published_at or "unknown"
        base_name = _safe_filename(
            f"{pub_date[:10]}_{mod.author_displayname or 'Unknown'}_{mod.title}"
        )
        suffix = "md" if template_kind.lower() in {"reddit", "discord"} else "txt"
        
        image_paths = []
        if template_kind.lower() == "reddit":
            post_dir = out_dir / base_name
            post_dir.mkdir(parents=True, exist_ok=True)
            (post_dir / f"{base_name}.{suffix}").write_text(
                f"# {title}\n\n{body}\n", encoding="utf-8"
            )
            if mod.preview_image_url:
                img_path = post_dir / "image_00_preview.jpg"
                if download_image(mod.preview_image_url, img_path, convert_to_jpg=True):
                    image_paths.append(str(img_path))
            
            gallery_urls = _image_urls(mod)
            for i, url in enumerate(gallery_urls):
                img_path = post_dir / f"image_{i+1:02d}.jpg"
                if download_image(url, img_path, convert_to_jpg=True):
                    image_paths.append(str(img_path))
        else:
            (out_dir / f"{base_name}.{suffix}").write_text(
                f"# {title}\n\n{body}\n" if template_kind.lower() != "wiki" else body + "\n",
                encoding="utf-8",
            )
            
        return title, body, image_paths, pub_date, _flair_id_for_product(mod, config)
    except Exception as exc:
        logger.error("Failed to write template for %s: %s", mod.mod_id, exc)
        return None


def authorize_reddit(config: Config) -> None:
    if not config.reddit_client_id or not config.reddit_client_secret:
        raise ValueError("Missing Reddit client configuration")
    if not config.reddit_redirect_uri:
        raise ValueError("Missing REDDIT_REDIRECT_URI")
    scope = config.reddit_oauth_scope or "identity submit"
    state = _attempt_id()
    auth_url = (
        "https://www.reddit.com/api/v1/authorize"
        f"?client_id={config.reddit_client_id}"
        f"&response_type=code"
        f"&state={state}"
        f"&redirect_uri={config.reddit_redirect_uri}"
        f"&duration=permanent"
        f"&scope={scope.replace(' ', '%20')}"
    )

    code_holder = {"code": None, "state": None}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != urlparse(config.reddit_redirect_uri).path:
                self.send_response(404)
                self.end_headers()
                return
            query = parse_qs(parsed.query)
            code_holder["code"] = (query.get("code") or [None])[0]
            code_holder["state"] = (query.get("state") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Authorization received. You can close this window.")

        def log_message(self, format: str, *args: object) -> None:
            return

    redirect = urlparse(config.reddit_redirect_uri)
    server = HTTPServer((redirect.hostname or "localhost", redirect.port or 8080), Handler)

    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    logger.info("Open this URL to authorize Reddit:\n%s", auth_url)
    thread.join(timeout=300)
    server.server_close()

    if code_holder["state"] != state or not code_holder["code"]:
        raise RuntimeError("OAuth callback failed or was not received.")

    auth = requests.auth.HTTPBasicAuth(
        config.reddit_client_id, config.reddit_client_secret
    )
    data = {
        "grant_type": "authorization_code",
        "code": code_holder["code"],
        "redirect_uri": config.reddit_redirect_uri,
    }
    headers = {"User-Agent": config.reddit_user_agent or "vcbot"}
    response = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=auth,
        data=data,
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("No refresh_token in Reddit response")

    store = SQLiteStore(config.database_path)
    try:
        store.set_meta("reddit_refresh_token", refresh_token)
        logger.info("Stored Reddit refresh token in DB meta")
    finally:
        store.close()
