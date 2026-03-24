"""
Buildings API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload
from pydantic import BaseModel
from typing import List, Optional
from app.api.deps import get_tenant_scoped_db, _remap_active_field
from app.db.models import Building, Room, User
from app.auth.dependencies import get_current_user, require_admin_or_above
from app.api.shared_schemas import ActionResponse
from datetime import datetime
import logging

router = APIRouter(prefix="/api/buildings", tags=["buildings"])
logger = logging.getLogger(__name__)


class BuildingCreate(BaseModel):
    name: str
    description: Optional[str] = None
    active: bool = True
    sort_order: int = 0


class BuildingUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    active: Optional[bool] = None
    sort_order: Optional[int] = None


class BuildingResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    active: bool
    sort_order: int
    room_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


def _building_to_response(building: Building) -> BuildingResponse:
    """Convert Building ORM object to BuildingResponse."""
    return BuildingResponse(
        id=building.id,
        name=building.name,
        description=building.description,
        active=building.is_active,
        sort_order=building.sort_order,
        room_count=len(building.rooms) if building.rooms else 0,
        created_at=building.created_at,
    )


@router.get("", response_model=List[BuildingResponse])
async def get_buildings(
    include_inactive: bool = False,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Get all buildings"""
    query = db.query(Building).options(
        selectinload(Building.rooms),
    )

    if not include_inactive:
        query = query.filter(Building.is_active == True)

    buildings = query.order_by(Building.sort_order, Building.name).all()
    return [_building_to_response(b) for b in buildings]


@router.get("/{building_id}", response_model=BuildingResponse)
async def get_building(
    building_id: int,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single building by ID"""
    building = db.query(Building).options(
        selectinload(Building.rooms),
    ).filter(Building.id == building_id).first()

    if not building:
        raise HTTPException(status_code=404, detail="건물을 찾을 수 없습니다")
    return _building_to_response(building)


@router.post("", response_model=BuildingResponse, status_code=201)
async def create_building(
    building: BuildingCreate,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """Create a new building"""
    # Check for duplicate name
    existing = db.query(Building).filter(Building.name == building.name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"'{building.name}' 건물이 이미 존재합니다")

    db_building = Building(
        name=building.name,
        description=building.description,
        is_active=building.active,
        sort_order=building.sort_order,
    )
    db.add(db_building)
    db.commit()
    db.refresh(db_building)

    logger.info(f"Created building: {building.name}")
    return _building_to_response(db_building)


@router.put("/{building_id}", response_model=BuildingResponse)
async def update_building(
    building_id: int,
    building: BuildingUpdate,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """Update a building (including template linkage)"""
    db_building = db.query(Building).options(
        selectinload(Building.rooms),
    ).filter(Building.id == building_id).first()

    if not db_building:
        raise HTTPException(status_code=404, detail="건물을 찾을 수 없습니다")

    update_data = building.dict(exclude_unset=True)

    # Remap JSON key to ORM column name
    _remap_active_field(update_data)

    # Check for duplicate name if name is being changed
    if "name" in update_data and update_data["name"] != db_building.name:
        existing = db.query(Building).filter(Building.name == update_data["name"]).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"'{update_data['name']}' 건물이 이미 존재합니다")

    for field, value in update_data.items():
        setattr(db_building, field, value)

    db.commit()
    db.refresh(db_building)

    logger.info(f"Updated building {building_id}: {db_building.name}")
    return _building_to_response(db_building)


@router.delete("/{building_id}", response_model=ActionResponse)
async def delete_building(
    building_id: int,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """Delete a building (reject if rooms are linked)"""
    db_building = db.query(Building).options(
        selectinload(Building.rooms),
    ).filter(Building.id == building_id).first()

    if not db_building:
        raise HTTPException(status_code=404, detail="건물을 찾을 수 없습니다")

    room_count = len(db_building.rooms) if db_building.rooms else 0
    if room_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"'{db_building.name}' 건물에 {room_count}개의 객실이 연결되어 있습니다. 객실을 먼저 다른 건물로 이동하거나 삭제해주세요."
        )

    name = db_building.name
    db.delete(db_building)
    db.commit()

    logger.info(f"Deleted building: {name}")
    return {"success": True, "message": f"'{name}' 건물이 삭제되었습니다."}
