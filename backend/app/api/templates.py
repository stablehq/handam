"""
Message Templates API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timezone

from app.api.deps import get_tenant_scoped_db, _remap_active_field
from app.db.models import MessageTemplate, User
from app.auth.dependencies import get_current_user, require_admin_or_above
from app.templates.renderer import TemplateRenderer
from app.api.shared_schemas import ActionResponse

router = APIRouter(prefix="/api/templates", tags=["templates"])
router_misc = APIRouter()


# Pydantic models
class TemplateCreate(BaseModel):
    template_key: str
    name: str
    content: str
    variables: Optional[str] = None
    category: Optional[str] = None
    active: bool = True
    short_label: Optional[str] = None
    participant_buffer: Optional[int] = 0
    male_buffer: Optional[int] = 0
    female_buffer: Optional[int] = 0
    gender_ratio_buffers: Optional[str] = None
    round_unit: Optional[int] = 0
    round_mode: Optional[str] = 'ceil'


class TemplateUpdate(BaseModel):
    template_key: Optional[str] = None
    name: Optional[str] = None
    content: Optional[str] = None
    variables: Optional[str] = None
    category: Optional[str] = None
    active: Optional[bool] = None
    short_label: Optional[str] = None
    participant_buffer: Optional[int] = None
    male_buffer: Optional[int] = None
    female_buffer: Optional[int] = None
    gender_ratio_buffers: Optional[str] = None
    round_unit: Optional[int] = None
    round_mode: Optional[str] = None


class TemplateResponse(BaseModel):
    id: int
    template_key: str
    name: str
    content: str
    variables: Optional[str]
    category: Optional[str]
    active: bool
    created_at: datetime
    updated_at: datetime
    schedule_count: int = 0
    short_label: Optional[str] = None
    participant_buffer: Optional[int] = 0
    male_buffer: Optional[int] = 0
    female_buffer: Optional[int] = 0
    gender_ratio_buffers: Optional[str] = None
    round_unit: Optional[int] = 0
    round_mode: Optional[str] = 'ceil'

    class Config:
        from_attributes = True


class TemplatePreviewRequest(BaseModel):
    variables: dict


class TemplatePreviewResponse(BaseModel):
    rendered: str
    variables_used: List[str]


@router.get("", response_model=List[TemplateResponse])
def get_templates(
    category: Optional[str] = None,
    active: Optional[bool] = None,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Get all message templates"""
    query = db.query(MessageTemplate)

    if category:
        query = query.filter(MessageTemplate.category == category)
    if active is not None:
        query = query.filter(MessageTemplate.is_active == active)

    templates = query.order_by(MessageTemplate.created_at.desc()).all()

    # Add schedule count
    result = []
    for template in templates:
        template_dict = {
            "id": template.id,
            "template_key": template.template_key,
            "name": template.name,
            "content": template.content,
            "variables": template.variables,
            "category": template.category,
            "active": template.is_active,
            "created_at": template.created_at,
            "updated_at": template.updated_at,
            "schedule_count": len(template.schedules) if hasattr(template, 'schedules') else 0,
            "short_label": template.short_label,
            "participant_buffer": template.participant_buffer or 0,
            "male_buffer": template.male_buffer or 0,
            "female_buffer": template.female_buffer or 0,
            "gender_ratio_buffers": template.gender_ratio_buffers,
            "round_unit": template.round_unit or 0,
            "round_mode": template.round_mode or 'ceil',
        }
        result.append(template_dict)

    return result


@router.get("/labels")
def get_template_labels(
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Get template labels for chip display — 테넌트별 우선순위 지원"""
    import json as _json
    from app.db.tenant_context import current_tenant_id
    from app.db.models import Tenant

    # 테넌트별 chip_priority_keys 로드
    priority_keys = []
    tid = current_tenant_id.get()
    if tid:
        tenant = db.query(Tenant).filter(Tenant.id == tid).first()
        if tenant and tenant.chip_priority_keys:
            try:
                priority_keys = _json.loads(tenant.chip_priority_keys)
            except (ValueError, TypeError):
                pass
    # 폴백: 설정 없으면 기본 순서
    if not priority_keys:
        priority_keys = ["party_info", "room_info", "sub_room_info"]

    templates = db.query(MessageTemplate).filter(MessageTemplate.is_active == True).all()
    templates.sort(key=lambda t: (
        priority_keys.index(t.template_key) if t.template_key in priority_keys else len(priority_keys),
        t.template_key,
    ))
    return [
        {
            "template_key": t.template_key,
            "name": t.name,
            "short_label": t.short_label,
        }
        for t in templates
    ]


@router.get("/{template_id}", response_model=TemplateResponse)
def get_template(template_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Get a specific template"""
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id).first()

    if not template:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다")

    return {
        "id": template.id,
        "template_key": template.template_key,
        "name": template.name,
        "content": template.content,
        "variables": template.variables,
        "category": template.category,
        "active": template.is_active,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
        "schedule_count": len(template.schedules) if hasattr(template, 'schedules') else 0,
        "short_label": template.short_label,
        "participant_buffer": template.participant_buffer or 0,
        "male_buffer": template.male_buffer or 0,
        "female_buffer": template.female_buffer or 0,
        "gender_ratio_buffers": template.gender_ratio_buffers,
        "round_unit": template.round_unit or 0,
        "round_mode": template.round_mode or 'ceil',
    }


@router.post("", response_model=TemplateResponse)
def create_template(template: TemplateCreate, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(require_admin_or_above)):
    """Create a new message template"""
    # Check if key already exists
    existing = db.query(MessageTemplate).filter(MessageTemplate.template_key == template.template_key).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"키 '{template.template_key}'의 템플릿이 이미 존재합니다")

    # Create template
    db_template = MessageTemplate(
        template_key=template.template_key,
        name=template.name,
        content=template.content,
        variables=template.variables,
        category=template.category,
        is_active=template.active,
        short_label=template.short_label,
        participant_buffer=template.participant_buffer or 0,
        male_buffer=template.male_buffer or 0,
        female_buffer=template.female_buffer or 0,
        gender_ratio_buffers=template.gender_ratio_buffers,
        round_unit=template.round_unit or 0,
        round_mode=template.round_mode or 'ceil',
    )

    db.add(db_template)
    db.commit()
    db.refresh(db_template)

    return {
        "id": db_template.id,
        "template_key": db_template.template_key,
        "name": db_template.name,
        "content": db_template.content,
        "variables": db_template.variables,
        "category": db_template.category,
        "active": db_template.is_active,
        "created_at": db_template.created_at,
        "updated_at": db_template.updated_at,
        "schedule_count": 0,
        "short_label": db_template.short_label,
        "participant_buffer": db_template.participant_buffer or 0,
        "male_buffer": db_template.male_buffer or 0,
        "female_buffer": db_template.female_buffer or 0,
        "gender_ratio_buffers": db_template.gender_ratio_buffers,
        "round_unit": db_template.round_unit or 0,
        "round_mode": db_template.round_mode or 'ceil',
    }


@router.put("/{template_id}", response_model=TemplateResponse)
def update_template(template_id: int, template: TemplateUpdate, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(require_admin_or_above)):
    """Update a message template"""
    db_template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id).first()

    if not db_template:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다")

    # Check if new key conflicts
    if template.template_key and template.template_key != db_template.template_key:
        existing = db.query(MessageTemplate).filter(MessageTemplate.template_key == template.template_key).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"키 '{template.template_key}'의 템플릿이 이미 존재합니다")

    # Update fields
    update_data = template.dict(exclude_unset=True)
    # Remap Pydantic 'active' field to ORM 'is_active' column
    _remap_active_field(update_data)
    for field, value in update_data.items():
        setattr(db_template, field, value)

    db_template.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(db_template)

    return {
        "id": db_template.id,
        "template_key": db_template.template_key,
        "name": db_template.name,
        "content": db_template.content,
        "variables": db_template.variables,
        "category": db_template.category,
        "active": db_template.is_active,
        "created_at": db_template.created_at,
        "updated_at": db_template.updated_at,
        "schedule_count": len(db_template.schedules) if hasattr(db_template, 'schedules') else 0,
        "short_label": db_template.short_label,
        "participant_buffer": db_template.participant_buffer or 0,
        "male_buffer": db_template.male_buffer or 0,
        "female_buffer": db_template.female_buffer or 0,
        "gender_ratio_buffers": db_template.gender_ratio_buffers,
        "round_unit": db_template.round_unit or 0,
        "round_mode": db_template.round_mode or 'ceil',
    }


@router.delete("/{template_id}", response_model=ActionResponse)
def delete_template(template_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(require_admin_or_above)):
    """Delete a message template"""
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id).first()

    if not template:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다")

    # Check if template has active schedules
    if hasattr(template, 'schedules') and template.schedules:
        active_schedules = [s for s in template.schedules if s.is_active]
        if active_schedules:
            raise HTTPException(
                status_code=400,
                detail=f"활성 스케줄이 {len(active_schedules)}개 있는 템플릿은 삭제할 수 없습니다"
            )

    db.delete(template)
    db.commit()

    return {"success": True, "message": "템플릿이 삭제되었습니다"}


@router.post("/{template_id}/preview", response_model=TemplatePreviewResponse)
def preview_template(
    template_id: int,
    request: TemplatePreviewRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Preview template with sample variables"""
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id).first()

    if not template:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다")

    try:
        # Create renderer instance with db session
        renderer = TemplateRenderer(db)

        # Render template with provided variables
        rendered = renderer.render(template.template_key, request.variables)

        # Extract variables used (simple regex)
        import re
        variables_pattern = r'\{\{(\w+)\}\}'
        variables_used = re.findall(variables_pattern, template.content)

        return {
            "rendered": rendered,
            "variables_used": list(set(variables_used))
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"템플릿 렌더링 실패: {str(e)}")


@router_misc.get("/api/template-variables")
def get_available_variables(current_user: User = Depends(get_current_user)):
    """
    Get list of all available template variables

    Returns variables grouped by category with descriptions and examples
    """
    from app.templates.variables import AVAILABLE_VARIABLES, get_variable_categories

    return {
        "variables": AVAILABLE_VARIABLES,
        "categories": get_variable_categories()
    }
