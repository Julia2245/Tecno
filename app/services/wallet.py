from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any, Mapping
from uuid import UUID

from app.core.wallet import WalletBalance, WalletHold, WalletMutation

if TYPE_CHECKING:
    from app.repositories.wallet import WalletRepository

_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")
_ASSET_RE = re.compile(r"^[A-Z0-9_]{2,16}$")
_BUCKET_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class WalletValidationError(ValueError):
    pass


class WalletService:
    """Validated application-facing wallet API.

    Monetary values are integer minor units only. Floats are intentionally
    rejected so callers cannot introduce binary rounding into money paths.
    """

    def __init__(self, repository: "WalletRepository") -> None:
        self.repository = repository

    async def get_balance(
        self,
        telegram_id: int,
        *,
        asset_code: str = "SYP",
        bucket: str = "cash",
    ) -> WalletBalance | None:
        telegram_id = self._positive_telegram_id(telegram_id)
        asset_code = self._asset(asset_code)
        bucket = self._bucket(bucket)
        return await self.repository.get_balance(
            telegram_id,
            asset_code=asset_code,
            bucket=bucket,
        )

    async def credit(
        self,
        telegram_id: int,
        amount: int,
        *,
        idempotency_key: str,
        reason: str,
        asset_code: str = "SYP",
        bucket: str = "cash",
        actor_telegram_id: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> WalletMutation:
        params = self._base_params(
            operation="credit",
            telegram_id=telegram_id,
            amount=amount,
            idempotency_key=idempotency_key,
            reason=reason,
            asset_code=asset_code,
            bucket=bucket,
            actor_telegram_id=actor_telegram_id,
            metadata=metadata,
        )
        return await self.repository.credit(**params)

    async def debit(
        self,
        telegram_id: int,
        amount: int,
        *,
        idempotency_key: str,
        reason: str,
        asset_code: str = "SYP",
        bucket: str = "cash",
        actor_telegram_id: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> WalletMutation:
        params = self._base_params(
            operation="debit",
            telegram_id=telegram_id,
            amount=amount,
            idempotency_key=idempotency_key,
            reason=reason,
            asset_code=asset_code,
            bucket=bucket,
            actor_telegram_id=actor_telegram_id,
            metadata=metadata,
        )
        return await self.repository.debit(**params)

    async def create_hold(
        self,
        telegram_id: int,
        amount: int,
        *,
        idempotency_key: str,
        reason: str,
        asset_code: str = "SYP",
        bucket: str = "cash",
        actor_telegram_id: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[WalletMutation, WalletHold]:
        params = self._base_params(
            operation="hold_create",
            telegram_id=telegram_id,
            amount=amount,
            idempotency_key=idempotency_key,
            reason=reason,
            asset_code=asset_code,
            bucket=bucket,
            actor_telegram_id=actor_telegram_id,
            metadata=metadata,
        )
        return await self.repository.create_hold(**params)

    async def release_hold(
        self,
        hold_id: UUID | str,
        *,
        idempotency_key: str,
        reason: str,
        actor_telegram_id: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[WalletMutation, WalletHold]:
        parsed_hold_id = self._uuid(hold_id)
        key = self._idempotency_key(idempotency_key)
        reason = self._reason(reason)
        actor = self._optional_actor(actor_telegram_id)
        clean_metadata = self._metadata(metadata)
        request_hash = self._request_hash(
            {
                "operation": "hold_release",
                "hold_id": str(parsed_hold_id),
                "reason": reason,
                "actor_telegram_id": actor,
                "metadata": clean_metadata,
            }
        )
        return await self.repository.release_hold(
            hold_id=parsed_hold_id,
            idempotency_key=key,
            request_hash=request_hash,
            reason=reason,
            actor_telegram_id=actor,
            metadata=clean_metadata,
        )

    async def capture_hold(
        self,
        hold_id: UUID | str,
        *,
        idempotency_key: str,
        reason: str,
        actor_telegram_id: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[WalletMutation, WalletHold]:
        parsed_hold_id = self._uuid(hold_id)
        key = self._idempotency_key(idempotency_key)
        reason = self._reason(reason)
        actor = self._optional_actor(actor_telegram_id)
        clean_metadata = self._metadata(metadata)
        request_hash = self._request_hash(
            {
                "operation": "hold_capture",
                "hold_id": str(parsed_hold_id),
                "reason": reason,
                "actor_telegram_id": actor,
                "metadata": clean_metadata,
            }
        )
        return await self.repository.capture_hold(
            hold_id=parsed_hold_id,
            idempotency_key=key,
            request_hash=request_hash,
            reason=reason,
            actor_telegram_id=actor,
            metadata=clean_metadata,
        )

    def _base_params(
        self,
        *,
        operation: str,
        telegram_id: int,
        amount: int,
        idempotency_key: str,
        reason: str,
        asset_code: str,
        bucket: str,
        actor_telegram_id: int | None,
        metadata: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        telegram_id = self._positive_telegram_id(telegram_id)
        amount = self._positive_amount(amount)
        key = self._idempotency_key(idempotency_key)
        reason = self._reason(reason)
        asset = self._asset(asset_code)
        clean_bucket = self._bucket(bucket)
        actor = self._optional_actor(actor_telegram_id)
        clean_metadata = self._metadata(metadata)
        request_hash = self._request_hash(
            {
                "operation": operation,
                "telegram_id": telegram_id,
                "amount": amount,
                "asset_code": asset,
                "bucket": clean_bucket,
                "reason": reason,
                "actor_telegram_id": actor,
                "metadata": clean_metadata,
            }
        )
        return {
            "telegram_id": telegram_id,
            "amount": amount,
            "asset_code": asset,
            "bucket": clean_bucket,
            "idempotency_key": key,
            "request_hash": request_hash,
            "reason": reason,
            "actor_telegram_id": actor,
            "metadata": clean_metadata,
        }

    @staticmethod
    def _positive_telegram_id(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise WalletValidationError("telegram_id must be a positive integer")
        return value

    @staticmethod
    def _positive_amount(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise WalletValidationError("amount must be a positive integer minor-unit value")
        if value > 9_000_000_000_000_000_000:
            raise WalletValidationError("amount is outside supported BIGINT safety range")
        return value

    @staticmethod
    def _idempotency_key(value: str) -> str:
        value = value.strip()
        if not _IDEMPOTENCY_RE.fullmatch(value):
            raise WalletValidationError(
                "idempotency_key must be 1-128 chars using letters, digits, :, ., _, or -"
            )
        return value

    @staticmethod
    def _reason(value: str) -> str:
        value = value.strip()
        if not value or len(value) > 256:
            raise WalletValidationError("reason must contain 1-256 characters")
        return value

    @staticmethod
    def _asset(value: str) -> str:
        value = value.strip().upper()
        if not _ASSET_RE.fullmatch(value):
            raise WalletValidationError("asset_code format is invalid")
        return value

    @staticmethod
    def _bucket(value: str) -> str:
        value = value.strip().lower()
        if not _BUCKET_RE.fullmatch(value):
            raise WalletValidationError("bucket format is invalid")
        return value

    def _optional_actor(self, value: int | None) -> int | None:
        if value is None:
            return None
        return self._positive_telegram_id(value)

    @staticmethod
    def _uuid(value: UUID | str) -> UUID:
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise WalletValidationError("hold_id is not a valid UUID") from exc

    @staticmethod
    def _metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
        clean = dict(value or {})
        try:
            encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise WalletValidationError("metadata must be JSON serializable") from exc
        if len(encoded.encode("utf-8")) > 16_384:
            raise WalletValidationError("metadata is too large")
        return clean

    @staticmethod
    def _request_hash(payload: Mapping[str, Any]) -> str:
        encoded = json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
