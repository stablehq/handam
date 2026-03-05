"""
Rules management API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from app.db.database import get_db
from app.db.models import Rule, User
from app.auth.dependencies import get_current_user, require_admin_or_above
from datetime import datetime

router = APIRouter(prefix="/api/rules", tags=["rules"])


class RuleCreate(BaseModel):
    name: str
    pattern: str
    response: str
    priority: int = 0
    active: bool = True


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    pattern: Optional[str] = None
    response: Optional[str] = None
    priority: Optional[int] = None
    active: Optional[bool] = None


class RuleResponse(BaseModel):
    id: int
    name: str
    pattern: str
    response: str
    priority: int
    active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[RuleResponse])
async def get_rules(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get all rules"""
    rules = db.query(Rule).order_by(Rule.priority.desc()).all()
    return rules


@router.post("", response_model=RuleResponse)
async def create_rule(rule: RuleCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_above)):
    """Create a new rule"""
    db_rule = Rule(**rule.dict())
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    return db_rule


@router.put("/{rule_id}", response_model=RuleResponse)
async def update_rule(rule_id: int, rule: RuleUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_above)):
    """Update a rule"""
    db_rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    update_data = rule.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_rule, field, value)

    db.commit()
    db.refresh(db_rule)
    return db_rule


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_above)):
    """Delete a rule"""
    db_rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    db.delete(db_rule)
    db.commit()
    return {"status": "success", "message": "Rule deleted"}
