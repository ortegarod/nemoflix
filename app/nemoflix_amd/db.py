from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg

from .config import get_settings

_pool: asyncpg.Pool | None = None
_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized")
    return _pool


async def init_db() -> asyncpg.Pool:
    global _pool
    settings = get_settings()
    _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
    await run_migrations()
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def run_migrations() -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            version = path.stem
            exists = await conn.fetchval("SELECT 1 FROM schema_migrations WHERE version=$1", version)
            if exists:
                continue
            sql = path.read_text()
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute("INSERT INTO schema_migrations(version) VALUES($1)", version)


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value)


def _job_row(row: asyncpg.Record) -> dict[str, Any]:
    data = dict(row)
    metadata = data.get("metadata")
    if isinstance(metadata, str):
        with contextlib.suppress(json.JSONDecodeError):
            metadata = json.loads(metadata)
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            data.setdefault(key, value)
    return data


async def save_job(
    *,
    prompt_id: str,
    job_type: str,
    status: str = "pending",
    prompt: str | None = None,
    width: int | None = None,
    height: int | None = None,
    workflow_json: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO jobs (prompt_id, job_type, status, prompt, width, height, workflow_json, metadata, error, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9,NOW())
            ON CONFLICT (prompt_id) DO UPDATE SET
                job_type=EXCLUDED.job_type,
                status=EXCLUDED.status,
                prompt=COALESCE(EXCLUDED.prompt, jobs.prompt),
                width=COALESCE(EXCLUDED.width, jobs.width),
                height=COALESCE(EXCLUDED.height, jobs.height),
                workflow_json=COALESCE(EXCLUDED.workflow_json, jobs.workflow_json),
                metadata=COALESCE(EXCLUDED.metadata, jobs.metadata),
                error=EXCLUDED.error,
                updated_at=NOW()
            """,
            prompt_id,
            job_type,
            status,
            prompt,
            width,
            height,
            _json(workflow_json),
            _json(metadata),
            error,
        )


async def update_job_status(prompt_id: str, status: str, *, error: str | None = None, output_filename: str | None = None) -> None:
    completed = status in {"completed", "failed"}
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE jobs
            SET status=$2,
                error=$3,
                output_filename=COALESCE($4, output_filename),
                updated_at=NOW(),
                completed_at=CASE WHEN $5 THEN NOW() ELSE completed_at END
            WHERE prompt_id=$1
            """,
            prompt_id,
            status,
            error,
            output_filename,
            completed,
        )


async def update_job_metadata(prompt_id: str, metadata: dict[str, Any]) -> None:
    if not metadata:
        return
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE jobs
            SET metadata=COALESCE(jobs.metadata, '{}'::jsonb) || $2::jsonb,
                updated_at=NOW()
            WHERE prompt_id=$1
            """,
            prompt_id,
            _json(metadata),
        )


async def get_job(prompt_id: str) -> dict[str, Any] | None:
    row = await get_pool().fetchrow("SELECT * FROM jobs WHERE prompt_id=$1", prompt_id)
    return _job_row(row) if row else None


# -- training_jobs ---------------------------------------------------------------

def _training_job_row(row: asyncpg.Record) -> dict[str, Any]:
    data = dict(row)
    if isinstance(data.get("metadata"), str):
        with contextlib.suppress(json.JSONDecodeError):
            data["metadata"] = json.loads(data["metadata"])
    return data


async def get_training_job(job_name: str) -> dict[str, Any] | None:
    row = await get_pool().fetchrow("SELECT * FROM training_jobs WHERE job_name=$1", job_name)
    return _training_job_row(row) if row else None


async def get_latest_training_job() -> dict[str, Any] | None:
    row = await get_pool().fetchrow("SELECT * FROM training_jobs ORDER BY created_at DESC LIMIT 1")
    return _training_job_row(row) if row else None


async def list_training_jobs() -> list[dict[str, Any]]:
    rows = await get_pool().fetch("SELECT * FROM training_jobs ORDER BY created_at DESC")
    return [_training_job_row(row) for row in rows]


async def list_datasets() -> list[dict[str, Any]]:
    rows = await get_pool().fetch("SELECT * FROM datasets ORDER BY created_at")
    return [dict(row) for row in rows]


async def upsert_dataset(id: str, name: str, description: str | None = None, image_count: int | None = None) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO datasets (id, name, description, image_count)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id) DO UPDATE SET
                name        = EXCLUDED.name,
                description = COALESCE(EXCLUDED.description, datasets.description),
                image_count = COALESCE(EXCLUDED.image_count, datasets.image_count)
            RETURNING *
            """,
            id, name, description, image_count,
        )
    return dict(row)


async def save_training_job(
    job_name: str,
    *,
    status: str = "configured",
    config_path: str | None = None,
    log_path: str | None = None,
    output_dir: str | None = None,
    dataset: str | None = None,
    trigger_word: str | None = None,
    model: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO training_jobs (job_name, status, config_path, log_path, output_dir,
                                       dataset, trigger_word, model, metadata, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,NOW())
            ON CONFLICT (job_name) DO UPDATE SET
                status      = EXCLUDED.status,
                config_path = COALESCE(EXCLUDED.config_path, training_jobs.config_path),
                log_path    = COALESCE(EXCLUDED.log_path, training_jobs.log_path),
                output_dir  = COALESCE(EXCLUDED.output_dir, training_jobs.output_dir),
                dataset     = COALESCE(EXCLUDED.dataset, training_jobs.dataset),
                trigger_word= COALESCE(EXCLUDED.trigger_word, training_jobs.trigger_word),
                model       = COALESCE(EXCLUDED.model, training_jobs.model),
                metadata    = COALESCE(training_jobs.metadata, '{}'::jsonb) || COALESCE(EXCLUDED.metadata, '{}'::jsonb),
                updated_at  = NOW()
            """,
            job_name, status, config_path, log_path, output_dir,
            dataset, trigger_word, model, _json(metadata),
        )


async def update_training_job_status(
    job_name: str,
    status: str,
    *,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    completed = status in {"completed", "failed"}
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE training_jobs
            SET status       = $2,
                error        = $3,
                metadata     = COALESCE(training_jobs.metadata, '{}'::jsonb) || COALESCE($4::jsonb, '{}'::jsonb),
                updated_at   = NOW(),
                completed_at = CASE WHEN $5 THEN NOW() ELSE training_jobs.completed_at END
            WHERE job_name   = $1
            """,
            job_name, status, error, _json(metadata), completed,
        )


def _character_row(row: asyncpg.Record) -> dict[str, Any]:
    data = dict(row)
    for key in ("source_images", "loras", "defaults", "metadata"):
        value = data.get(key)
        if isinstance(value, str):
            with contextlib.suppress(json.JSONDecodeError):
                data[key] = json.loads(value)
    return data


async def list_characters() -> list[dict[str, Any]]:
    rows = await get_pool().fetch("SELECT * FROM characters ORDER BY updated_at DESC")
    return [_character_row(row) for row in rows]


async def get_character(character_id: str) -> dict[str, Any] | None:
    row = await get_pool().fetchrow("SELECT * FROM characters WHERE id=$1", character_id)
    return _character_row(row) if row else None


async def upsert_character(character: dict[str, Any]) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO characters (id, name, trigger, description, source_images, loras, defaults, metadata, updated_at)
            VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8::jsonb,NOW())
            ON CONFLICT (id) DO UPDATE SET
                name=EXCLUDED.name,
                trigger=EXCLUDED.trigger,
                description=EXCLUDED.description,
                source_images=EXCLUDED.source_images,
                loras=EXCLUDED.loras,
                defaults=EXCLUDED.defaults,
                metadata=EXCLUDED.metadata,
                updated_at=NOW()
            RETURNING *
            """,
            character["id"],
            character["name"],
            character.get("trigger"),
            character.get("description"),
            _json(character.get("source_images", [])),
            _json(character.get("loras", [])),
            _json(character.get("defaults", {})),
            _json(character.get("metadata", {})),
        )
    return _character_row(row)


async def delete_character(character_id: str) -> bool:
    result = await get_pool().execute("DELETE FROM characters WHERE id=$1", character_id)
    return not result.endswith(" 0")


def _json_row(row: asyncpg.Record, keys: tuple[str, ...]) -> dict[str, Any]:
    data = dict(row)
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            with contextlib.suppress(json.JSONDecodeError):
                data[key] = json.loads(value)
    return data


def _project_row(row: asyncpg.Record) -> dict[str, Any]:
    return _json_row(row, ("characters", "metadata"))


def _scene_row(row: asyncpg.Record) -> dict[str, Any]:
    return _json_row(row, ("characters", "metadata"))


def _shot_row(row: asyncpg.Record) -> dict[str, Any]:
    return _json_row(row, ("characters", "metadata"))


def _shot_version_row(row: asyncpg.Record) -> dict[str, Any]:
    return _json_row(row, ("metadata",))


async def list_projects(limit: int = 100) -> list[dict[str, Any]]:
    rows = await get_pool().fetch("SELECT * FROM projects ORDER BY updated_at DESC LIMIT $1", limit)
    return [_project_row(row) for row in rows]


async def get_project(project_id: str) -> dict[str, Any] | None:
    row = await get_pool().fetchrow("SELECT * FROM projects WHERE id=$1", project_id)
    return _project_row(row) if row else None


async def upsert_project(project: dict[str, Any]) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO projects (id, title, description, aspect_ratio, duration_seconds, status, characters, metadata, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,NOW())
            ON CONFLICT (id) DO UPDATE SET
                title=EXCLUDED.title,
                description=EXCLUDED.description,
                aspect_ratio=EXCLUDED.aspect_ratio,
                duration_seconds=EXCLUDED.duration_seconds,
                status=EXCLUDED.status,
                characters=EXCLUDED.characters,
                metadata=EXCLUDED.metadata,
                updated_at=NOW()
            RETURNING *
            """,
            project["id"],
            project["title"],
            project.get("description"),
            project.get("aspect_ratio", "9:16"),
            project.get("duration_seconds"),
            project.get("status", "draft"),
            _json(project.get("characters", [])),
            _json(project.get("metadata", {})),
        )
    return _project_row(row)


async def delete_project(project_id: str) -> bool:
    result = await get_pool().execute("DELETE FROM projects WHERE id=$1", project_id)
    return not result.endswith(" 0")


async def delete_project_scene(project_id: str, scene_id: str) -> bool:
    result = await get_pool().execute("DELETE FROM project_scenes WHERE project_id=$1 AND id=$2", project_id, scene_id)
    return not result.endswith(" 0")


async def delete_project_shot(project_id: str, scene_id: str, shot_id: str) -> bool:
    result = await get_pool().execute("DELETE FROM project_shots WHERE project_id=$1 AND scene_id=$2 AND id=$3", project_id, scene_id, shot_id)
    return not result.endswith(" 0")


async def list_project_scenes(project_id: str) -> list[dict[str, Any]]:
    rows = await get_pool().fetch("SELECT * FROM project_scenes WHERE project_id=$1 ORDER BY scene_number", project_id)
    return [_scene_row(row) for row in rows]


async def get_project_scene(project_id: str, scene_id: str) -> dict[str, Any] | None:
    row = await get_pool().fetchrow("SELECT * FROM project_scenes WHERE project_id=$1 AND id=$2", project_id, scene_id)
    return _scene_row(row) if row else None


async def upsert_project_scene(scene: dict[str, Any]) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO project_scenes (id, project_id, scene_number, title, setting, weather, summary, location, time_of_day, characters, metadata, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb,NOW())
            ON CONFLICT (id) DO UPDATE SET
                scene_number=EXCLUDED.scene_number,
                title=EXCLUDED.title,
                setting=EXCLUDED.setting,
                weather=EXCLUDED.weather,
                summary=EXCLUDED.summary,
                location=EXCLUDED.location,
                time_of_day=EXCLUDED.time_of_day,
                characters=EXCLUDED.characters,
                metadata=EXCLUDED.metadata,
                updated_at=NOW()
            RETURNING *
            """,
            scene["id"],
            scene["project_id"],
            scene["scene_number"],
            scene.get("title"),
            scene.get("setting"),
            scene.get("weather"),
            scene.get("summary"),
            scene.get("location"),
            scene.get("time_of_day"),
            _json(scene.get("characters", [])),
            _json(scene.get("metadata", {})),
        )
    return _scene_row(row)


async def list_project_shots(project_id: str, scene_id: str | None = None) -> list[dict[str, Any]]:
    if scene_id:
        rows = await get_pool().fetch("SELECT * FROM project_shots WHERE project_id=$1 AND scene_id=$2 ORDER BY shot_number", project_id, scene_id)
    else:
        rows = await get_pool().fetch("SELECT * FROM project_shots WHERE project_id=$1 ORDER BY scene_id, shot_number", project_id)
    return [_shot_row(row) for row in rows]


async def get_project_shot(project_id: str, scene_id: str, shot_id: str) -> dict[str, Any] | None:
    row = await get_pool().fetchrow("SELECT * FROM project_shots WHERE project_id=$1 AND scene_id=$2 AND id=$3", project_id, scene_id, shot_id)
    return _shot_row(row) if row else None


async def next_shot_version_number(shot_id: str, kind: str) -> int:
    value = await get_pool().fetchval("SELECT COALESCE(MAX(version_number), 0) + 1 FROM project_shot_versions WHERE shot_id=$1 AND kind=$2", shot_id, kind)
    return int(value or 1)


async def list_project_shot_versions(project_id: str, scene_id: str, shot_id: str) -> list[dict[str, Any]]:
    rows = await get_pool().fetch(
        """
        SELECT * FROM project_shot_versions
        WHERE project_id=$1 AND scene_id=$2 AND shot_id=$3
        ORDER BY kind, version_number DESC
        """,
        project_id,
        scene_id,
        shot_id,
    )
    return [_shot_version_row(row) for row in rows]


async def get_project_shot_version(project_id: str, scene_id: str, shot_id: str, version_id: str) -> dict[str, Any] | None:
    row = await get_pool().fetchrow(
        "SELECT * FROM project_shot_versions WHERE project_id=$1 AND scene_id=$2 AND shot_id=$3 AND id=$4",
        project_id,
        scene_id,
        shot_id,
        version_id,
    )
    return _shot_version_row(row) if row else None


async def get_project_shot_version_by_prompt(prompt_id: str) -> dict[str, Any] | None:
    row = await get_pool().fetchrow("SELECT * FROM project_shot_versions WHERE prompt_id=$1", prompt_id)
    return _shot_version_row(row) if row else None


async def upsert_project_shot_version(version: dict[str, Any]) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO project_shot_versions (id, project_id, scene_id, shot_id, version_number, kind, status, prompt, file, prompt_id, metadata, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,NOW())
            ON CONFLICT (id) DO UPDATE SET
                status=EXCLUDED.status,
                prompt=COALESCE(EXCLUDED.prompt, project_shot_versions.prompt),
                file=COALESCE(EXCLUDED.file, project_shot_versions.file),
                prompt_id=COALESCE(EXCLUDED.prompt_id, project_shot_versions.prompt_id),
                metadata=COALESCE(project_shot_versions.metadata, '{}'::jsonb) || EXCLUDED.metadata,
                updated_at=NOW()
            RETURNING *
            """,
            version["id"],
            version["project_id"],
            version["scene_id"],
            version["shot_id"],
            version["version_number"],
            version["kind"],
            version.get("status", "pending"),
            version.get("prompt"),
            version.get("file"),
            version.get("prompt_id"),
            _json(version.get("metadata", {})),
        )
    return _shot_version_row(row)


async def upsert_project_shot(shot: dict[str, Any]) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO project_shots (
                id, project_id, scene_id, shot_number, text, description, subtitle, voiceover, image_prompt, motion_prompt,
                camera_motion, characters, duration_seconds, status, image_file, video_file,
                image_prompt_id, video_prompt_id, metadata, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13,$14,$15,$16,$17,$18,$19::jsonb,NOW())
            ON CONFLICT (id) DO UPDATE SET
                shot_number=EXCLUDED.shot_number,
                text=EXCLUDED.text,
                description=EXCLUDED.description,
                subtitle=EXCLUDED.subtitle,
                voiceover=EXCLUDED.voiceover,
                image_prompt=EXCLUDED.image_prompt,
                motion_prompt=EXCLUDED.motion_prompt,
                camera_motion=EXCLUDED.camera_motion,
                characters=EXCLUDED.characters,
                duration_seconds=EXCLUDED.duration_seconds,
                status=EXCLUDED.status,
                image_file=EXCLUDED.image_file,
                video_file=EXCLUDED.video_file,
                image_prompt_id=EXCLUDED.image_prompt_id,
                video_prompt_id=EXCLUDED.video_prompt_id,
                metadata=EXCLUDED.metadata,
                updated_at=NOW()
            RETURNING *
            """,
            shot["id"],
            shot["project_id"],
            shot["scene_id"],
            shot["shot_number"],
            shot.get("text"),
            shot.get("description"),
            shot.get("subtitle"),
            shot.get("voiceover"),
            shot.get("image_prompt"),
            shot.get("motion_prompt"),
            shot.get("camera_motion"),
            _json(shot.get("characters", [])),
            shot.get("duration_seconds", 5),
            shot.get("status", "draft"),
            shot.get("image_file"),
            shot.get("video_file"),
            shot.get("image_prompt_id"),
            shot.get("video_prompt_id"),
            _json(shot.get("metadata", {})),
        )
    return _shot_row(row)


async def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    rows = await get_pool().fetch("SELECT * FROM jobs ORDER BY updated_at DESC LIMIT $1", limit)
    return [_job_row(row) for row in rows]


async def upsert_media(row: dict[str, Any]) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO media (
                filename, type, width, height, size, modified,
                prompt, seed, steps, guidance, sampler,
                model, vae, text_encoder, loras, workflow_type, prompt_id,
                source_image, video_file, updated_at
            ) VALUES (
                $1,$2,$3,$4,$5,$6,
                $7,$8,$9,$10,$11,
                $12,$13,$14,$15::jsonb,$16,$17,
                $18,$19,NOW()
            )
            ON CONFLICT (filename) DO UPDATE SET
                type=EXCLUDED.type,
                width=EXCLUDED.width,
                height=EXCLUDED.height,
                size=EXCLUDED.size,
                modified=EXCLUDED.modified,
                prompt=COALESCE(EXCLUDED.prompt, media.prompt),
                seed=COALESCE(EXCLUDED.seed, media.seed),
                steps=COALESCE(EXCLUDED.steps, media.steps),
                guidance=COALESCE(EXCLUDED.guidance, media.guidance),
                sampler=COALESCE(EXCLUDED.sampler, media.sampler),
                model=COALESCE(EXCLUDED.model, media.model),
                vae=COALESCE(EXCLUDED.vae, media.vae),
                text_encoder=COALESCE(EXCLUDED.text_encoder, media.text_encoder),
                loras=COALESCE(EXCLUDED.loras, media.loras),
                workflow_type=COALESCE(EXCLUDED.workflow_type, media.workflow_type),
                prompt_id=COALESCE(EXCLUDED.prompt_id, media.prompt_id),
                source_image=COALESCE(EXCLUDED.source_image, media.source_image),
                video_file=COALESCE(EXCLUDED.video_file, media.video_file),
                updated_at=NOW()
            """,
            row.get("filename"),
            row.get("type", "image"),
            row.get("width"),
            row.get("height"),
            row.get("size"),
            row.get("modified"),
            row.get("prompt"),
            row.get("seed"),
            row.get("steps"),
            row.get("guidance"),
            row.get("sampler"),
            row.get("model"),
            row.get("vae"),
            row.get("text_encoder"),
            _json(row.get("loras")),
            row.get("workflow_type"),
            row.get("prompt_id"),
            row.get("source_image"),
            row.get("video_file"),
        )


async def list_media(limit: int = 60, offset: int = 0) -> list[dict[str, Any]]:
    rows = await get_pool().fetch(
        """
        SELECT * FROM media
        ORDER BY COALESCE(modified, created_at) DESC, filename DESC
        LIMIT $1 OFFSET $2
        """,
        limit,
        offset,
    )
    return [dict(row) for row in rows]


async def media_count() -> int:
    return int(await get_pool().fetchval("SELECT COUNT(*) FROM media") or 0)


async def delete_media_rows(files: list[str]) -> None:
    if not files:
        return
    await get_pool().execute("DELETE FROM media WHERE filename = ANY($1::text[])", files)


def utc_from_timestamp(value: float) -> datetime:
    return datetime.fromtimestamp(value, UTC)
