from fastapi import APIRouter, HTTPException, Query

from app.services.navigation_service import (
    NavigationDatabaseUnavailable,
    get_graph_health,
    get_multiple_route_costs,
    get_route_details,
)


router = APIRouter(prefix="/navigation", tags=["Navigation"])


def _database_error():
    raise HTTPException(
        status_code=503,
        detail="Navigation graph database is unavailable",
    )


@router.get("/graph/health")
def navigation_graph_health():
    try:
        return {
            "status": "connected",
            "graph": get_graph_health(),
        }
    except NavigationDatabaseUnavailable:
        _database_error()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Could not read navigation graph health",
        )


@router.get("/routes")
def compare_navigation_routes(
    slots: str = Query(..., description="Comma-separated PostgreSQL parking slot IDs")
):
    try:
        slot_ids = [int(value.strip()) for value in slots.split(",") if value.strip()]
        if not slot_ids or any(value <= 0 for value in slot_ids):
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="slots must contain comma-separated positive integers",
        )

    try:
        return {
            "routes": get_multiple_route_costs(slot_ids),
            "note": "Routes use simulated demo distances and times; topology and accessibility are unverified placeholders.",
        }
    except NavigationDatabaseUnavailable:
        _database_error()


@router.get("/{slot_id}")
def navigate_to_parking_slot(slot_id: int):
    if slot_id <= 0:
        raise HTTPException(status_code=422, detail="slot_id must be positive")

    try:
        details = get_route_details(slot_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except NavigationDatabaseUnavailable:
        _database_error()

    if details is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No configured navigation route exists for this parking slot. "
                "Real weighted PATH relationships are required."
            ),
        )

    return details


# Driver navigation is a separate public, token-authenticated workflow.
from app.schemas.ticket import DriverNavigationResponse
from app.services.driver_navigation_service import get_driver_navigation
from app.api.dependencies import get_db
from fastapi import Depends, Path
from sqlalchemy.orm import Session


driver_navigation_router = APIRouter(tags=["Driver Navigation"])


@driver_navigation_router.get(
    "/navigate/{token}",
    response_model=DriverNavigationResponse,
)
def public_driver_navigation(
    token: str = Path(..., min_length=20, max_length=256),
    db: Session = Depends(get_db),
):
    return get_driver_navigation(db, token)
