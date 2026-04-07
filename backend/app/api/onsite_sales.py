from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from app.api.deps import get_tenant_scoped_db
from app.auth.dependencies import get_current_user
from app.db.models import OnsiteSale, User

router = APIRouter(prefix="/api/onsite-sales", tags=["onsite-sales"])


class OnsiteSaleCreate(BaseModel):
    date: str  # YYYY-MM-DD
    item_name: str
    amount: int


class OnsiteSaleResponse(BaseModel):
    id: int
    date: str
    item_name: str
    amount: int
    created_by: Optional[str]
    created_at: Optional[str]

    class Config:
        from_attributes = True


@router.get("", response_model=List[OnsiteSaleResponse])
async def get_sales(
    date: str,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """특정 날짜의 현장 판매 목록 조회"""
    sales = (
        db.query(OnsiteSale)
        .filter(OnsiteSale.date == date)
        .order_by(OnsiteSale.created_at.desc())
        .all()
    )
    return [
        {
            "id": s.id,
            "date": s.date,
            "item_name": s.item_name,
            "amount": s.amount,
            "created_by": s.created_by,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in sales
    ]


@router.post("", response_model=OnsiteSaleResponse)
async def create_sale(
    req: OnsiteSaleCreate,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """현장 판매 기록 추가"""
    sale = OnsiteSale(
        date=req.date,
        item_name=req.item_name,
        amount=req.amount,
        created_by=current_user.username,
    )
    db.add(sale)
    db.commit()
    db.refresh(sale)
    return {
        "id": sale.id,
        "date": sale.date,
        "item_name": sale.item_name,
        "amount": sale.amount,
        "created_by": sale.created_by,
        "created_at": sale.created_at.isoformat() if sale.created_at else None,
    }


@router.delete("/{sale_id}")
async def delete_sale(
    sale_id: int,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """현장 판매 기록 삭제"""
    sale = db.query(OnsiteSale).filter(OnsiteSale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="판매 기록을 찾을 수 없습니다")
    db.delete(sale)
    db.commit()
    return {"success": True}
