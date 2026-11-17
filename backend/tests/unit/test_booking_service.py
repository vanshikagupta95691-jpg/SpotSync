
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException


from app.services import booking_service


def future_range():
    start = datetime.now(timezone.utc) + timedelta(days=1)
    return start, start + timedelta(hours=2)


def test_booking_rejects_vehicle_owned_by_another_user():
    db = MagicMock()
    db.get.return_value = SimpleNamespace(user_id=2)
    start, end = future_range()

    with pytest.raises(HTTPException) as exc:
        booking_service.create_user_booking(
            db, user_id=1, vehicle_id=10,
            parking_slot_id=20, start_time=start, end_time=end
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Vehicle not found"
    db.commit.assert_not_called()


def test_booking_rejects_past_start_time():
    db = MagicMock()
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    end = start + timedelta(hours=2)

    with pytest.raises(HTTPException) as exc:
        booking_service.create_user_booking(
            db, user_id=1, vehicle_id=10,
            parking_slot_id=20, start_time=start, end_time=end
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Booking cannot start in the past"
    db.get.assert_not_called()


def test_booking_rejects_unavailable_slot():
    db = MagicMock()
    db.get.side_effect = [
        SimpleNamespace(user_id=1),
        SimpleNamespace(is_available=False),
    ]
    start, end = future_range()

    with pytest.raises(HTTPException) as exc:
        booking_service.create_user_booking(
            db, user_id=1, vehicle_id=10,
            parking_slot_id=20, start_time=start, end_time=end
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Parking slot is not available"
    db.commit.assert_not_called()


def test_booking_rejects_overlapping_reservation(monkeypatch):
    db = MagicMock()
    vehicle = SimpleNamespace(user_id=1)
    slot = SimpleNamespace(is_available=True, parking_lot_id=30)

    db.get.side_effect = [vehicle, slot]

    monkeypatch.setattr(
        booking_service,
        "get_parking_lot_by_id",
        lambda *args: SimpleNamespace(id=30),
    )
    monkeypatch.setattr(
        booking_service,
        "get_overlapping_booking",
        lambda *args: SimpleNamespace(id=99),
    )

    start, end = future_range()

    with pytest.raises(HTTPException) as exc:
        booking_service.create_user_booking(
            db, user_id=1, vehicle_id=10,
            parking_slot_id=20, start_time=start, end_time=end
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Parking slot is already booked for this time"
    db.commit.assert_not_called()


def test_user_cannot_access_another_users_booking(monkeypatch):
    booking = SimpleNamespace(id=99, user_id=2)

    monkeypatch.setattr(
        booking_service,
        "get_booking_by_id",
        lambda db, booking_id: booking,
    )

    with pytest.raises(HTTPException) as exc:
        booking_service.get_booking_for_user(
            db=MagicMock(), booking_id=99, user_id=1
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Booking not found"
