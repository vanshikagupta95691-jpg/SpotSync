import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.floor import Floor
from app.models.parking_session import ParkingSession
from app.models.parking_slot import ParkingSlot
from app.models.vehicle import Vehicle
from app.repositories.ticket_repository import get_ticket_by_hash
from app.services.navigation_service import (
    NavigationDatabaseUnavailable,
    get_route_details,
)


def get_driver_navigation(db: Session, raw_token: str):
    """
    Validate a driver navigation token and return its destination.

    This function is deliberately read-only:
    - It does not lock the token row.
    - It does not update used_at or revoked_at.
    - It does not commit or flush the database session.
    """
    if not raw_token or len(raw_token) < 20 or len(raw_token) > 256:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Navigation link not found",
        )

    token_hash = hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()

    token = get_ticket_by_hash(db, token_hash)

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Navigation link not found",
        )

    now = datetime.now(timezone.utc)

    if token.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Navigation link is no longer valid",
        )

    if token.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Navigation link has already been used",
        )

    if token.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Navigation link has expired",
        )

    parking_session = db.get(
        ParkingSession,
        token.parking_session_id,
    )

    if parking_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Navigation destination not found",
        )

    if parking_session.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Parking session is no longer active",
        )

    vehicle = (
        db.get(Vehicle, parking_session.vehicle_id)
        if parking_session.vehicle_id is not None
        else None
    )

    slot = db.get(
        ParkingSlot,
        parking_session.parking_slot_id,
    )

    if (
        vehicle is None
        or slot is None
        or slot.parking_lot_id != parking_session.parking_lot_id
        or slot.floor_id is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Navigation destination not found",
        )

    floor = db.get(Floor, slot.floor_id)

    if floor is None or floor.parking_lot_id != slot.parking_lot_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Navigation destination not found",
        )

    try:
        route = get_route_details(slot.id)
    except NavigationDatabaseUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Navigation service is temporarily unavailable",
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Navigation route is not configured",
        )

    if route is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Navigation route is not configured",
        )

    # No token/session mutation, flush, commit, or consumption occurs here.
    return {
        "session_id": parking_session.id,
        "vehicle": {
            "id": vehicle.id,
            "vehicle_number": vehicle.vehicle_number,
            "vehicle_type": vehicle.vehicle_type,
        },
        "parking_slot": {
            "id": slot.id,
            "parking_lot_id": slot.parking_lot_id,
            "slot_number": slot.slot_number,
            "display_code": slot.display_code,
            "slot_type": slot.slot_type,
            "status": slot.status,
        },
        "floor": {
            "id": floor.id,
            "floor_code": floor.floor_code,
            "floor_name": floor.floor_name,
        },
        "navigation": route,
    }
