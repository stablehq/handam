"""
Rules management API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from app.api.deps import get_tenant_scoped_db
from app.db.models import Rule, User
from app.auth.dependencies import get_current_user, require_admin_or_above
from app.api.shared_schemas import ActionResponse
from datetime import datetime
import re

router = APIRouter(prefix="/api/rules", tags=["rules"])


def _validate_regex_pattern(pattern: str) -> None:
    """M17: Regex 패턴 유효성 검증 - 유효하지 않으면 HTTPException 발생"""
    if len(pattern) > 500:
        raise HTTPException(status_code=400, detail="패턴이 너무 깁니다 (최대 500자)")
    try:
        re.compile(pattern)
    except re.error as e:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 정규식 패턴입니다: {e}")


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


def _rule_to_response(rule: Rule) -> dict:
    """Convert Rule ORM object to RuleResponse-compatible dict."""
    return {
        "id": rule.id,
        "name": rule.name,
        "pattern": rule.pattern,
        "response": rule.response,
        "priority": rule.priority,
        "active": rule.is_active,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


@router.get("", response_model=List[RuleResponse])
async def get_rules(db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Get all rules"""
    rules = db.query(Rule).order_by(Rule.priority.desc()).all()
    return [_rule_to_response(r) for r in rules]


@router.post("", response_model=RuleResponse)
async def create_rule(rule: RuleCreate, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(require_admin_or_above)):
    """Create a new rule"""
    _validate_regex_pattern(rule.pattern)
    rule_data = rule.dict()
    # Remap Pydantic 'active' → ORM 'is_active'
    if "active" in rule_data:
        rule_data["is_active"] = rule_data.pop("active")
    db_rule = Rule(**rule_data)
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    return _rule_to_response(db_rule)


@router.put("/{rule_id}", response_model=RuleResponse)
async def update_rule(rule_id: int, rule: RuleUpdate, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(require_admin_or_above)):
    """Update a rule"""
    db_rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="규칙을 찾을 수 없습니다")

    update_data = rule.dict(exclude_unset=True)
    # Remap Pydantic 'active' → ORM 'is_active'
    if "active" in update_data:
        update_data["is_active"] = update_data.pop("active")
    if "pattern" in update_data:
        _validate_regex_pattern(update_data["pattern"])
    for field, value in update_data.items():
        setattr(db_rule, field, value)

    db.commit()
    db.refresh(db_rule)
    return _rule_to_response(db_rule)


@router.delete("/{rule_id}", response_model=ActionResponse)
async def delete_rule(rule_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(require_admin_or_above)):
    """Delete a rule"""
    db_rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="규칙을 찾을 수 없습니다")

    db.delete(db_rule)
    db.commit()
    return {"success": True, "message": "규칙이 삭제되었습니다"}
