CREATE TABLE IF NOT EXISTS bot_core.wallet_accounts (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL REFERENCES bot_core.users(telegram_id) ON DELETE RESTRICT,
    asset_code TEXT NOT NULL,
    bucket TEXT NOT NULL DEFAULT 'cash',
    available BIGINT NOT NULL DEFAULT 0,
    held BIGINT NOT NULL DEFAULT 0,
    version BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT wallet_accounts_available_range CHECK (available BETWEEN 0 AND 9000000000000000000),
    CONSTRAINT wallet_accounts_held_range CHECK (held BETWEEN 0 AND 9000000000000000000),
    CONSTRAINT wallet_accounts_version_nonnegative CHECK (version >= 0),
    CONSTRAINT wallet_accounts_asset_code_format CHECK (asset_code ~ '^[A-Z0-9_]{2,16}$'),
    CONSTRAINT wallet_accounts_bucket_format CHECK (bucket ~ '^[a-z][a-z0-9_]{0,31}$'),
    CONSTRAINT wallet_accounts_identity_unique UNIQUE (telegram_id, asset_code, bucket)
);

CREATE INDEX IF NOT EXISTS idx_wallet_accounts_telegram_id
    ON bot_core.wallet_accounts (telegram_id);

CREATE TABLE IF NOT EXISTS bot_core.wallet_operations (
    id UUID PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    operation_type TEXT NOT NULL,
    request_hash CHAR(64) NOT NULL,
    actor_telegram_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT wallet_operations_idempotency_key_length CHECK (
        char_length(idempotency_key) BETWEEN 1 AND 128
    ),
    CONSTRAINT wallet_operations_type_format CHECK (
        operation_type ~ '^[a-z][a-z0-9_]{1,31}$'
    ),
    CONSTRAINT wallet_operations_request_hash_format CHECK (
        request_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT wallet_operations_actor_positive CHECK (
        actor_telegram_id IS NULL OR actor_telegram_id > 0
    )
);

CREATE INDEX IF NOT EXISTS idx_wallet_operations_created_at
    ON bot_core.wallet_operations (created_at DESC);

CREATE TABLE IF NOT EXISTS bot_core.wallet_ledger (
    id BIGSERIAL PRIMARY KEY,
    operation_id UUID NOT NULL REFERENCES bot_core.wallet_operations(id) ON DELETE RESTRICT,
    account_id BIGINT NOT NULL REFERENCES bot_core.wallet_accounts(id) ON DELETE RESTRICT,
    entry_type TEXT NOT NULL,
    available_before BIGINT NOT NULL,
    available_delta BIGINT NOT NULL,
    available_after BIGINT NOT NULL,
    held_before BIGINT NOT NULL,
    held_delta BIGINT NOT NULL,
    held_after BIGINT NOT NULL,
    version_before BIGINT NOT NULL,
    version_after BIGINT NOT NULL,
    reason TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT wallet_ledger_operation_account_unique UNIQUE (operation_id, account_id),
    CONSTRAINT wallet_ledger_entry_type_allowed CHECK (
        entry_type IN ('credit', 'debit', 'hold', 'release', 'capture')
    ),
    CONSTRAINT wallet_ledger_available_before_nonnegative CHECK (available_before >= 0),
    CONSTRAINT wallet_ledger_available_after_nonnegative CHECK (available_after >= 0),
    CONSTRAINT wallet_ledger_held_before_nonnegative CHECK (held_before >= 0),
    CONSTRAINT wallet_ledger_held_after_nonnegative CHECK (held_after >= 0),
    CONSTRAINT wallet_ledger_available_math CHECK (
        available_before + available_delta = available_after
    ),
    CONSTRAINT wallet_ledger_held_math CHECK (
        held_before + held_delta = held_after
    ),
    CONSTRAINT wallet_ledger_version_math CHECK (
        version_before >= 0 AND version_after = version_before + 1
    ),
    CONSTRAINT wallet_ledger_nonzero_change CHECK (
        available_delta <> 0 OR held_delta <> 0
    ),
    CONSTRAINT wallet_ledger_reason_length CHECK (
        char_length(reason) BETWEEN 1 AND 256
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_wallet_ledger_account_version
    ON bot_core.wallet_ledger (account_id, version_after);

CREATE INDEX IF NOT EXISTS idx_wallet_ledger_account_id_id
    ON bot_core.wallet_ledger (account_id, id);

CREATE INDEX IF NOT EXISTS idx_wallet_ledger_created_at
    ON bot_core.wallet_ledger (created_at DESC);

CREATE TABLE IF NOT EXISTS bot_core.wallet_holds (
    id UUID PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES bot_core.wallet_accounts(id) ON DELETE RESTRICT,
    amount BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_by_operation_id UUID NOT NULL UNIQUE
        REFERENCES bot_core.wallet_operations(id) ON DELETE RESTRICT,
    closed_by_operation_id UUID UNIQUE
        REFERENCES bot_core.wallet_operations(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    CONSTRAINT wallet_holds_amount_positive CHECK (amount > 0),
    CONSTRAINT wallet_holds_status_allowed CHECK (status IN ('active', 'released', 'captured')),
    CONSTRAINT wallet_holds_close_fields_consistent CHECK (
        (status = 'active' AND closed_by_operation_id IS NULL AND closed_at IS NULL)
        OR
        (status IN ('released', 'captured') AND closed_by_operation_id IS NOT NULL AND closed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_wallet_holds_active_account
    ON bot_core.wallet_holds (account_id)
    WHERE status = 'active';

-- Immutable audit records: successful wallet operations and ledger entries are append-only.
CREATE OR REPLACE FUNCTION bot_core.reject_immutable_wallet_row_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'immutable wallet audit row cannot be changed';
END;
$$;

DROP TRIGGER IF EXISTS wallet_operations_immutable ON bot_core.wallet_operations;
CREATE TRIGGER wallet_operations_immutable
BEFORE UPDATE OR DELETE ON bot_core.wallet_operations
FOR EACH ROW EXECUTE FUNCTION bot_core.reject_immutable_wallet_row_change();

DROP TRIGGER IF EXISTS wallet_ledger_immutable ON bot_core.wallet_ledger;
CREATE TRIGGER wallet_ledger_immutable
BEFORE UPDATE OR DELETE ON bot_core.wallet_ledger
FOR EACH ROW EXECUTE FUNCTION bot_core.reject_immutable_wallet_row_change();

-- A hold may only move once from active -> released/captured. Identity and amount never change.
CREATE OR REPLACE FUNCTION bot_core.guard_wallet_hold_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.id <> OLD.id
       OR NEW.account_id <> OLD.account_id
       OR NEW.amount <> OLD.amount
       OR NEW.created_by_operation_id <> OLD.created_by_operation_id
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'wallet hold identity fields are immutable';
    END IF;

    IF OLD.status <> 'active' THEN
        RAISE EXCEPTION 'closed wallet hold cannot be changed';
    END IF;

    IF NEW.status NOT IN ('released', 'captured') THEN
        RAISE EXCEPTION 'wallet hold can only close as released or captured';
    END IF;

    IF NEW.closed_by_operation_id IS NULL OR NEW.closed_at IS NULL THEN
        RAISE EXCEPTION 'closed wallet hold requires closing operation and timestamp';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS wallet_holds_transition_guard ON bot_core.wallet_holds;
CREATE TRIGGER wallet_holds_transition_guard
BEFORE UPDATE ON bot_core.wallet_holds
FOR EACH ROW EXECUTE FUNCTION bot_core.guard_wallet_hold_transition();

-- An account identity cannot be reassigned to another user/asset/bucket.
CREATE OR REPLACE FUNCTION bot_core.guard_wallet_account_identity()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.id <> OLD.id
       OR NEW.telegram_id <> OLD.telegram_id
       OR NEW.asset_code <> OLD.asset_code
       OR NEW.bucket <> OLD.bucket
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'wallet account identity fields are immutable';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS wallet_accounts_identity_guard ON bot_core.wallet_accounts;
CREATE TRIGGER wallet_accounts_identity_guard
BEFORE UPDATE ON bot_core.wallet_accounts
FOR EACH ROW EXECUTE FUNCTION bot_core.guard_wallet_account_identity();

-- Each ledger row must continue exactly from the previous immutable row.
CREATE OR REPLACE FUNCTION bot_core.guard_wallet_ledger_chain()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    previous_available BIGINT;
    previous_held BIGINT;
BEGIN
    IF NEW.version_before = 0 THEN
        IF NEW.available_before <> 0 OR NEW.held_before <> 0 THEN
            RAISE EXCEPTION 'first wallet ledger row must start from zero';
        END IF;
    ELSE
        SELECT available_after, held_after
          INTO previous_available, previous_held
          FROM bot_core.wallet_ledger
         WHERE account_id = NEW.account_id
           AND version_after = NEW.version_before;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'wallet ledger chain is missing previous version %', NEW.version_before;
        END IF;

        IF NEW.available_before <> previous_available OR NEW.held_before <> previous_held THEN
            RAISE EXCEPTION 'wallet ledger row does not continue from previous balance';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS wallet_ledger_chain_guard ON bot_core.wallet_ledger;
CREATE TRIGGER wallet_ledger_chain_guard
BEFORE INSERT ON bot_core.wallet_ledger
FOR EACH ROW EXECUTE FUNCTION bot_core.guard_wallet_ledger_chain();

-- Deferred invariants make direct balance tampering fail at COMMIT unless the ledger agrees.
CREATE OR REPLACE FUNCTION bot_core.assert_wallet_account_matches_ledger()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    target_account_id BIGINT;
    account_available BIGINT;
    account_held BIGINT;
    ledger_available BIGINT;
    ledger_held BIGINT;
    ledger_count BIGINT;
    ledger_max_version BIGINT;
    account_version BIGINT;
BEGIN
    IF TG_TABLE_NAME = 'wallet_accounts' THEN
        target_account_id := NEW.id;
    ELSE
        target_account_id := NEW.account_id;
    END IF;

    SELECT available, held, version
      INTO account_available, account_held, account_version
      FROM bot_core.wallet_accounts
     WHERE id = target_account_id;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT
        COALESCE(SUM(available_delta), 0),
        COALESCE(SUM(held_delta), 0),
        COUNT(*),
        COALESCE(MAX(version_after), 0)
      INTO ledger_available, ledger_held, ledger_count, ledger_max_version
      FROM bot_core.wallet_ledger
     WHERE account_id = target_account_id;

    IF account_available <> ledger_available
       OR account_held <> ledger_held
       OR account_version <> ledger_count
       OR account_version <> ledger_max_version THEN
        RAISE EXCEPTION
            'wallet account % does not match append-only ledger/version',
            target_account_id;
    END IF;

    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS wallet_accounts_ledger_consistency ON bot_core.wallet_accounts;
CREATE CONSTRAINT TRIGGER wallet_accounts_ledger_consistency
AFTER INSERT OR UPDATE ON bot_core.wallet_accounts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION bot_core.assert_wallet_account_matches_ledger();

DROP TRIGGER IF EXISTS wallet_ledger_account_consistency ON bot_core.wallet_ledger;
CREATE CONSTRAINT TRIGGER wallet_ledger_account_consistency
AFTER INSERT ON bot_core.wallet_ledger
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION bot_core.assert_wallet_account_matches_ledger();

-- A successful wallet operation must have exactly one matching ledger row in Phase 2.
CREATE OR REPLACE FUNCTION bot_core.assert_wallet_operation_matches_ledger()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    ledger_count BIGINT;
    ledger_type TEXT;
    expected_type TEXT;
BEGIN
    expected_type := CASE NEW.operation_type
        WHEN 'credit' THEN 'credit'
        WHEN 'debit' THEN 'debit'
        WHEN 'hold_create' THEN 'hold'
        WHEN 'hold_release' THEN 'release'
        WHEN 'hold_capture' THEN 'capture'
        ELSE NULL
    END;

    IF expected_type IS NULL THEN
        RAISE EXCEPTION 'unsupported wallet operation type %', NEW.operation_type;
    END IF;

    SELECT COUNT(*), MIN(entry_type)
      INTO ledger_count, ledger_type
      FROM bot_core.wallet_ledger
     WHERE operation_id = NEW.id;

    IF ledger_count <> 1 OR ledger_type <> expected_type THEN
        RAISE EXCEPTION
            'wallet operation % does not have exactly one matching ledger row',
            NEW.id;
    END IF;

    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS wallet_operations_ledger_consistency ON bot_core.wallet_operations;
CREATE CONSTRAINT TRIGGER wallet_operations_ledger_consistency
AFTER INSERT ON bot_core.wallet_operations
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION bot_core.assert_wallet_operation_matches_ledger();

-- Each hold must be backed by the exact immutable ledger operations that created/closed it.
CREATE OR REPLACE FUNCTION bot_core.assert_wallet_hold_matches_ledger()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    create_entry RECORD;
    close_entry RECORD;
BEGIN
    SELECT entry_type, account_id, available_delta, held_delta
      INTO create_entry
      FROM bot_core.wallet_ledger
     WHERE operation_id = NEW.created_by_operation_id
       AND account_id = NEW.account_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'wallet hold % has no creation ledger entry', NEW.id;
    END IF;

    IF create_entry.entry_type <> 'hold'
       OR create_entry.available_delta <> -NEW.amount
       OR create_entry.held_delta <> NEW.amount THEN
        RAISE EXCEPTION 'wallet hold % has invalid creation ledger entry', NEW.id;
    END IF;

    IF NEW.status IN ('released', 'captured') THEN
        SELECT entry_type, account_id, available_delta, held_delta
          INTO close_entry
          FROM bot_core.wallet_ledger
         WHERE operation_id = NEW.closed_by_operation_id
           AND account_id = NEW.account_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'wallet hold % has no closing ledger entry', NEW.id;
        END IF;

        IF close_entry.held_delta <> -NEW.amount THEN
            RAISE EXCEPTION 'wallet hold % has invalid closing held delta', NEW.id;
        END IF;

        IF NEW.status = 'released'
           AND (close_entry.entry_type <> 'release' OR close_entry.available_delta <> NEW.amount) THEN
            RAISE EXCEPTION 'released wallet hold % has invalid closing ledger entry', NEW.id;
        END IF;

        IF NEW.status = 'captured'
           AND (close_entry.entry_type <> 'capture' OR close_entry.available_delta <> 0) THEN
            RAISE EXCEPTION 'captured wallet hold % has invalid closing ledger entry', NEW.id;
        END IF;
    END IF;

    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS wallet_holds_ledger_consistency ON bot_core.wallet_holds;
CREATE CONSTRAINT TRIGGER wallet_holds_ledger_consistency
AFTER INSERT OR UPDATE ON bot_core.wallet_holds
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION bot_core.assert_wallet_hold_matches_ledger();

-- Every held unit must belong to one active hold; no anonymous held balance is allowed.
CREATE OR REPLACE FUNCTION bot_core.assert_wallet_account_matches_holds()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    target_account_id BIGINT;
    account_held BIGINT;
    active_holds BIGINT;
BEGIN
    IF TG_TABLE_NAME = 'wallet_accounts' THEN
        target_account_id := NEW.id;
    ELSE
        target_account_id := NEW.account_id;
    END IF;

    SELECT held
      INTO account_held
      FROM bot_core.wallet_accounts
     WHERE id = target_account_id;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT COALESCE(SUM(amount), 0)
      INTO active_holds
      FROM bot_core.wallet_holds
     WHERE account_id = target_account_id
       AND status = 'active';

    IF account_held <> active_holds THEN
        RAISE EXCEPTION
            'wallet account % held amount does not match active holds: account=%, holds=%',
            target_account_id,
            account_held,
            active_holds;
    END IF;

    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS wallet_accounts_holds_consistency ON bot_core.wallet_accounts;
CREATE CONSTRAINT TRIGGER wallet_accounts_holds_consistency
AFTER INSERT OR UPDATE ON bot_core.wallet_accounts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION bot_core.assert_wallet_account_matches_holds();

DROP TRIGGER IF EXISTS wallet_holds_account_consistency ON bot_core.wallet_holds;
CREATE CONSTRAINT TRIGGER wallet_holds_account_consistency
AFTER INSERT OR UPDATE ON bot_core.wallet_holds
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION bot_core.assert_wallet_account_matches_holds();
