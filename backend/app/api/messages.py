"""
Message API endpoints
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from typing import List, Optional
from app.api.deps import get_tenant_scoped_db, get_current_tenant
from app.db.models import Message, MessageDirection, MessageStatus, Reservation, User, Tenant
from app.auth.dependencies import get_current_user
from app.factory import get_sms_provider_for_tenant
from app.services.activity_logger import log_activity
from datetime import datetime

router = APIRouter(prefix="/api/messages", tags=["messages"])


class SendSMSRequest(BaseModel):
    to: str
    content: str


class SimulateReceiveRequest(BaseModel):
    from_: str
    to: str
    content: str


class MessageResponse(BaseModel):
    id: int
    message_id: str
    direction: str
    from_: str
    to: str
    content: str
    status: str
    created_at: datetime
    auto_response: Optional[str] = None
    auto_response_confidence: Optional[float] = None
    needs_review: bool = False
    response_source: Optional[str] = None

    class Config:
        from_attributes = True


class ContactResponse(BaseModel):
    phone: str
    last_message: str
    last_message_time: datetime
    last_direction: str
    customer_name: Optional[str] = None


@router.get("/contacts", response_model=List[ContactResponse])
async def get_contacts(db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user), tenant: Tenant = Depends(get_current_tenant)):
    """Get unique contact list with last message preview"""
    # Get all messages, find unique phone numbers (excluding our own number)
    our_number = tenant.aligo_sender or ''

    messages = (
        db.query(Message)
        .order_by(Message.created_at.desc())
        .all()
    )

    contacts_map: dict = {}
    for msg in messages:
        # Determine customer phone number
        if msg.direction == MessageDirection.INBOUND:
            phone = msg.from_
        else:
            phone = msg.to

        # Skip our own number
        if phone == our_number:
            continue

        if phone not in contacts_map:
            contacts_map[phone] = {
                "phone": phone,
                "last_message": msg.content[:100],
                "last_message_time": msg.created_at,
                "last_direction": msg.direction.value,
            }

    # Look up customer names from reservations — 배치 조회로 N+1 제거
    phones = list(contacts_map.keys())
    reservations_for_contacts = (
        db.query(Reservation)
        .filter(Reservation.phone.in_(phones))
        .order_by(Reservation.created_at.desc())
        .all()
    )
    res_map: dict = {}
    for r in reservations_for_contacts:
        if r.phone not in res_map:
            res_map[r.phone] = r

    contacts = []
    for phone, contact in contacts_map.items():
        reservation = res_map.get(phone)
        contact["customer_name"] = reservation.customer_name if reservation else None
        contacts.append(ContactResponse(**contact))

    # Sort by last message time descending
    contacts.sort(key=lambda c: c.last_message_time, reverse=True)

    return contacts


@router.get("", response_model=List[MessageResponse])
async def get_messages(
    skip: int = 0,
    limit: int = 50,
    direction: Optional[str] = None,
    phone: Optional[str] = None,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Get message history with pagination"""
    query = db.query(Message)

    if direction:
        query = query.filter(Message.direction == direction)

    if phone:
        query = query.filter(or_(Message.from_ == phone, Message.to == phone))
        # Chat view: ascending order for conversation flow
        messages = query.order_by(Message.created_at.asc()).offset(skip).limit(limit).all()
    else:
        # Default: descending (newest first)
        messages = query.order_by(Message.created_at.desc()).offset(skip).limit(limit).all()

    return [
        MessageResponse(
            id=msg.id,
            message_id=msg.message_id,
            direction=msg.direction.value,
            from_=msg.from_,
            to=msg.to,
            content=msg.content,
            status=msg.status.value,
            created_at=msg.created_at,
            auto_response=msg.auto_response,
            auto_response_confidence=msg.auto_response_confidence,
            needs_review=msg.needs_review,
            response_source=msg.response_source,
        )
        for msg in messages
    ]


@router.post("/send")
async def send_sms(request: SendSMSRequest, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user), tenant: Tenant = Depends(get_current_tenant)):
    """Send SMS manually"""
    sms_provider = get_sms_provider_for_tenant(tenant)
    result = await sms_provider.send_sms(to=request.to, message=request.content)

    # Save to DB
    msg = Message(
        message_id=result["message_id"],
        direction=MessageDirection.OUTBOUND,
        from_=tenant.aligo_sender or '',
        to=request.to,
        content=request.content,
        status=MessageStatus.SENT,
        response_source="manual",
    )
    db.add(msg)
    db.commit()

    log_activity(
        db,
        type="sms_manual",
        title=f"수동 문자 발송 → {request.to}",
        detail={"to": request.to, "content": request.content[:50], "success": result.get("success", False)},
        target_count=1,
        success_count=1 if result.get("success") else 0,
        created_by=current_user.username,
    )
    db.commit()

    return {"success": True, "result": result}


