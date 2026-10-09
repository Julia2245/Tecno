import os

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/db")

from app.config import Settings


def test_super_admin_parsing() -> None:
    settings = Settings(SUPER_ADMINS="123, 456;123")
    assert settings.super_admin_ids == frozenset({123, 456})


def test_pool_bounds() -> None:
    settings = Settings(PG_POOL_MIN=2, PG_POOL_MAX=2)
    assert settings.pg_pool_min == settings.pg_pool_max == 2
