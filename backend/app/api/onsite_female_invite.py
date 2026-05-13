from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from app.api.deps import get_tenant_scoped_db
from app.auth.dependencies import require_admin_or_above
from app.db.models import OnsiteFemaleInvite, User

router = APIRouter(prefix="/api/onsite-female-invites", tags=["onsite-female-invites"])


class OnsiteFemaleInviteCreate(BaseModel):
    date: str  # YYYY-MM-DD
    host_username: str
    count: int  # 더할 값 (누적)


class OnsiteFemaleInviteUpdate(BaseModel):
    host_username: Optional[str] = None
    count: Optional[int] = None  # 절대값 (덮어쓰기)


class OnsiteFemaleInviteResponse(BaseModel):
    id: int
    date: str
    host_username: str
    count: int

    class Config:
        from_attributes = True


@router.get("", response_model=List[OnsiteFemaleInviteResponse])
async def list_invites(
    date: str,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """특정 날짜의 진행자별 여자초대수 목록"""
    rows = (
        db.query(OnsiteFemaleInvite)
        .filter(OnsiteFemaleInvite.date == date)
        .order_by(OnsiteFemaleInvite.host_username)
        .all()
    )
    return [{"id": r.id, "date": r.date, "host_username": r.host_username, "count": r.count} for r in rows]


@router.post("", response_model=OnsiteFemaleInviteResponse)
async def add_invite(
    req: OnsiteFemaleInviteCreate,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """여자초대수 추가 — 같은 진행자 재입력 시 count 누적"""
    if not req.host_username.strip():
        raise HTTPException(status_code=400, detail="진행자를 선택해주세요")
    if req.count <= 0:
        raise HTTPException(status_code=400, detail="0보다 큰 값을 입력해주세요")
    existing = (
        db.query(OnsiteFemaleInvite)
        .filter(
            OnsiteFemaleInvite.date == req.date,
            OnsiteFemaleInvite.host_username == req.host_username,
        )
        .with_for_update()
        .first()
    )
    if existing:
        existing.count += req.count
        db.commit()
        db.refresh(existing)
        row = existing
    else:
        row = OnsiteFemaleInvite(
            date=req.date,
            host_username=req.host_username,
            count=req.count,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return {"id": row.id, "date": row.date, "host_username": row.host_username, "count": row.count}


@router.patch("/{invite_id}", response_model=OnsiteFemaleInviteResponse)
async def update_invite(
    invite_id: int,
    req: OnsiteFemaleInviteUpdate,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """진행자별 여자초대수 수정 — host_username/count 덮어쓰기"""
    row = db.query(OnsiteFemaleInvite).filter(OnsiteFemaleInvite.id == invite_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다")
    if req.host_username is not None:
        new_host = req.host_username.strip()
        if not new_host:
            raise HTTPException(status_code=400, detail="진행자를 선택해주세요")
        if new_host != row.host_username:
            # with_for_update — POST add_invite 와 동일 패턴. dup 체크와 update 사이
            # 다른 트랜잭션이 같은 (date, host_username) 행을 insert 하는 race 차단.
            dup = (
                db.query(OnsiteFemaleInvite)
                .filter(
                    OnsiteFemaleInvite.date == row.date,
                    OnsiteFemaleInvite.host_username == new_host,
                    OnsiteFemaleInvite.id != invite_id,
                )
                .with_for_update()
                .first()
            )
            if dup:
                raise HTTPException(status_code=400, detail=f"{new_host} 진행자는 이미 등록되어 있습니다")
            row.host_username = new_host
    if req.count is not None:
        if req.count <= 0:
            raise HTTPException(status_code=400, detail="0보다 큰 값을 입력해주세요")
        row.count = req.count
    db.commit()
    db.refresh(row)
    return {"id": row.id, "date": row.date, "host_username": row.host_username, "count": row.count}


@router.delete("/{invite_id}", status_code=204)
async def delete_invite(
    invite_id: int,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """진행자별 여자초대수 행 전체 삭제"""
    row = db.query(OnsiteFemaleInvite).filter(OnsiteFemaleInvite.id == invite_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다")
    db.delete(row)
    db.commit()
