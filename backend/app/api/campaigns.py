"""
Campaign API endpoints for tag-based SMS sending
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from datetime import datetime

from ..db.database import get_db
from ..db.models import CampaignLog, GenderStat, MessageTemplate, User
from ..auth.dependencies import get_current_user, require_admin_or_above
from ..factory import get_sms_provider, get_storage_provider
from ..campaigns.tag_manager import TagCampaignManager
from ..notifications.service import NotificationService
from ..analytics.gender_analyzer import GenderAnalyzer

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


# Campaign definitions - each campaign is independent
CAMPAIGN_DEFINITIONS = {
    # Tag-based campaigns
    "tag_객후": {
        "name": "객후",
        "description": "객후 태그가 있는 사람에게 객후 메시지 발송",
        "target_type": "tag",
        "target_value": "객후",
        "sms_type": "room",
        "template_key": "tag_객후"
    },
    "tag_1초": {
        "name": "1초",
        "description": "1초 태그가 있는 사람에게 1초 메시지 발송",
        "target_type": "tag",
        "target_value": "1초",
        "sms_type": "party",
        "template_key": "tag_1초"
    },
    "tag_2차만": {
        "name": "2차만",
        "description": "2차만 태그가 있는 사람에게 2차만 메시지 발송",
        "target_type": "tag",
        "target_value": "2차만",
        "sms_type": "party",
        "template_key": "tag_2차만"
    },
    "tag_객후1초": {
        "name": "객후,1초",
        "description": "객후,1초 태그가 있는 사람에게 메시지 발송",
        "target_type": "tag",
        "target_value": "객후,1초",
        "sms_type": "room",
        "template_key": "tag_객후1초"
    },
    "tag_1초2차만": {
        "name": "1초,2차만",
        "description": "1초,2차만 태그가 있는 사람에게 메시지 발송",
        "target_type": "tag",
        "target_value": "1초,2차만",
        "sms_type": "party",
        "template_key": "tag_1초2차만"
    },
    # SMS type campaigns
    "sms_room": {
        "name": "객실 문자",
        "description": "객실이 배정된 사람에게 객실 안내 발송",
        "target_type": "sms_type",
        "target_value": "room",
        "sms_type": "room",
        "template_key": "room_guide"
    },
    "sms_party": {
        "name": "파티 문자",
        "description": "파티 참여자에게 파티 안내 발송",
        "target_type": "sms_type",
        "target_value": "party",
        "sms_type": "party",
        "template_key": "party_guide"
    },
    # Template-based campaigns
    "template_welcome": {
        "name": "환영 메시지",
        "description": "신규 예약자에게 환영 메시지 발송",
        "target_type": "all_reservations",
        "target_value": None,
        "sms_type": "room",
        "template_key": "welcome"
    },
    "template_confirm": {
        "name": "확인 메시지",
        "description": "확정된 예약자에게 확인 메시지 발송",
        "target_type": "confirmed",
        "target_value": None,
        "sms_type": "room",
        "template_key": "confirmation"
    },
}


# Request/Response models
class CampaignRequest(BaseModel):
    tag: str
    template_key: str
    variables: Optional[Dict[str, Any]] = None
    sms_type: str = 'room'  # 'room' or 'party'
    date: Optional[str] = None  # YYYY-MM-DD


class RoomGuideRequest(BaseModel):
    date: Optional[str] = None  # YYYY-MM-DD
    start_row: int = 3
    end_row: int = 68


class PartyGuideRequest(BaseModel):
    date: Optional[str] = None
    start_row: int = 100
    end_row: int = 117


class GenderStatsResponse(BaseModel):
    date: str
    male_count: int
    female_count: int
    total_participants: int
    balance: Dict[str, Any]


@router.get("/list")
async def get_campaign_list(current_user: User = Depends(get_current_user)):
    """Get list of available independent campaigns"""
    return [
        {
            "id": campaign_id,
            "name": campaign["name"],
            "description": campaign["description"],
            "target_type": campaign["target_type"],
        }
        for campaign_id, campaign in CAMPAIGN_DEFINITIONS.items()
    ]


class IndependentCampaignRequest(BaseModel):
    campaign_type: str
    date: Optional[str] = None  # YYYY-MM-DD
    variables: Optional[Dict[str, Any]] = None


@router.post("/send")
async def send_campaign(
    request: IndependentCampaignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_above),
):
    """
    Send independent campaign by campaign_type

    Args:
        request.campaign_type: One of the predefined campaign types (e.g., "tag_객후", "sms_room")
        request.date: Optional date filter
    """
    campaign_def = CAMPAIGN_DEFINITIONS.get(request.campaign_type)

    if not campaign_def:
        raise HTTPException(status_code=400, detail=f"Unknown campaign type: {request.campaign_type}")

    sms_provider = get_sms_provider()
    manager = TagCampaignManager(db, sms_provider)

    try:
        # Use existing send_campaign but with campaign definition
        if campaign_def["target_type"] == "tag":
            campaign = await manager.send_campaign(
                tag=campaign_def["target_value"],
                template_key=campaign_def["template_key"],
                variables=request.variables,
                sms_type=campaign_def["sms_type"],
                date=request.date,
            )
        else:
            # For non-tag campaigns, pass empty tag to get all matching sms_type
            campaign = await manager.send_campaign(
                tag="",  # Empty tag = all
                template_key=campaign_def["template_key"],
                variables=request.variables,
                sms_type=campaign_def["sms_type"],
                date=request.date,
            )

        return {
            "campaign_id": campaign.id,
            "campaign_type": request.campaign_type,
            "campaign_name": campaign_def["name"],
            "target_count": campaign.target_count,
            "sent_count": campaign.sent_count,
            "failed_count": campaign.failed_count,
            "status": "completed" if campaign.completed_at else "running"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/preview")
async def preview_campaign_targets(
    campaign_type: str,
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Preview targets for a campaign before sending

    Args:
        campaign_type: One of the predefined campaign types
        date: Optional date filter in YYYY-MM-DD format
    """
    campaign_def = CAMPAIGN_DEFINITIONS.get(campaign_type)

    if not campaign_def:
        raise HTTPException(status_code=400, detail=f"Unknown campaign type: {campaign_type}")

    sms_provider = get_sms_provider()
    manager = TagCampaignManager(db, sms_provider)

    # Get targets based on campaign definition
    if campaign_def["target_type"] == "tag":
        targets = manager.get_targets_by_tag(
            tag=campaign_def["target_value"],
            exclude_sent=True,
            sms_type=campaign_def["sms_type"],
            date=date
        )
    else:
        targets = manager.get_targets_by_tag(
            tag="",  # Empty tag = all
            exclude_sent=True,
            sms_type=campaign_def["sms_type"],
            date=date
        )

    return {
        "campaign_type": campaign_type,
        "campaign_name": campaign_def["name"],
        "total_count": len(targets),
        "targets": [
            {
                "id": t.id,
                "name": t.customer_name,
                "phone": t.phone,
                "date": t.date,
                "room_number": t.room_number,
                "tags": t.tags,
            }
            for t in targets
        ]
    }


@router.get("/targets")
async def get_campaign_targets(
    tag: str,
    exclude_sent: bool = True,
    sms_type: str = 'room',
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get SMS targets filtered by tag

    Args:
        tag: Tag to filter by (e.g., "객후", "1,2,2차만")
        exclude_sent: Exclude already-sent numbers
        sms_type: Type of SMS ('room' or 'party')
        date: Date filter in YYYY-MM-DD format
    """
    sms_provider = get_sms_provider()
    manager = TagCampaignManager(db, sms_provider)

    targets = manager.get_targets_by_tag(tag, exclude_sent, sms_type, date=date)

    return {
        "tag": tag,
        "total_count": len(targets),
        "targets": [
            {
                "id": t.id,
                "name": t.customer_name,
                "phone": t.phone,
                "date": t.date,
                "room_number": t.room_number,
                "tags": t.tags,
                "room_sms_sent": t.room_sms_sent,
                "party_sms_sent": t.party_sms_sent
            }
            for t in targets
        ]
    }


@router.post("/send-by-tag")
async def send_by_tag(
    request: CampaignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_above),
):
    """
    Execute tag-based SMS campaign

    Args:
        request: Campaign configuration
    """
    sms_provider = get_sms_provider()
    manager = TagCampaignManager(db, sms_provider)

    try:
        campaign = await manager.send_campaign(
            tag=request.tag,
            template_key=request.template_key,
            variables=request.variables,
            sms_type=request.sms_type,
            date=request.date,
        )

        return {
            "campaign_id": campaign.id,
            "target_count": campaign.target_count,
            "sent_count": campaign.sent_count,
            "failed_count": campaign.failed_count,
            "status": "completed" if campaign.completed_at else "running"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/campaigns/{campaign_id}")
async def get_campaign_stats(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get campaign statistics by ID"""
    sms_provider = get_sms_provider()
    manager = TagCampaignManager(db, sms_provider)

    stats = manager.get_campaign_stats(campaign_id)

    if not stats:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return stats


@router.post("/notifications/room-guide")
async def send_room_guide(
    request: RoomGuideRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_above),
):
    """
    Send room guide messages to confirmed guests

    Automated version of stable-clasp-main roomGuideSMS()
    """
    sms_provider = get_sms_provider()
    storage_provider = get_storage_provider()

    service = NotificationService(db, sms_provider, storage_provider)

    # Parse date
    if request.date:
        date = datetime.strptime(request.date, "%Y-%m-%d")
    else:
        date = datetime.now()

    try:
        campaign = await service.send_room_guide(
            date=date,
            start_row=request.start_row,
            end_row=request.end_row
        )

        return {
            "campaign_id": campaign.id,
            "date": date.strftime("%Y-%m-%d"),
            "target_count": campaign.target_count,
            "sent_count": campaign.sent_count,
            "failed_count": campaign.failed_count,
            "status": "completed"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notifications/party-guide")
async def send_party_guide(
    request: PartyGuideRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_above),
):
    """
    Send party guide messages to unassigned guests

    Automated version of stable-clasp-main partyGuideSMS()
    """
    sms_provider = get_sms_provider()
    storage_provider = get_storage_provider()

    service = NotificationService(db, sms_provider, storage_provider)

    # Parse date
    if request.date:
        date = datetime.strptime(request.date, "%Y-%m-%d")
    else:
        date = datetime.now()

    try:
        campaign = await service.send_party_guide(
            date=date,
            start_row=request.start_row,
            end_row=request.end_row
        )

        return {
            "campaign_id": campaign.id,
            "date": date.strftime("%Y-%m-%d"),
            "target_count": campaign.target_count,
            "sent_count": campaign.sent_count,
            "failed_count": campaign.failed_count,
            "status": "completed"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gender-stats")
async def get_gender_stats(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get gender statistics for a specific date

    Args:
        date: Date in YYYY-MM-DD format (defaults to today)
    """
    storage_provider = get_storage_provider()
    analyzer = GenderAnalyzer(db, storage_provider)

    # Parse date
    if date:
        target_date = datetime.strptime(date, "%Y-%m-%d")
    else:
        target_date = datetime.now()

    # Try to get from database first
    stat = analyzer.get_gender_stats(target_date)

    if not stat:
        # Extract from sheets if not in DB
        stat = await analyzer.extract_gender_stats(target_date)

    if not stat:
        raise HTTPException(status_code=404, detail="Gender stats not found")

    # Calculate balance
    balance = analyzer.calculate_party_balance(stat)

    return {
        "date": stat.date,
        "male_count": stat.male_count,
        "female_count": stat.female_count,
        "total_participants": stat.total_participants,
        "balance": balance,
        "invite_message": analyzer.generate_invite_message(stat)
    }


@router.post("/gender-stats/refresh")
async def refresh_gender_stats(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_above),
):
    """
    Refresh gender statistics from Google Sheets

    Args:
        date: Date in YYYY-MM-DD format (defaults to today)
    """
    storage_provider = get_storage_provider()
    analyzer = GenderAnalyzer(db, storage_provider)

    # Parse date
    if date:
        target_date = datetime.strptime(date, "%Y-%m-%d")
    else:
        target_date = datetime.now()

    try:
        stat = await analyzer.extract_gender_stats(target_date)

        if not stat:
            raise HTTPException(status_code=404, detail="Failed to extract gender stats")

        balance = analyzer.calculate_party_balance(stat)

        return {
            "date": stat.date,
            "male_count": stat.male_count,
            "female_count": stat.female_count,
            "total_participants": stat.total_participants,
            "balance": balance,
            "updated_at": stat.updated_at.isoformat()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_campaign_history(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get campaign sending history"""
    campaigns = (
        db.query(CampaignLog)
        .order_by(CampaignLog.sent_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return [
        {
            "id": c.id,
            "campaign_type": c.campaign_type,
            "target_tag": c.target_tag,
            "target_count": c.target_count,
            "sent_count": c.sent_count,
            "failed_count": c.failed_count,
            "sent_at": c.sent_at.isoformat() if c.sent_at else None,
            "completed_at": c.completed_at.isoformat() if c.completed_at else None,
            "error_message": c.error_message,
        }
        for c in campaigns
    ]


@router.get("/gender-stats/history")
async def get_gender_stats_history(
    days: int = 8,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get gender statistics history for chart"""
    stats = (
        db.query(GenderStat)
        .order_by(GenderStat.date.desc())
        .limit(days)
        .all()
    )

    # Return in chronological order
    stats.reverse()

    return [
        {
            "date": s.date,
            "male_count": s.male_count,
            "female_count": s.female_count,
            "total_participants": s.total_participants,
        }
        for s in stats
    ]


@router.get("/templates")
async def get_templates(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get all message templates"""
    templates = db.query(MessageTemplate).filter_by(active=True).all()

    return [
        {
            "id": t.id,
            "key": t.key,
            "name": t.name,
            "content": t.content,
            "variables": t.variables,
            "category": t.category,
        }
        for t in templates
    ]
