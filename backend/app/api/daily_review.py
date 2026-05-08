from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.api.deps import get_tenant_scoped_db
from app.auth.dependencies import require_admin_or_above
from app.db.models import DailyReviewCount, User

router = APIRouter(prefix="/api/daily-review", tags=["daily-review"])


class DailyReviewUpsert(BaseModel):
    date: str  # YYYY-MM-DD
    count: int


class DailyReviewResponse(BaseModel):
    id: int
    date: str
    count: int

    class Config:
        from_attributes = True


@router.get("", response_model=Optional[DailyReviewResponse])
async def get_daily_review(
    date: str,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """특정 날짜의 리뷰 수 조회"""
    row = db.query(DailyReviewCount).filter(DailyReviewCount.date == date).first()
    if not row:
        return None
    return {"id": row.id, "date": row.date, "count": row.count}


@router.put("", response_model=DailyReviewResponse)
async def upsert_daily_review(
    req: DailyReviewUpsert,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """리뷰 수 저장 (upsert: 날짜당 1건)"""
    existing = (
        db.query(DailyReviewCount)
        .filter(DailyReviewCount.date == req.date)
        .with_for_update()
        .first()
    )
    if existing:
        existing.count = req.count
        db.commit()
        db.refresh(existing)
        row = existing
    else:
        row = DailyReviewCount(date=req.date, count=req.count)
        db.add(row)
        db.commit()
        db.refresh(row)
    return {"id": row.id, "date": row.date, "count": row.count}
