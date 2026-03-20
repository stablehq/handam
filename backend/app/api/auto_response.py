"""
Auto-response API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.api.deps import get_tenant_scoped_db, get_current_tenant
from app.db.models import Message, MessageDirection, MessageStatus, User, Tenant
from app.auth.dependencies import get_current_user, require_admin_or_above
from app.router.message_router import message_router
from app.factory import get_sms_provider_for_tenant

router = APIRouter(prefix="/api/auto-response", tags=["auto-response"])


class GenerateResponseRequest(BaseModel):
    message_id: int


class GenerateResponseFromTextRequest(BaseModel):
    message: str


@router.post("/generate")
async def generate_auto_response(request: GenerateResponseRequest, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user), tenant: Tenant = Depends(get_current_tenant)):
    """Generate auto-response for a message by ID"""
    # Get message from DB
    msg = db.query(Message).filter(Message.id == request.message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="메시지를 찾을 수 없습니다")

    if msg.direction != MessageDirection.INBOUND:
        raise HTTPException(status_code=400, detail="수신 메시지에만 자동응답을 생성할 수 있습니다")

    # Generate response
    result = await message_router.generate_auto_response(msg.content)

    # Update message with auto-response
    msg.auto_response = result["response"]
    msg.auto_response_confidence = result["confidence"]
    msg.needs_review = result["needs_review"]
    msg.response_source = result["source"]
    db.commit()

    # Auto-send if confidence is high enough
    if not result["needs_review"]:
        sms_provider = get_sms_provider_for_tenant(tenant)
        await sms_provider.send_sms(to=msg.from_, message=result["response"])

        # Create outbound message record
        outbound_msg = Message(
            message_id=f"auto_{msg.id}_{int(msg.created_at.timestamp())}",
            direction=MessageDirection.OUTBOUND,
            from_=msg.to,
            to=msg.from_,
            content=result["response"],
            status=MessageStatus.SENT,
            response_source=result["source"],
        )
        db.add(outbound_msg)
        db.commit()

    return {
        "message_id": msg.id,
        "auto_response": result["response"],
        "confidence": result["confidence"],
        "needs_review": result["needs_review"],
        "source": result["source"],
        "sent": not result["needs_review"],
    }


@router.post("/test")
async def test_auto_response(request: GenerateResponseFromTextRequest, current_user: User = Depends(require_admin_or_above)):
    """Test auto-response generation without saving to DB"""
    result = await message_router.generate_auto_response(request.message)
    return result


@router.post("/reload-rules")
async def reload_rules(current_user: User = Depends(require_admin_or_above)):
    """Hot reload rules from YAML file"""
    message_router.reload_rules()
    return {"success": True, "message": "규칙이 다시 로드되었습니다"}
