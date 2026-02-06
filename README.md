# Bethesda Reddit Bot

Fetch Bethesda mod data and post updates to Reddit while tracking what was already posted.

## Setup

1. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and fill in your Reddit credentials and optional Bethesda overrides.

3. Run a fetch-only sync to populate the local database:

```bash
python main.py fetch
```

4. Preview posts without sending:

```bash
python main.py run --dry-run
```

5. Post to Reddit:

```bash
python main.py run
```

## Notes

- The bot fetches `ugc.bnetKey` from `https://cdn.bethesda.net/data/core` unless `BETHESDA_BNET_KEY` is provided.
- Mod tracking data is stored in `data/vcbot.db` (configurable via `DATABASE_PATH`).
- Update posts trigger when the mod `utime` changes or the content hash changes.
- You can customize the mod detail URL template via `BETHESDA_MOD_URL_TEMPLATE`.
- Set `BETHESDA_COUNTS_PLATFORM` to control the `counts_platform` query parameter (default `ALL`).
- The Reddit body uses `POST_TEMPLATE_PATH` (default `templates/post.md`) for markdown rendering.
- Discord posting uses `DISCORD_WEBHOOK_URL` and `DISCORD_TEMPLATE_PATH` (default `templates/discord_post.md`).

## Template Variables

The default template supports placeholders like:

- `{post_type}`, `{title}`, `{summary}`, `{author}`, `{author_url}`, `{product}`
- `{platforms}`, `{platform_full_names}`, `{platform_emojis}`, `{categories}`, `{prices}`
- `{details_url}`, `{preview_image_url}`, `{cover_image_url}`, `{banner_image_url}`
- `{image_urls}`, `{mod_id}`

## Tracking Notes

- The bot stops scanning when it reaches the last seen `first_ptime` for the product.
- Set `SYNTHETIC_LAST_SEEN_FIRST_PTIME` to force a cutoff during dry runs or testing.

## Commands

- `fetch`: Fetch mods and update the local DB only.
- `run`: Fetch mods and post new/update entries to Reddit.
- `sample`: Generate local markdown posts for Reddit and Discord by paging until an eligible creation is found.
- `export-db`: Export the database to JSON.
- `import-db`: Import the database from JSON.
- `retry`: Retry failed or missed posts for Reddit/Discord.
- `reddit-auth`: Run the local OAuth callback flow and store a Reddit refresh token.

Use `--help` on either command to see available overrides.

Manual mode: pass `--manual-output-dir <path>` to `run` to write Reddit/Discord templates instead of posting.
