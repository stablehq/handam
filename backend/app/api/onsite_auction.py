from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Literal, Optional
from app.api.deps import get_tenant_scoped_db
from app.auth.dependencies import require_admin_or_above
from app.db.models import OnsiteAuction, User

router = APIRouter(prefix="/api/onsite-auctions", tags=["onsite-auctions"])


class OnsiteAuctionUpsert(BaseModel):
    date: str  # YYYY-MM-DD
    item_name: str
    final_amount: int
    winner_name: str
    payment_method: Literal["카드", "이체", "현금"] = "카드"


class OnsiteAuctionResponse(BaseModel):
    id: int
    date: str
    item_name: str
    final_amount: int
    winner_name: str
    payment_method: Optional[str]
    created_by: Optional[str]
    created_at: Optional[str]

    class Config:
        from_attributes = True


@router.get("", response_model=Optional[OnsiteAuctionResponse])
async def get_auction(
    date: str,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """특정 날짜의 경매 기록 조회"""
    auction = db.query(OnsiteAuction).filter(OnsiteAuction.date == date).first()
    if not auction:
        return None
    return {
        "id": auction.id,
        "date": auction.date,
        "item_name": auction.item_name,
        "final_amount": auction.final_amount,
        "winner_name": auction.winner_name,
        "payment_method": auction.payment_method,
        "created_by": auction.created_by,
        "created_at": auction.created_at.isoformat() if auction.created_at else None,
    }


@router.post("", response_model=OnsiteAuctionResponse)
async def upsert_auction(
    req: OnsiteAuctionUpsert,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """경매 기록 저장 (upsert: 날짜당 1건)"""
    existing = (
        db.query(OnsiteAuction)
        .filter(OnsiteAuction.date == req.date)
        .with_for_update()
        .first()
    )
    if existing:
        existing.item_name = req.item_name
        existing.final_amount = req.final_amount
        existing.winner_name = req.winner_name
        existing.payment_method = req.payment_method
        db.commit()
        db.refresh(existing)
        auction = existing
    else:
        auction = OnsiteAuction(
            date=req.date,
            item_name=req.item_name,
            final_amount=req.final_amount,
            winner_name=req.winner_name,
            payment_method=req.payment_method,
            created_by=current_user.username,
        )
        db.add(auction)
        db.commit()
        db.refresh(auction)
    return {
        "id": auction.id,
        "date": auction.date,
        "item_name": auction.item_name,
        "final_amount": auction.final_amount,
        "winner_name": auction.winner_name,
        "payment_method": auction.payment_method,
        "created_by": auction.created_by,
        "created_at": auction.created_at.isoformat() if auction.created_at else None,
    }


@router.delete("/{auction_id}")
async def delete_auction(
    auction_id: int,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """경매 기록 삭제"""
    auction = db.query(OnsiteAuction).filter(OnsiteAuction.id == auction_id).first()
    if not auction:
        raise HTTPException(status_code=404, detail="경매 기록을 찾을 수 없습니다")
    db.delete(auction)
    db.commit()
    return {"success": True}
