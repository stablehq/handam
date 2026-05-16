"""
Message Templates API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone

from app.api.deps import get_tenant_scoped_db, _remap_active_field
from app.diag_logger import diag
from app.db.models import MessageTemplate, User
from app.auth.dependencies import get_current_user, require_admin_or_above
from app.templates.renderer import TemplateRenderer
from app.api.shared_schemas import ActionResponse

router = APIRouter(prefix="/api/templates", tags=["templates"])
router_misc = APIRouter()


# Pydantic models
def _validate_lms_title(value: Optional[str]) -> Optional[str]:
    """Aligo LMS 제목 30바이트 제한 (EUC-KR 기준, 한글 2바이트). 빈 문자열은 None 으로 정규화."""
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    try:
        byte_len = len(v.encode("euc-kr"))
    except UnicodeEncodeError:
        # EUC-KR 미지원 문자 → utf-8 fallback (보수적으로 더 큰 값 사용)
        byte_len = len(v.encode("utf-8"))
    if byte_len > 30:
        raise ValueError(f"LMS 제목은 최대 30바이트입니다 (현재 {byte_len}바이트, 한글 약 14자)")
    return v


class TemplateCreate(BaseModel):
    template_key: str
    name: str
    content: str
    variables: Optional[str] = None
    category: Optional[str] = None
    active: bool = True
    short_label: Optional[str] = None
    lms_title: Optional[str] = Field(default=None, max_length=30)
    participant_buffer: Optional[int] = 0
    male_buffer: Optional[int] = 0
    female_buffer: Optional[int] = 0
    gender_ratio_buffers: Optional[str] = None
    round_unit: Optional[int] = 0
    round_mode: Optional[str] = 'ceil'

    @field_validator("lms_title", mode="before")
    @classmethod
    def _check_lms_title(cls, v):
        return _validate_lms_title(v)


class TemplateUpdate(BaseModel):
    template_key: Optional[str] = None
    name: Optional[str] = None
    content: Optional[str] = None
    variables: Optional[str] = None
    category: Optional[str] = None
    active: Optional[bool] = None
    short_label: Optional[str] = None
    lms_title: Optional[str] = Field(default=None, max_length=30)
    participant_buffer: Optional[int] = None
    male_buffer: Optional[int] = None
    female_buffer: Optional[int] = None
    gender_ratio_buffers: Optional[str] = None
    round_unit: Optional[int] = None
    round_mode: Optional[str] = None

    @field_validator("lms_title", mode="before")
    @classmethod
    def _check_lms_title(cls, v):
        return _validate_lms_title(v)


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
    lms_title: Optional[str] = None
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
    query = db.query(MessageTemplate).options(selectinload(MessageTemplate.schedules))

    if category:
        query = query.filter(MessageTemplate.category == category)
    if active is not None:
        query = query.filter(MessageTemplate.is_active == active)

    templates = query.order_by(MessageTemplate.sort_order.asc(), MessageTemplate.id.asc()).all()

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
            "lms_title": template.lms_title,
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
    """Get template labels for chip display — 테넌트별 우선순위 지원.

    정렬 규칙:
      1. priority_keys 에 정의된 템플릿 — 그 배열 순서대로 (앞 고정)
      2. 그 외 — 하루 내 발송 시각(시:분) 오름차순. 시각 미상(스케줄 미연결,
         interval/event 등)은 끝으로
      3. 동률 tiebreaker: template_key 알파벳순
    """
    import json as _json
    from app.db.tenant_context import get_session_tenant_id
    from app.db.models import Tenant, TemplateSchedule

    # 테넌트별 chip_priority_keys 로드
    priority_keys = []
    tid = get_session_tenant_id(db)
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

    # 활성 스케줄에서 template_id 별 가장 이른 발송 시각(분 단위) 계산.
    # 예약일 기준 day-offset 까지 고려:
    #   today      → 0 (예약일 당일 발송)
    #   yesterday  → +1 (예약일 다음 날 발송 — 후기 류)
    #   tomorrow   → -1 (예약일 전날 발송 — 사전 안내 류)
    #   기타       → 0 (today_checkout 등은 안전하게 same-day 취급)
    # 정렬 값 = offset*1440 + hour*60 + minute → 같은 template 의 여러 스케줄이
    # 묶이면 가장 이른 값을 사용.
    DAY_OFFSET = {'today': 0, 'yesterday': 1, 'tomorrow': -1}
    SCHEDULE_TIME_MAX = 10 * 24 * 60  # 시각 미상 정렬용 (모든 정상 시각보다 큼)
    schedule_time_by_template: dict[int, int] = {}
    schedules = db.query(TemplateSchedule).filter(
        TemplateSchedule.is_active == True,
    ).all()
    for s in schedules:
        if s.hour is None or s.minute is None:
            continue
        offset = DAY_OFFSET.get(s.date_target or 'today', 0)
        minutes_total = offset * 1440 + s.hour * 60 + s.minute
        existing = schedule_time_by_template.get(s.template_id)
        if existing is None or minutes_total < existing:
            schedule_time_by_template[s.template_id] = minutes_total

    templates = db.query(MessageTemplate).filter(MessageTemplate.is_active == True).all()
    templates.sort(key=lambda t: (
        priority_keys.index(t.template_key) if t.template_key in priority_keys else len(priority_keys),
        schedule_time_by_template.get(t.id, SCHEDULE_TIME_MAX),
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
        "lms_title": template.lms_title,
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

    # 신규 템플릿은 정렬 맨 아래에 추가 (max + 1)
    from sqlalchemy import func
    max_order = db.query(func.max(MessageTemplate.sort_order)).scalar()
    next_order = (max_order or 0) + 1

    # Create template
    db_template = MessageTemplate(
        template_key=template.template_key,
        name=template.name,
        content=template.content,
        variables=template.variables,
        category=template.category,
        is_active=template.active,
        short_label=template.short_label,
        lms_title=template.lms_title,
        participant_buffer=template.participant_buffer or 0,
        male_buffer=template.male_buffer or 0,
        female_buffer=template.female_buffer or 0,
        gender_ratio_buffers=template.gender_ratio_buffers,
        round_unit=template.round_unit or 0,
        round_mode=template.round_mode or 'ceil',
        sort_order=next_order,
    )

    db.add(db_template)
    db.commit()
    db.refresh(db_template)

    diag("template.created", level="critical", template_id=db_template.id, key=db_template.template_key, name=db_template.name)

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
        "lms_title": db_template.lms_title,
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

    # 템플릿 비활성화 시 연관 칩 정리 — chip_store 위임 (PR10 이주).
    if 'is_active' in update_data and not update_data['is_active']:
        from app.services.chip_store import delete_chips_for_template
        delete_chips_for_template(db, template_key=db_template.template_key)

    db.commit()
    db.refresh(db_template)

    diag("template.updated", level="critical", template_id=db_template.id, changed_fields=list(update_data.keys()))
    if "content" in update_data:
        diag("template.content_changed", level="critical", template_id=db_template.id, key=db_template.template_key)

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
        "lms_title": db_template.lms_title,
        "participant_buffer": db_template.participant_buffer or 0,
        "male_buffer": db_template.male_buffer or 0,
        "female_buffer": db_template.female_buffer or 0,
        "gender_ratio_buffers": db_template.gender_ratio_buffers,
        "round_unit": db_template.round_unit or 0,
        "round_mode": db_template.round_mode or 'ceil',
    }


class TemplateReorderRequest(BaseModel):
    ordered_ids: List[int]  # 새 정렬 순서대로 정렬된 템플릿 id 배열


@router.post("/reorder", response_model=ActionResponse)
def reorder_templates(
    payload: TemplateReorderRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """ordered_ids 순서대로 sort_order 일괄 갱신 (DnD용).

    현재 테넌트의 전체 템플릿 ID 와 정확히 일치해야 함 (중복/누락 모두 거부).
    부분 reorder 를 허용하면 보내지 않은 템플릿과 sort_order 가 충돌할 수 있음.
    """
    sent_ids = payload.ordered_ids
    if not sent_ids:
        raise HTTPException(status_code=400, detail="ordered_ids가 비어 있습니다")

    if len(sent_ids) != len(set(sent_ids)):
        raise HTTPException(status_code=400, detail="중복된 템플릿 ID가 포함되어 있습니다")

    # 현재 테넌트의 모든 템플릿 (TenantMixin auto-filter 적용)
    all_ids = {row[0] for row in db.query(MessageTemplate.id).all()}
    if set(sent_ids) != all_ids:
        raise HTTPException(status_code=400, detail="전체 템플릿 목록과 일치하지 않습니다")

    templates = db.query(MessageTemplate).filter(MessageTemplate.id.in_(sent_ids)).all()
    by_id = {t.id: t for t in templates}

    for index, tid in enumerate(sent_ids):
        by_id[tid].sort_order = index

    db.commit()

    diag("template.reordered", level="critical", count=len(sent_ids))
    return {"success": True, "message": "순서가 변경되었습니다"}


@router.delete("/{template_id}", response_model=ActionResponse)
def delete_template(template_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(require_admin_or_above)):
    """Delete a message template"""
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id).first()

    if not template:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다")

    # template_schedules.template_id 가 NOT NULL 이라 SET NULL cascade 가 NotNullViolation 으로 터짐.
    # 활성/비활성 무관하게 묶인 스케줄이 있으면 차단해서 사용자에게 명시적으로 알린다.
    if hasattr(template, 'schedules') and template.schedules:
        total = len(template.schedules)
        active_count = sum(1 for s in template.schedules if s.is_active)
        inactive_count = total - active_count
        parts = []
        if active_count:
            parts.append(f"활성 {active_count}개")
        if inactive_count:
            parts.append(f"비활성 {inactive_count}개")
        raise HTTPException(
            status_code=400,
            detail=f"이 템플릿을 사용하는 스케줄({', '.join(parts)})을 먼저 삭제하세요",
        )

    diag("template.deleted", level="critical", template_id=template_id)
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

