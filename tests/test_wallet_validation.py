from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.wallet import WalletService, WalletValidationError


class DummyRepository:
    pass


@pytest.fixture
def service() -> WalletService:
    return WalletService(DummyRepository())  # type: ignore[arg-type]


def test_amount_rejects_float_zero_negative_and_bool(service: WalletService) -> None:
    for value in (1.5, 0, -1, True):
        with pytest.raises(WalletValidationError):
            service._positive_amount(value)  # type: ignore[arg-type]


def test_amount_accepts_integer_minor_units(service: WalletService) -> None:
    assert service._positive_amount(25_000) == 25_000


def test_asset_and_bucket_are_normalized(service: WalletService) -> None:
    assert service._asset("syp") == "SYP"
    assert service._bucket("Cash") == "cash"


def test_idempotency_key_is_strict(service: WalletService) -> None:
    assert service._idempotency_key("withdraw:123:claim") == "withdraw:123:claim"
    with pytest.raises(WalletValidationError):
        service._idempotency_key("contains space")


def test_request_hash_is_stable(service: WalletService) -> None:
    a = service._request_hash({"b": 2, "a": 1})
    b = service._request_hash({"a": 1, "b": 2})
    assert a == b
    assert len(a) == 64


def test_uuid_validation(service: WalletService) -> None:
    value = uuid4()
    assert service._uuid(str(value)) == value
    with pytest.raises(WalletValidationError):
        service._uuid("not-a-uuid")


def test_metadata_must_be_json_serializable(service: WalletService) -> None:
    with pytest.raises(WalletValidationError):
        service._metadata({"bad": object()})
