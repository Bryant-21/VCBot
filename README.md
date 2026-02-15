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

The bot exposes all fields from the `Mod` class as template variables, plus several computed fields.

### Common Variables

- `{post_type}`: "creation" or "update"
- `{title}`: Mod title
- `{summary}`: Cleaned up short summary
- `{description}`: Full mod description (markdown cleaned)
- `{author}`: Author display name
- `{author_url}`: URL to author's profile on Bethesda
- `{product}`: Internal product ID (e.g. "STARFIELD")
- `{product_title}`: Display name of the game
- `{platforms}`: Comma-separated hardware platforms
- `{platform_full_names}`: Comma-separated readable platform names
- `{platform_emojis}`: Platform emojis (e.g. :xbox: :pc:)
- `{categories}`: Comma-separated categories
- `{prices}`: Human-readable price string
- `{price_credits}`: Price in credits
- `{release_date}`: First published date (YYYY-MM-DD)
- `{version}`: Latest version from release notes
- `{details_url}`: Link to mod on Bethesda site
- `{preview_image_url}`, `{cover_image_url}`, `{banner_image_url}`: Various image URLs
- `{image_urls}`: List of all screenshot URLs
- `{mod_id}`: The Bethesda content ID

### Timestamp Aliases

- `{ptime}`: Published at (ISO format)
- `{first_ptime}`: First published at (ISO format)
- `{ctime}`: Created at (ISO format)
- `{utime}`: Updated at (ISO format)

### Full Mod Fields

Any attribute of the `Mod` class in `vcbot/bethesda.py` can be used, including:
`mod_id`, `title`, `overview`, `description`, `product`, `product_title`, `content_type`, `hardware_platforms`, `categories`, `author_displayname`, `author_buid`, `author_verified`, `author_official`, `published_buid`, `updated_buid`, `created_at`, `published_at`, `first_published_at`, `updated_at`, `status`, `moderation_state`, `error_info`, `deleted`, `published`, `moderated`, `beta`, `maintenance`, `restricted`, `use_high_report_threshold`, `marketplace`, `review_revision`, `author_price`, `achievement_friendly`, `default_locale`, `supported_locales`, `stats`.

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

### Reddit Web Mode

If you cannot obtain official Reddit API keys (Client ID and Secret), you can use "Web Mode" by providing your browser session cookies and CSRF token.

1. Log in to Reddit in your browser.
2. Open Developer Tools (F12) -> Network tab.
3. Create a post or perform an action, and look for a request to `graphql`.
4. Copy the `Cookie` header value and the `x-reddit-csrf` header value.
5. In your `.env` file, set:
   - `REDDIT_SESSION_COOKIES`: The full string from the `Cookie` header.
   - `REDDIT_CSRF_TOKEN`: The value from the `x-reddit-csrf` header.
6. Ensure `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` are left empty.

Use `--help` on either command to see available overrides.

Manual mode: pass `--manual-output-dir <path>` to `run` to write Reddit/Discord templates instead of posting.
