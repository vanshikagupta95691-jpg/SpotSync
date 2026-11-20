from datetime import datetime

from pydantic import BaseModel, Field


class TicketCreateResponse(BaseModel):
    token: str
    navigation_url: str
    expires_at: datetime
    message: str


class TicketValidationRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)


class TicketValidationResponse(BaseModel):
    valid: bool
    session_id: int
    parking_lot_id: int
    parking_slot_id: int
    vehicle_id: int | None
    message: str


class DriverVehicleInfo(BaseModel):
    id: int
    vehicle_number: str
    vehicle_type: str


class DriverParkingSlotInfo(BaseModel):
    id: int
    parking_lot_id: int
    slot_number: str
    display_code: str | None
    slot_type: str
    status: str


class DriverFloorInfo(BaseModel):
    id: int
    floor_code: str
    floor_name: str


class DriverNavigationResponse(BaseModel):
    session_id: int
    vehicle: DriverVehicleInfo
    parking_slot: DriverParkingSlotInfo
    floor: DriverFloorInfo
    navigation: dict
