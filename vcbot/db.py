import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .bethesda import Mod


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS mods (
                mod_id TEXT PRIMARY KEY,
                product TEXT NOT NULL,
                product_title TEXT,
                title TEXT,
                overview TEXT,
                description TEXT,
                content_type TEXT,
                author_displayname TEXT,
                author_buid TEXT,
                author_verified INTEGER,
                author_official INTEGER,
                published_buid TEXT,
                updated_buid TEXT,
                created_at TEXT,
                published_at TEXT,
                first_published_at TEXT,
                updated_at TEXT,
                status TEXT,
                moderation_state TEXT,
                error_info TEXT,
                deleted INTEGER,
                published INTEGER,
                moderated INTEGER,
                beta INTEGER,
                maintenance INTEGER,
                restricted INTEGER,
                use_high_report_threshold INTEGER,
                marketplace INTEGER,
                review_revision INTEGER,
                author_price_json TEXT,
                required_dlc_json TEXT,
                required_mods_json TEXT,
                achievement_friendly INTEGER,
                default_locale TEXT,
                supported_locales_json TEXT,
                release_notes_json TEXT,
                stats_json TEXT,
                custom_data_json TEXT,
                catalog_info_json TEXT,
                prices_json TEXT,
                categories_json TEXT,
                platforms_json TEXT,
                preview_image_url TEXT,
                cover_image_url TEXT,
                preview_image_json TEXT,
                cover_image_json TEXT,
                screenshot_images_json TEXT,
                videos_json TEXT,
                details_url TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_seen_ptime TEXT,
                last_posted_at TEXT,
                last_update_posted_at TEXT,
                last_known_hash TEXT
            );

            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mod_id TEXT NOT NULL,
                post_id TEXT NOT NULL,
                post_type TEXT NOT NULL,
                target TEXT NOT NULL,
                success INTEGER NOT NULL,
                error_message TEXT,
                posted_at TEXT NOT NULL,
                title TEXT,
                url TEXT,
                FOREIGN KEY(mod_id) REFERENCES mods(mod_id)
            );

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_unique
                ON posts(mod_id, post_type, post_id);
            """
        )
        self._ensure_columns(
            "mods",
            {
                "author_verified": "INTEGER",
                "author_official": "INTEGER",
                "published_buid": "TEXT",
                "updated_buid": "TEXT",
                "moderation_state": "TEXT",
                "error_info": "TEXT",
                "beta": "INTEGER",
                "maintenance": "INTEGER",
                "restricted": "INTEGER",
                "use_high_report_threshold": "INTEGER",
                "marketplace": "INTEGER",
                "review_revision": "INTEGER",
                "author_price_json": "TEXT",
                "required_dlc_json": "TEXT",
                "required_mods_json": "TEXT",
                "achievement_friendly": "INTEGER",
                "default_locale": "TEXT",
                "supported_locales_json": "TEXT",
                "release_notes_json": "TEXT",
                "stats_json": "TEXT",
                "custom_data_json": "TEXT",
                "catalog_info_json": "TEXT",
                "prices_json": "TEXT",
                "preview_image_json": "TEXT",
                "cover_image_json": "TEXT",
                "screenshot_images_json": "TEXT",
                "videos_json": "TEXT",
                "last_seen_ptime": "TEXT",
            },
        )
        self._ensure_columns(
            "posts",
            {
                "target": "TEXT",
                "success": "INTEGER",
                "error_message": "TEXT",
            },
        )
        self.conn.commit()

    def _ensure_columns(self, table: str, columns: Dict[str, str]) -> None:
        existing = {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table})")
        }
        for name, col_type in columns.items():
            if name not in existing:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")

    def get_mod(self, mod_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.execute("SELECT * FROM mods WHERE mod_id = ?", (mod_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

    def get_mod_model(self, mod_id: str) -> Optional[Mod]:
        row = self.get_mod(mod_id)
        if not row:
            return None
        return Mod(
            mod_id=row.get("mod_id") or "",
            title=row.get("title") or "",
            overview=row.get("overview"),
            description=row.get("description"),
            product=row.get("product") or "",
            product_title=row.get("product_title"),
            content_type=row.get("content_type"),
            hardware_platforms=_json_load(row.get("platforms_json"), []),
            categories=_json_load(row.get("categories_json"), []),
            author_displayname=row.get("author_displayname"),
            author_buid=row.get("author_buid"),
            author_verified=bool(row.get("author_verified")),
            author_official=bool(row.get("author_official")),
            published_buid=row.get("published_buid"),
            updated_buid=row.get("updated_buid"),
            created_at=row.get("created_at"),
            published_at=row.get("published_at"),
            first_published_at=row.get("first_published_at"),
            updated_at=row.get("updated_at"),
            status=row.get("status"),
            moderation_state=row.get("moderation_state"),
            error_info=row.get("error_info"),
            deleted=bool(row.get("deleted")),
            published=bool(row.get("published")),
            moderated=bool(row.get("moderated")),
            beta=bool(row.get("beta")),
            maintenance=bool(row.get("maintenance")),
            restricted=bool(row.get("restricted")),
            use_high_report_threshold=bool(row.get("use_high_report_threshold")),
            marketplace=bool(row.get("marketplace")),
            review_revision=bool(row.get("review_revision")),
            author_price=_json_load(row.get("author_price_json"), None),
            required_dlc=_json_load(row.get("required_dlc_json"), []),
            required_mods=_json_load(row.get("required_mods_json"), []),
            achievement_friendly=bool(row.get("achievement_friendly")),
            default_locale=row.get("default_locale"),
            supported_locales=_json_load(row.get("supported_locales_json"), []),
            release_notes=_json_load(row.get("release_notes_json"), []),
            stats=_json_load(row.get("stats_json"), {}),
            custom_data=_json_load(row.get("custom_data_json"), None),
            catalog_info=_json_load(row.get("catalog_info_json"), []),
            prices=_json_load(row.get("prices_json"), []),
            preview_image_url=row.get("preview_image_url"),
            cover_image_url=row.get("cover_image_url"),
            preview_image=_json_load(row.get("preview_image_json"), {}),
            cover_image=_json_load(row.get("cover_image_json"), {}),
            screenshot_images=_json_load(row.get("screenshot_images_json"), []),
            videos=_json_load(row.get("videos_json"), []),
            details_url=row.get("details_url"),
        )

    def get_failed_posts(self, target: str) -> List[Dict[str, Any]]:
        cursor = self.conn.execute(
            """
            SELECT mod_id, post_type
            FROM posts
            WHERE target = ? AND success = 0
            GROUP BY mod_id, post_type
            """,
            (target,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_missing_discord_posts(self) -> List[Dict[str, Any]]:
        cursor = self.conn.execute(
            """
            SELECT mods.mod_id, 'new' AS post_type
            FROM mods
            WHERE mods.last_posted_at IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM posts
                  WHERE posts.mod_id = mods.mod_id
                    AND posts.target = 'discord'
                    AND posts.success = 1
                    AND posts.post_type = 'new'
              )
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_meta(self, key: str) -> Optional[str]:
        cursor = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = cursor.fetchone()
        if not row:
            return None
        return row["value"]

    def set_meta(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO meta (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def export_json(self) -> Dict[str, Any]:
        mods = [dict(row) for row in self.conn.execute("SELECT * FROM mods")]
        posts = [dict(row) for row in self.conn.execute("SELECT * FROM posts")]
        meta = [dict(row) for row in self.conn.execute("SELECT * FROM meta")]
        return {"mods": mods, "posts": posts, "meta": meta}

    def import_json(self, payload: Dict[str, Any]) -> None:
        mods = payload.get("mods") or []
        posts = payload.get("posts") or []
        meta = payload.get("meta") or []
        with self.conn:
            for row in meta:
                if "key" in row and "value" in row:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                        (row["key"], row["value"]),
                    )
            for row in mods:
                columns = list(row.keys())
                if not columns:
                    continue
                placeholders = ", ".join("?" for _ in columns)
                cols = ", ".join(columns)
                values = [row[col] for col in columns]
                self.conn.execute(
                    f"INSERT OR REPLACE INTO mods ({cols}) VALUES ({placeholders})",
                    values,
                )
            for row in posts:
                columns = list(row.keys())
                if not columns:
                    continue
                placeholders = ", ".join("?" for _ in columns)
                cols = ", ".join(columns)
                values = [row[col] for col in columns]
                self.conn.execute(
                    f"INSERT OR REPLACE INTO posts ({cols}) VALUES ({placeholders})",
                    values,
                )

    def upsert_mod(self, mod: Mod, last_seen_at: str, mod_hash: str) -> None:
        categories_json = json.dumps(mod.categories, ensure_ascii=True)
        platforms_json = json.dumps(mod.hardware_platforms, ensure_ascii=True)
        author_price_json = json.dumps(mod.author_price, ensure_ascii=True)
        required_dlc_json = json.dumps(mod.required_dlc, ensure_ascii=True)
        required_mods_json = json.dumps(mod.required_mods, ensure_ascii=True)
        supported_locales_json = json.dumps(mod.supported_locales, ensure_ascii=True)
        release_notes_json = json.dumps(mod.release_notes, ensure_ascii=True)
        stats_json = json.dumps(mod.stats, ensure_ascii=True)
        custom_data_json = json.dumps(mod.custom_data, ensure_ascii=True)
        catalog_info_json = json.dumps(mod.catalog_info, ensure_ascii=True)
        prices_json = json.dumps(mod.prices, ensure_ascii=True)
        preview_image_json = json.dumps(mod.preview_image, ensure_ascii=True)
        cover_image_json = json.dumps(mod.cover_image, ensure_ascii=True)
        screenshot_images_json = json.dumps(mod.screenshot_images, ensure_ascii=True)
        videos_json = json.dumps(mod.videos, ensure_ascii=True)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO mods (
                    mod_id,
                    product,
                    product_title,
                    title,
                    overview,
                    description,
                    content_type,
                    author_displayname,
                    author_buid,
                    author_verified,
                    author_official,
                    published_buid,
                    updated_buid,
                    created_at,
                    published_at,
                    first_published_at,
                    updated_at,
                    status,
                    moderation_state,
                    error_info,
                    deleted,
                    published,
                    moderated,
                    beta,
                    maintenance,
                    restricted,
                    use_high_report_threshold,
                    marketplace,
                    review_revision,
                    author_price_json,
                    required_dlc_json,
                    required_mods_json,
                    achievement_friendly,
                    default_locale,
                    supported_locales_json,
                    release_notes_json,
                    stats_json,
                    custom_data_json,
                    catalog_info_json,
                    prices_json,
                    categories_json,
                    platforms_json,
                    preview_image_url,
                    cover_image_url,
                    preview_image_json,
                    cover_image_json,
                    screenshot_images_json,
                    videos_json,
                    details_url,
                    first_seen_at,
                    last_seen_at,
                    last_seen_ptime,
                    last_known_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mod_id) DO UPDATE SET
                    product = excluded.product,
                    product_title = excluded.product_title,
                    title = excluded.title,
                    overview = excluded.overview,
                    description = excluded.description,
                    content_type = excluded.content_type,
                    author_displayname = excluded.author_displayname,
                    author_buid = excluded.author_buid,
                    author_verified = excluded.author_verified,
                    author_official = excluded.author_official,
                    published_buid = excluded.published_buid,
                    updated_buid = excluded.updated_buid,
                    created_at = excluded.created_at,
                    published_at = excluded.published_at,
                    first_published_at = excluded.first_published_at,
                    updated_at = excluded.updated_at,
                    status = excluded.status,
                    moderation_state = excluded.moderation_state,
                    error_info = excluded.error_info,
                    deleted = excluded.deleted,
                    published = excluded.published,
                    moderated = excluded.moderated,
                    beta = excluded.beta,
                    maintenance = excluded.maintenance,
                    restricted = excluded.restricted,
                    use_high_report_threshold = excluded.use_high_report_threshold,
                    marketplace = excluded.marketplace,
                    review_revision = excluded.review_revision,
                    author_price_json = excluded.author_price_json,
                    required_dlc_json = excluded.required_dlc_json,
                    required_mods_json = excluded.required_mods_json,
                    achievement_friendly = excluded.achievement_friendly,
                    default_locale = excluded.default_locale,
                    supported_locales_json = excluded.supported_locales_json,
                    release_notes_json = excluded.release_notes_json,
                    stats_json = excluded.stats_json,
                    custom_data_json = excluded.custom_data_json,
                    catalog_info_json = excluded.catalog_info_json,
                    prices_json = excluded.prices_json,
                    categories_json = excluded.categories_json,
                    platforms_json = excluded.platforms_json,
                    preview_image_url = excluded.preview_image_url,
                    cover_image_url = excluded.cover_image_url,
                    preview_image_json = excluded.preview_image_json,
                    cover_image_json = excluded.cover_image_json,
                    screenshot_images_json = excluded.screenshot_images_json,
                    videos_json = excluded.videos_json,
                    details_url = excluded.details_url,
                    last_seen_at = excluded.last_seen_at,
                    last_seen_ptime = excluded.last_seen_ptime,
                    last_known_hash = excluded.last_known_hash,
                    first_seen_at = COALESCE(mods.first_seen_at, excluded.first_seen_at)
                """,
                (
                    mod.mod_id,
                    mod.product,
                    mod.product_title,
                    mod.title,
                    mod.overview,
                    mod.description,
                    mod.content_type,
                    mod.author_displayname,
                    mod.author_buid,
                    int(mod.author_verified),
                    int(mod.author_official),
                    mod.published_buid,
                    mod.updated_buid,
                    mod.created_at,
                    mod.published_at,
                    mod.first_published_at,
                    mod.updated_at,
                    mod.status,
                    mod.moderation_state,
                    mod.error_info,
                    int(mod.deleted),
                    int(mod.published),
                    int(mod.moderated),
                    int(mod.beta),
                    int(mod.maintenance),
                    int(mod.restricted),
                    int(mod.use_high_report_threshold),
                    int(mod.marketplace),
                    int(mod.review_revision),
                    author_price_json,
                    required_dlc_json,
                    required_mods_json,
                    int(mod.achievement_friendly),
                    mod.default_locale,
                    supported_locales_json,
                    release_notes_json,
                    stats_json,
                    custom_data_json,
                    catalog_info_json,
                    prices_json,
                    categories_json,
                    platforms_json,
                    mod.preview_image_url,
                    mod.cover_image_url,
                    preview_image_json,
                    cover_image_json,
                    screenshot_images_json,
                    videos_json,
                    mod.details_url,
                    last_seen_at,
                    last_seen_at,
                    mod.published_at,
                    mod_hash,
                ),
            )


    def mark_posted(
        self,
        mod_id: str,
        post_type: str,
        post_id: str,
        posted_at: str,
        title: Optional[str] = None,
        url: Optional[str] = None,
        target: str = "reddit",
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        if post_type not in {"new", "update"}:
            raise ValueError("post_type must be 'new' or 'update'")
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO posts (mod_id, post_id, post_type, target, success, error_message, posted_at, title, url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mod_id,
                    post_id,
                    post_type,
                    target,
                    int(success),
                    error_message,
                    posted_at,
                    title,
                    url,
                ),
            )
            if post_type == "new":
                self.conn.execute(
                    "UPDATE mods SET last_posted_at = ? WHERE mod_id = ?",
                    (posted_at, mod_id),
                )
            else:
                self.conn.execute(
                    "UPDATE mods SET last_update_posted_at = ? WHERE mod_id = ?",
                    (posted_at, mod_id),
                )


class NullStore:
    def __init__(self) -> None:
        pass

    def close(self) -> None:
        return None

    def get_mod(self, mod_id: str) -> Optional[Dict[str, Any]]:
        return None

    def get_mod_model(self, mod_id: str) -> Optional[Mod]:
        return None

    def get_failed_posts(self, target: str) -> List[Dict[str, Any]]:
        return []

    def get_missing_discord_posts(self) -> List[Dict[str, Any]]:
        return []

    def get_meta(self, key: str) -> Optional[str]:
        return None

    def set_meta(self, key: str, value: str) -> None:
        return None

    def export_json(self) -> Dict[str, Any]:
        return {"mods": [], "posts": [], "meta": []}

    def import_json(self, payload: Dict[str, Any]) -> None:
        return None

    def upsert_mod(self, mod: Mod, last_seen_at: str, mod_hash: str) -> None:
        return None

    def mark_posted(
        self,
        mod_id: str,
        post_type: str,
        post_id: str,
        posted_at: str,
        title: Optional[str] = None,
        url: Optional[str] = None,
        target: str = "reddit",
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        return None


def _json_load(value: Optional[str], default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
