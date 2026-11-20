import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models.floor import Floor
from app.models.parking_session import ParkingSession
from app.models.parking_slot import ParkingSlot
from app.models.vehicle import Vehicle
from app.services import driver_navigation_service as service


RAW_TOKEN = "sample-secure-navigation-token-123456"


def make_records(
    *,
    revoked_at=None,
    used_at=None,
    expires_at=None,
    session_status="ACTIVE",
):
    token = SimpleNamespace(
        parking_session_id=10,
        revoked_at=revoked_at,
        used_at=used_at,
        expires_at=expires_at or (
            datetime.now(timezone.utc) + timedelta(minutes=5)
        ),
    )

    session = SimpleNamespace(
        id=10,
        status=session_status,
        parking_lot_id=20,
        parking_slot_id=30,
        vehicle_id=40,
    )

    vehicle = SimpleNamespace(
        id=40,
        vehicle_number="UP32AB1234",
        vehicle_type="CAR",
    )

    slot = SimpleNamespace(
        id=30,
        parking_lot_id=20,
        floor_id=50,
        slot_number="A-12",
        display_code="A12",
        slot_type="STANDARD",
        status="OCCUPIED",
    )

    floor = SimpleNamespace(
        id=50,
        parking_lot_id=20,
        floor_code="G",
        floor_name="Ground Floor",
    )

    records = {
        (ParkingSession, 10): session,
        (Vehicle, 40): vehicle,
        (ParkingSlot, 30): slot,
        (Floor, 50): floor,
    }

    db = MagicMock()
    db.get.side_effect = lambda model, record_id: records.get(
        (model, record_id)
    )

    return db, token


def mock_token_lookup(monkeypatch, token):
    expected_hash = hashlib.sha256(RAW_TOKEN.encode("utf-8")).hexdigest()

    def lookup(db, token_hash):
        assert token_hash == expected_hash
        return token

    monkeypatch.setattr(service, "get_ticket_by_hash", lookup)


def test_driver_navigation_success_is_read_only(monkeypatch):
    db, token = make_records()
    mock_token_lookup(monkeypatch, token)

    route = {
        "route": ["ENTRANCE_MAIN", "A-12"],
        "distance_m": 25,
        "travel_time_s": 30,
        "route_data_status": "SIMULATED_DEMO",
        "topology_status": "UNVERIFIED_PLACEHOLDER",
    }
    monkeypatch.setattr(service, "get_route_details", lambda slot_id: route)

    result = service.get_driver_navigation(db, RAW_TOKEN)

    assert result["session_id"] == 10
    assert result["vehicle"]["vehicle_number"] == "UP32AB1234"
    assert result["parking_slot"]["slot_number"] == "A-12"
    assert result["floor"]["floor_name"] == "Ground Floor"
    assert result["navigation"] == route

    # Public navigation must never consume or revoke the token.
    assert token.used_at is None
    assert token.revoked_at is None
    db.commit.assert_not_called()
    db.flush.assert_not_called()


def test_unknown_token_returns_404_without_exposing_data(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(
        service, "get_ticket_by_hash", lambda *args: None
    )

    with pytest.raises(HTTPException) as exc:
        service.get_driver_navigation(db, RAW_TOKEN)

    assert exc.value.status_code == 404
    db.get.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value", "expected_status"),
    [
        ("revoked_at", datetime.now(timezone.utc), 409),
        ("used_at", datetime.now(timezone.utc), 409),
        (
            "expires_at",
            datetime.now(timezone.utc) - timedelta(minutes=1),
            410,
        ),
    ],
)
def test_unusable_token_is_rejected(
    monkeypatch, field, value, expected_status
):
    db, token = make_records()
    setattr(token, field, value)
    mock_token_lookup(monkeypatch, token)

    with pytest.raises(HTTPException) as exc:
        service.get_driver_navigation(db, RAW_TOKEN)

    assert exc.value.status_code == expected_status
    db.get.assert_not_called()
    db.commit.assert_not_called()
    db.flush.assert_not_called()


def test_completed_session_is_rejected(monkeypatch):
    db, token = make_records(session_status="COMPLETED")
    mock_token_lookup(monkeypatch, token)

    with pytest.raises(HTTPException) as exc:
        service.get_driver_navigation(db, RAW_TOKEN)

    assert exc.value.status_code == 409
    db.commit.assert_not_called()
    db.flush.assert_not_called()


def test_missing_session_returns_404(monkeypatch):
    db, token = make_records()
    db.get.side_effect = lambda model, record_id: None
    mock_token_lookup(monkeypatch, token)

    with pytest.raises(HTTPException) as exc:
        service.get_driver_navigation(db, RAW_TOKEN)

    assert exc.value.status_code == 404
    db.commit.assert_not_called()


def test_missing_destination_returns_404(monkeypatch):
    db, token = make_records()
    db.get.side_effect = lambda model, record_id: (
        SimpleNamespace(
            id=10,
            status="ACTIVE",
            parking_lot_id=20,
            parking_slot_id=30,
            vehicle_id=40,
        )
        if model is ParkingSession
        else None
    )
    mock_token_lookup(monkeypatch, token)

    with pytest.raises(HTTPException) as exc:
        service.get_driver_navigation(db, RAW_TOKEN)

    assert exc.value.status_code == 404
    db.commit.assert_not_called()


def test_unavailable_navigation_service_returns_503(monkeypatch):
    from app.services.navigation_service import NavigationDatabaseUnavailable

    db, token = make_records()
    mock_token_lookup(monkeypatch, token)

    def unavailable(slot_id):
        raise NavigationDatabaseUnavailable("Unavailable")

    monkeypatch.setattr(service, "get_route_details", unavailable)

    with pytest.raises(HTTPException) as exc:
        service.get_driver_navigation(db, RAW_TOKEN)

    assert exc.value.status_code == 503
    assert token.used_at is None
    assert token.revoked_at is None
    db.commit.assert_not_called()
    db.flush.assert_not_called()
