from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from app.api.deps import get_tenant_scoped_db
from app.auth.dependencies import get_current_user
from app.db.models import PartyHost, User

router = APIRouter(prefix="/api/party-hosts", tags=["party-hosts"])


class PartyHostCreate(BaseModel):
    name: str


class PartyHostResponse(BaseModel):
    id: int
    name: str
    is_active: bool

    class Config:
        from_attributes = True


@router.get("", response_model=List[PartyHostResponse])
async def list_party_hosts(
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """진행자 목록 조회 (활성만)"""
    return db.query(PartyHost).filter(PartyHost.is_active == True).order_by(PartyHost.name).all()


@router.post("", response_model=PartyHostResponse, status_code=201)
async def create_party_host(
    req: PartyHostCreate,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """진행자 추가"""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="이름을 입력해주세요")

    existing = db.query(PartyHost).filter(PartyHost.name == name).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            db.commit()
            db.refresh(existing)
            return existing
        raise HTTPException(status_code=409, detail="이미 등록된 진행자입니다")

    host = PartyHost(name=name)
    db.add(host)
    db.commit()
    db.refresh(host)
    return host


@router.delete("/{host_id}", status_code=204)
async def delete_party_host(
    host_id: int,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """진행자 비활성화 (soft delete)"""
    host = db.query(PartyHost).filter(PartyHost.id == host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="진행자를 찾을 수 없습니다")
    host.is_active = False
    db.commit()
