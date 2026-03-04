"""
SQLAlchemy database models
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Float, Enum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import enum

Base = declarative_base()


class MessageDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    RECEIVED = "received"


class ReservationStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class Message(Base):
    """SMS message records"""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String(100), unique=True, index=True)
    direction = Column(Enum(MessageDirection), nullable=False)
    from_ = Column("from_phone", String(20), nullable=False)
    to = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(Enum(MessageStatus), default=MessageStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Auto-response metadata
    auto_response = Column(Text, nullable=True)
    auto_response_confidence = Column(Float, nullable=True)
    needs_review = Column(Boolean, default=False)
    response_source = Column(String(20), nullable=True)  # 'rule', 'llm', 'manual'


class Reservation(Base):
    """Reservation records - Extended for SMS system integration"""

    __tablename__ = "reservations"

    # Core fields (original)
    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(100), unique=True, nullable=True, index=True)
    customer_name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False)
    date = Column(String(20), nullable=False)  # YYYY-MM-DD
    time = Column(String(10), nullable=False)  # HH:MM
    status = Column(Enum(ReservationStatus), default=ReservationStatus.PENDING)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    source = Column(String(20), default="manual")  # 'naver', 'manual', 'phone'

    # Naver Booking integration fields
    naver_booking_id = Column(String(50), nullable=True, index=True)
    naver_biz_item_id = Column(String(50), nullable=True)  # Room type ID
    visitor_name = Column(String(100), nullable=True)  # Alternative contact
    visitor_phone = Column(String(20), nullable=True)

    # Room assignment fields
    room_number = Column(String(20), nullable=True)  # e.g., A101, B205
    room_password = Column(String(20), nullable=True)  # Auto-generated password
    room_info = Column(String(200), nullable=True)  # Room type description

    # User demographics (from Naver user info)
    gender = Column(String(10), nullable=True)  # '남', '여'
    age_group = Column(String(20), nullable=True)  # '20대', '30대', etc.
    visit_count = Column(Integer, default=1)

    # Party/dormitory fields
    party_participants = Column(Integer, default=0)
    party_gender = Column(String(10), nullable=True)  # For dormitory assignments

    # Tag system (comma-separated tags)
    tags = Column(Text, nullable=True)  # JSON or comma-separated: "객후,1초,2차만"

    # SMS sending tracking
    room_sms_sent = Column(Boolean, default=False)
    party_sms_sent = Column(Boolean, default=False)
    room_sms_sent_at = Column(DateTime, nullable=True)
    party_sms_sent_at = Column(DateTime, nullable=True)
    sent_sms_types = Column(Text, nullable=True)  # Comma-separated list: "객후,파티안내,객실안내"

    # Google Sheets sync tracking
    sheets_row_number = Column(Integer, nullable=True)
    sheets_last_synced = Column(DateTime, nullable=True)

    # Multi-booking flag
    is_multi_booking = Column(Boolean, default=False)


class Rule(Base):
    """Auto-response rules"""

    __tablename__ = "rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    pattern = Column(String(500), nullable=False)  # Regex pattern
    response = Column(Text, nullable=False)
    priority = Column(Integer, default=0)  # Higher = higher priority
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Document(Base):
    """Knowledge base documents for RAG"""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(200), nullable=False)
    content = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    indexed = Column(Boolean, default=False)  # ChromaDB indexing status


class MessageTemplate(Base):
    """Message templates for SMS campaigns"""

    __tablename__ = "message_templates"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    variables = Column(Text, nullable=True)  # JSON list of variable names
    category = Column(String(50), nullable=True)  # 'room_guide', 'party_guide', etc.
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CampaignLog(Base):
    """SMS campaign execution logs"""

    __tablename__ = "campaign_logs"

    id = Column(Integer, primary_key=True, index=True)
    campaign_type = Column(String(50), nullable=False)  # 'tag_based', 'room_guide', 'party_guide'
    target_tag = Column(String(50), nullable=True)
    target_count = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    sent_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    extra_data = Column("metadata", Text, nullable=True)  # JSON for additional info


class GenderStat(Base):
    """Gender statistics for party planning"""

    __tablename__ = "gender_stats"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String(20), nullable=False, index=True)  # YYYY-MM-DD
    male_count = Column(Integer, default=0)
    female_count = Column(Integer, default=0)
    total_participants = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Room(Base):
    """Room configuration for room assignment"""

    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    room_number = Column(String(20), nullable=False, index=True)  # e.g., A101, B205, 별관 (duplicates allowed)
    room_type = Column(String(50), nullable=False)  # e.g., 더블룸, 트윈룸, 패밀리룸
    base_capacity = Column(Integer, default=2)  # 기준 인원
    max_capacity = Column(Integer, default=4)  # 최대 인원
    is_active = Column(Boolean, default=True)  # Active/inactive flag
    sort_order = Column(Integer, default=0)  # Display order
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TemplateSchedule(Base):
    """Template-based scheduled messaging"""

    __tablename__ = "template_schedules"

    # Basic information
    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey('message_templates.id'), nullable=False)
    schedule_name = Column(String(200), nullable=False)

    # Schedule configuration
    schedule_type = Column(String(20), nullable=False)  # 'daily', 'weekly', 'hourly', 'interval'
    hour = Column(Integer, nullable=True)  # 0-23
    minute = Column(Integer, nullable=True)  # 0-59
    day_of_week = Column(String(20), nullable=True)  # 'mon,tue,wed,...'
    interval_minutes = Column(Integer, nullable=True)  # For interval type
    timezone = Column(String(50), default="Asia/Seoul")

    # Target filters
    target_type = Column(String(50), nullable=False)  # 'all', 'tag', 'room_assigned', 'party_only'
    target_value = Column(String(200), nullable=True)  # Tag name if target_type='tag'
    date_filter = Column(String(20), nullable=True)  # 'today', 'tomorrow', 'YYYY-MM-DD', null

    # SMS tracking
    sms_type = Column(String(20), default='room')  # 'room' or 'party'
    exclude_sent = Column(Boolean, default=True)  # Prevent duplicate sending

    # Activation
    active = Column(Boolean, default=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)

    # Relationship
    template = relationship("MessageTemplate", backref="schedules")
