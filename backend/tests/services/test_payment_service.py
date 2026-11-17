
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import payment_service
from app.services.payment_service import create_payment_order


def mock_booking_query(db, booking):
    query = db.query.return_value
    query.filter.return_value.with_for_update.return_value.first.return_value = booking


# Existing payment-order tests

def test_create_payment_order_rejects_missing_booking():
    db = MagicMock()
    mock_booking_query(db, None)

    with pytest.raises(ValueError, match="Booking not found"):
        create_payment_order(
            db=db,
            booking_id=999,
            user_id=1,
            amount=Decimal("50.00"),
        )

    db.commit.assert_not_called()


def test_create_payment_order_rejects_wrong_owner():
    db = MagicMock()
    booking = MagicMock()
    booking.user_id = 2
    mock_booking_query(db, booking)

    with pytest.raises(ValueError, match="cannot pay for this booking"):
        create_payment_order(
            db=db,
            booking_id=1,
            user_id=1,
            amount=Decimal("50.00"),
        )

    db.commit.assert_not_called()


def test_create_payment_order_rejects_cancelled_booking():
    db = MagicMock()
    booking = MagicMock()
    booking.user_id = 1
    booking.status = "cancelled"
    mock_booking_query(db, booking)

    with pytest.raises(ValueError, match="already confirmed or cannot be paid"):
        create_payment_order(
            db=db,
            booking_id=1,
            user_id=1,
            amount=Decimal("50.00"),
        )

    db.commit.assert_not_called()


def test_create_payment_order_rejects_wrong_amount():
    db = MagicMock()
    booking = MagicMock()
    booking.user_id = 1
    booking.status = "pending"
    booking.total_amount = Decimal("100.00")
    mock_booking_query(db, booking)

    with pytest.raises(ValueError, match="amount does not match"):
        create_payment_order(
            db=db,
            booking_id=1,
            user_id=1,
            amount=Decimal("50.00"),
        )

    db.commit.assert_not_called()


def test_create_payment_order_rejects_non_inr_currency():
    db = MagicMock()
    booking = MagicMock()
    booking.user_id = 1
    booking.status = "pending"
    booking.total_amount = Decimal("50.00")
    mock_booking_query(db, booking)

    with pytest.raises(ValueError, match="Only INR"):
        create_payment_order(
            db=db,
            booking_id=1,
            user_id=1,
            amount=Decimal("50.00"),
            currency="USD",
        )

    db.commit.assert_not_called()


# New payment-verification test helpers

def make_verification_db(payment_status="created", booking_status="pending"):
    db = MagicMock()

    payment = SimpleNamespace(
        id=1,
        booking_id=10,
        user_id=5,
        amount=500.00,
        currency="INR",
        status=payment_status,
        razorpay_order_id="mock_order_123",
        razorpay_payment_id=None,
        razorpay_signature=None,
    )

    booking = SimpleNamespace(
        id=10,
        user_id=5,
        status=booking_status,
    )

    query = db.query.return_value
    query.filter.return_value.with_for_update.return_value.first.return_value = payment
    db.get.return_value = booking

    return db, payment, booking


def set_mock_payment_settings(monkeypatch):
    monkeypatch.setattr(payment_service.settings, "payment_mode", "mock")
    monkeypatch.setattr(payment_service.settings, "app_env", "development")
    monkeypatch.setattr(payment_service.settings, "allow_mock_payments", True)


def make_verification_records():
    return {
        "razorpay_order_id": "mock_order_123",
        "razorpay_payment_id": "mock_payment_123",
        "razorpay_signature": "mock_signature_123",
    }


# New payment-verification tests

def test_verify_payment_success_confirms_booking(monkeypatch):
    set_mock_payment_settings(monkeypatch)
    db, payment, booking = make_verification_db()

    result = payment_service.verify_payment(
        db=db,
        payment_id=1,
        user_id=5,
        **make_verification_records(),
    )

    assert result.status == "paid"
    assert result.razorpay_payment_id == "mock_payment_123"
    assert result.razorpay_signature == "mock_signature_123"
    assert booking.status == "confirmed"
    db.commit.assert_called_once()


def test_verify_payment_rejects_wrong_user(monkeypatch):
    set_mock_payment_settings(monkeypatch)
    db, _, _ = make_verification_db()

    with pytest.raises(ValueError, match="cannot verify"):
        payment_service.verify_payment(
            db=db,
            payment_id=1,
            user_id=99,
            **make_verification_records(),
        )


def test_verify_payment_rejects_wrong_order_id(monkeypatch):
    set_mock_payment_settings(monkeypatch)
    db, _, _ = make_verification_db()
    records = make_verification_records()
    records["razorpay_order_id"] = "mock_order_wrong"

    with pytest.raises(ValueError, match="order ID does not match"):
        payment_service.verify_payment(
            db=db,
            payment_id=1,
            user_id=5,
            **records,
        )


def test_verify_payment_rejects_missing_payment(monkeypatch):
    set_mock_payment_settings(monkeypatch)
    db, _, _ = make_verification_db()

    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = None

    with pytest.raises(ValueError, match="Payment not found"):
        payment_service.verify_payment(
            db=db,
            payment_id=1,
            user_id=5,
            **make_verification_records(),
        )


def test_verify_payment_rejects_cancelled_booking(monkeypatch):
    set_mock_payment_settings(monkeypatch)
    db, _, booking = make_verification_db()
    booking.status = "cancelled"

    with pytest.raises(ValueError, match="can no longer be confirmed"):
        payment_service.verify_payment(
            db=db,
            payment_id=1,
            user_id=5,
            **make_verification_records(),
        )


def test_verify_payment_rejects_mock_payment_in_production(monkeypatch):
    monkeypatch.setattr(payment_service.settings, "payment_mode", "mock")
    monkeypatch.setattr(payment_service.settings, "app_env", "production")
    monkeypatch.setattr(payment_service.settings, "allow_mock_payments", True)

    db, _, _ = make_verification_db()

    with pytest.raises(ValueError):
        payment_service.verify_payment(
            db=db,
            payment_id=1,
            user_id=5,
            **make_verification_records(),
        )


def test_verify_payment_is_idempotent(monkeypatch):
    set_mock_payment_settings(monkeypatch)
    db, payment, _ = make_verification_db(payment_status="paid")

    payment.razorpay_payment_id = "mock_payment_123"
    payment.razorpay_signature = "mock_signature_123"

    result = payment_service.verify_payment(
        db=db,
        payment_id=1,
        user_id=5,
        **make_verification_records(),
    )

    assert result.status == "paid"
    db.commit.assert_not_called()
