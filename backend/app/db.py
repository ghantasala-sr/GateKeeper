import asyncpg

from app.config import settings

pool: asyncpg.Pool | None = None


async def open_pool() -> None:
    global pool
    # The limited gatekeeper_app role, never the owner (see migrations/003_app_role.sql).
    pool = await asyncpg.create_pool(settings.app_database_url, min_size=1, max_size=10)


async def close_pool() -> None:
    if pool is not None:
        await pool.close()


def get_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError("database pool is not open")
    return pool
