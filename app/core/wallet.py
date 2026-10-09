from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class WalletError(RuntimeError):
    pass


class InsufficientFunds(WalletError):
    pass


class IdempotencyConflict(WalletError):
    pass


class HoldNotFound(WalletError):
    pass


class HoldNotActive(WalletError):
    pass


class WalletInvariantError(WalletError):
    pass


@dataclass(slots=True, frozen=True)
class WalletBalance:
    account_id: int
    telegram_id: int
    asset_code: str
    bucket: str
    available: int
    held: int
    version: int

    @property
    def total(self) -> int:
        return self.available + self.held


@dataclass(slots=True, frozen=True)
class WalletMutation:
    operation_id: UUID
    idempotency_key: str
    duplicate: bool
    entry_type: str
    balance_after: WalletBalance


@dataclass(slots=True, frozen=True)
class WalletHold:
    id: UUID
    account_id: int
    amount: int
    status: str
    created_by_operation_id: UUID
    closed_by_operation_id: UUID | None
    created_at: datetime
    closed_at: datetime | None
