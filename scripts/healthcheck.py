from __future__ import annotations

import asyncio

from app.config import get_settings
from app.core.db import Database


async def main() -> None:
    settings = get_settings()
    db = Database(
        settings.database_url,
        min_size=1,
        max_size=1,
        command_timeout=min(settings.pg_command_timeout, 5.0),
    )
    await db.connect()
    try:
        if not await db.ping():
            raise SystemExit(1)
        print("OK")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
