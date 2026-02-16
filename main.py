import argparse
import logging
import json
from datetime import datetime
from dataclasses import replace
from pathlib import Path
from typing import Optional

from vcbot.app import authorize_reddit, generate_sample_post, retry_failed_posts, run, sync_mods
from vcbot.bethesda import BethesdaClient
from vcbot.config import Config, load_config
from vcbot.db import SQLiteStore


def _configure_logging(verbose: bool, trace: bool, log_file: Optional[str]) -> None:
    level = logging.DEBUG if (trace or verbose) else logging.INFO
    handlers = []
    if not log_file:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_file = f"logs/vcbot-{stamp}.log"
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )
    if trace:
        logging.getLogger("vcbot.trace").setLevel(logging.DEBUG)
    else:
        logging.getLogger("vcbot.trace").setLevel(logging.WARNING)


def _apply_overrides(config: Config, args: argparse.Namespace) -> Config:
    updated = config
    if args.product:
        updated = replace(updated, product=args.product.strip().upper())
    if args.sort:
        updated = replace(updated, sort=args.sort)
    if args.time_period:
        updated = replace(updated, time_period=args.time_period)
    if args.size is not None:
        updated = replace(updated, size=args.size)
    if args.page is not None:
        updated = replace(updated, page=args.page)
    if args.counts_platform:
        updated = replace(updated, counts_platform=args.counts_platform)
    if args.post_template:
        updated = replace(updated, post_template_path=Path(args.post_template))
    if args.db:
        updated = replace(updated, database_path=Path(args.db))
    if args.mod_url_template:
        updated = replace(updated, mod_url_template=args.mod_url_template)
    return updated


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--product",
        help="Bethesda product code, e.g. FALLOUT4, SKYRIM, STARFIELD",
    )
    parser.add_argument("--sort", help="Sort field, e.g. ptime")
    parser.add_argument("--time-period", help="Time period, e.g. monthly")
    parser.add_argument("--size", type=int, help="Page size")
    parser.add_argument("--page", type=int, help="Page number")
    parser.add_argument("--counts-platform", help="Counts platform, e.g. ALL")
    parser.add_argument("--post-template", help="Markdown template path")
    parser.add_argument("--db", help="SQLite DB path")
    parser.add_argument("--mod-url-template", help="Template for mod detail URLs")


def _create_client(config: Config) -> BethesdaClient:
    return BethesdaClient(
        core_url=config.bethesda_core_url,
        content_url=config.bethesda_content_url,
        bnet_key=config.bethesda_bnet_key,
        bearer=config.bethesda_bearer,
        #origin=config.bethesda_origin,
        #referer=config.bethesda_referer,
        #user_agent=config.bethesda_user_agent,
        timeout_seconds=config.request_timeout_seconds,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Bethesda mod tracker and Reddit poster")
    parser.add_argument("--env", help="Path to .env file")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--trace", action="store_true", help="Enable trace logging")
    parser.add_argument(
        "--log-file",
        help="Log file path (defaults to logs/vcbot-<timestamp>.log)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch mods and update local DB")
    _add_common_args(fetch_parser)

    run_parser = subparsers.add_parser("run", help="Fetch mods and post to Reddit")
    _add_common_args(run_parser)
    run_parser.add_argument("--no-new", action="store_true", help="Disable new mod posts")
    run_parser.add_argument("--no-updates", action="store_true", help="Disable update posts")
    run_parser.add_argument("--dry-run", action="store_true", help="Preview posts without sending")
    run_parser.add_argument("--max-posts", type=int, help="Limit number of posts per run")
    run_parser.add_argument(
        "--manual-output-dir",
        help="Write Reddit/Discord templates to this directory instead of posting",
    )

    export_parser = subparsers.add_parser("export-db", help="Export DB to JSON")
    export_parser.add_argument("--output", default="db_export.json", help="Output JSON path")

    import_parser = subparsers.add_parser("import-db", help="Import DB from JSON")
    import_parser.add_argument("--input", required=True, help="Input JSON path")

    retry_parser = subparsers.add_parser(
        "retry", help="Retry failed or missed posts"
    )
    retry_parser.add_argument(
        "--dry-run", action="store_true", help="Preview retries without sending"
    )

    auth_parser = subparsers.add_parser(
        "reddit-auth", help="Authorize Reddit and store refresh token"
    )

    sample_parser = subparsers.add_parser(
        "sample", help="Generate a sample markdown post locally"
    )
    _add_common_args(sample_parser)
    sample_parser.add_argument(
        "--output",
        default="sample_post.md",
        help="Output markdown file path",
    )
    sample_parser.add_argument(
        "--discord-output",
        default="sample_discord_post.md",
        help="Output markdown file path for Discord",
    )
    sample_parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Max pages to scan for eligible creations",
    )

    args = parser.parse_args()
    _configure_logging(args.verbose, args.trace, args.log_file)

    env_path: Optional[Path] = Path(args.env) if args.env else None
    config = load_config(env_path)
    config = _apply_overrides(config, args)

    if args.command == "fetch":
        store = SQLiteStore(config.database_path)
        client = _create_client(config)
        try:
            _, fetched = sync_mods(
                config, store, client, post_new=False, post_updates=False, dry_run=False
            )
            logging.info("Fetched %s mods and updated DB", fetched)
        finally:
            store.close()
        return

    if args.command == "run":
        dry_run = args.dry_run or config.dry_run
        post_new = not args.no_new
        post_updates = not args.no_updates
        run(
            config,
            post_new=post_new,
            post_updates=post_updates,
            dry_run=dry_run,
            max_posts=args.max_posts,
            manual_output_dir=args.manual_output_dir,
        )
        return

    if args.command == "sample":
        generate_sample_post(
            config,
            output_path=args.output,
            discord_output_path=args.discord_output,
            max_pages=args.max_pages,
        )
        logging.info(
            "Wrote sample posts to %s and %s", args.output, args.discord_output
        )
        return

    if args.command == "export-db":
        store = SQLiteStore(config.database_path)
        try:
            payload = store.export_json()
            Path(args.output).write_text(
                json.dumps(payload, indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
            logging.info("Exported DB to %s", args.output)
        finally:
            store.close()
        return

    if args.command == "import-db":
        store = SQLiteStore(config.database_path)
        try:
            raw = Path(args.input).read_text(encoding="utf-8")
            payload = json.loads(raw)
            store.import_json(payload)
            logging.info("Imported DB from %s", args.input)
        finally:
            store.close()
        return

    if args.command == "retry":
        retry_failed_posts(config, dry_run=args.dry_run)
        return

    if args.command == "reddit-auth":
        authorize_reddit(config)
        return


if __name__ == "__main__":
    main()
