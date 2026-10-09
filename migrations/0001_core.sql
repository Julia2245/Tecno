CREATE SCHEMA IF NOT EXISTS bot_core;

CREATE TABLE IF NOT EXISTS bot_core.users (
    telegram_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT NOT NULL DEFAULT '',
    last_name TEXT,
    language_code TEXT,
    is_bot BOOLEAN NOT NULL DEFAULT FALSE,
    is_blocked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT users_telegram_id_positive CHECK (telegram_id > 0)
);

CREATE INDEX IF NOT EXISTS idx_users_username_lower
    ON bot_core.users ((LOWER(username)))
    WHERE username IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_users_created_at
    ON bot_core.users (created_at DESC);
