"""
Message Templates API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.db.database import get_db
from app.db.models import MessageTemplate, User
from app.auth.dependencies import get_current_user, require_admin_or_above
from app.templates.renderer import TemplateRenderer

router = APIRouter()


# Pydantic models
class TemplateCreate(BaseModel):
    key: str
    name: str
    content: str
    variables: Optional[str] = None
    category: Optional[str] = None
    active: bool = True


class TemplateUpdate(BaseModel):
    key: Optional[str] = None
    name: Optional[str] = None
    content: Optional[str] = None
    variables: Optional[str] = None
    category: Optional[str] = None
    active: Optional[bool] = None


class TemplateResponse(BaseModel):
    id: int
    key: str
    name: str
    content: str
    variables: Optional[str]
    category: Optional[str]
    active: bool
    created_at: datetime
    updated_at: datetime
    schedule_count: int = 0

    class Config:
        from_attributes = True


class TemplatePreviewRequest(BaseModel):
    variables: dict


class TemplatePreviewResponse(BaseModel):
    rendered: str
    variables_used: List[str]


@router.get("/api/templates", response_model=List[TemplateResponse])
def get_templates(
    category: Optional[str] = None,
    active: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all message templates"""
    query = db.query(MessageTemplate)

    if category:
        query = query.filter(MessageTemplate.category == category)
    if active is not None:
        query = query.filter(MessageTemplate.active == active)

    templates = query.order_by(MessageTemplate.created_at.desc()).all()

    # Add schedule count
    result = []
    for template in templates:
        template_dict = {
            "id": template.id,
            "key": template.key,
            "name": template.name,
            "content": template.content,
            "variables": template.variables,
            "category": template.category,
            "active": template.active,
            "created_at": template.created_at,
            "updated_at": template.updated_at,
            "schedule_count": len(template.schedules) if hasattr(template, 'schedules') else 0
        }
        result.append(template_dict)

    return result


@router.get("/api/templates/{template_id}", response_model=TemplateResponse)
def get_template(template_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get a specific template"""
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id).first()

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return {
        "id": template.id,
        "key": template.key,
        "name": template.name,
        "content": template.content,
        "variables": template.variables,
        "category": template.category,
        "active": template.active,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
        "schedule_count": len(template.schedules) if hasattr(template, 'schedules') else 0
    }


@router.post("/api/templates", response_model=TemplateResponse)
def create_template(template: TemplateCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_above)):
    """Create a new message template"""
    # Check if key already exists
    existing = db.query(MessageTemplate).filter(MessageTemplate.key == template.key).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Template with key '{template.key}' already exists")

    # Create template
    db_template = MessageTemplate(
        key=template.key,
        name=template.name,
        content=template.content,
        variables=template.variables,
        category=template.category,
        active=template.active
    )

    db.add(db_template)
    db.commit()
    db.refresh(db_template)

    return {
        "id": db_template.id,
        "key": db_template.key,
        "name": db_template.name,
        "content": db_template.content,
        "variables": db_template.variables,
        "category": db_template.category,
        "active": db_template.active,
        "created_at": db_template.created_at,
        "updated_at": db_template.updated_at,
        "schedule_count": 0
    }


@router.put("/api/templates/{template_id}", response_model=TemplateResponse)
def update_template(template_id: int, template: TemplateUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_above)):
    """Update a message template"""
    db_template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id).first()

    if not db_template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Check if new key conflicts
    if template.key and template.key != db_template.key:
        existing = db.query(MessageTemplate).filter(MessageTemplate.key == template.key).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Template with key '{template.key}' already exists")

    # Update fields
    update_data = template.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_template, field, value)

    db_template.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_template)

    return {
        "id": db_template.id,
        "key": db_template.key,
        "name": db_template.name,
        "content": db_template.content,
        "variables": db_template.variables,
        "category": db_template.category,
        "active": db_template.active,
        "created_at": db_template.created_at,
        "updated_at": db_template.updated_at,
        "schedule_count": len(db_template.schedules) if hasattr(db_template, 'schedules') else 0
    }


@router.delete("/api/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_above)):
    """Delete a message template"""
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id).first()

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Check if template has active schedules
    if hasattr(template, 'schedules') and template.schedules:
        active_schedules = [s for s in template.schedules if s.active]
        if active_schedules:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete template with {len(active_schedules)} active schedule(s)"
            )

    db.delete(template)
    db.commit()

    return {"success": True, "message": "Template deleted"}


@router.post("/api/templates/{template_id}/preview", response_model=TemplatePreviewResponse)
def preview_template(
    template_id: int,
    request: TemplatePreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Preview template with sample variables"""
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id).first()

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        # Create renderer instance with db session
        renderer = TemplateRenderer(db)

        # Render template with provided variables
        rendered = renderer.render(template.key, request.variables)

        # Extract variables used (simple regex)
        import re
        variables_pattern = r'\{\{(\w+)\}\}'
        variables_used = re.findall(variables_pattern, template.content)

        return {
            "rendered": rendered,
            "variables_used": list(set(variables_used))
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to render template: {str(e)}")


@router.get("/api/template-variables")
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
