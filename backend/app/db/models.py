"""
SQLAlchemy database models
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Float, Enum, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import enum

Base = declarative_base()


class UserRole(str, enum.Enum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    STAFF = "staff"


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
    direction = Column(Enum(MessageDirection, name="message_direction", native_enum=False), nullable=False)
    from_ = Column("from_phone", String(20), nullable=False)
    to = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(Enum(MessageStatus, name="message_status", native_enum=False), default=MessageStatus.PENDING)
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
    status = Column(Enum(ReservationStatus, name="reservation_status", native_enum=False), default=ReservationStatus.PENDING)
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

    # Room occupant counts (mixed gender support)
    male_count = Column(Integer, nullable=True)   # 남성 투숙 인원
    female_count = Column(Integer, nullable=True) # 여성 투숙 인원

    # Party/dormitory fields
    party_participants = Column(Integer, default=0)
    party_gender = Column(String(10), nullable=True)  # For dormitory assignments
    party_type = Column(String(10), nullable=True)  # '1'=1차만, '2'=1+2차, '2차만'=2차만

    # Tag system (comma-separated tags)
    tags = Column(Text, nullable=True)  # JSON or comma-separated: "객후,1초,2차만"

    # SMS sending tracking
    room_sms_sent = Column(Boolean, default=False)
    party_sms_sent = Column(Boolean, default=False)
    room_sms_sent_at = Column(DateTime, nullable=True)
    party_sms_sent_at = Column(DateTime, nullable=True)
    sent_sms_types = Column(Text, nullable=True)  # Comma-separated list: "객후,파티안내,객실안내"

    # Multi-booking flag
    is_multi_booking = Column(Boolean, default=False)

    # Extended Naver booking data
    end_date = Column(String(20), nullable=True)  # checkout date YYYY-MM-DD
    biz_item_name = Column(String(200), nullable=True)  # product/room name from Naver
    booking_count = Column(Integer, default=1)  # quantity
    booking_options = Column(Text, nullable=True)  # JSON string from bookingOptionJson
    custom_form_input = Column(Text, nullable=True)  # JSON string from customFormInputJson (요청사항)
    total_price = Column(Integer, nullable=True)  # total payment amount
    confirmed_datetime = Column(String(50), nullable=True)  # confirmation datetime ISO string
    cancelled_datetime = Column(String(50), nullable=True)  # cancellation datetime ISO string

    # Per-date room assignments relationship
    room_assignments = relationship("RoomAssignment", back_populates="reservation", cascade="all, delete-orphan")


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
    short_label = Column(String(10), nullable=True)  # 2-4 char abbreviation for chip display
    content = Column(Text, nullable=False)
    variables = Column(Text, nullable=True)  # JSON list of variable names
    category = Column(String(50), nullable=True)  # 'room_guide', 'party_guide', etc.
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReservationSmsAssignment(Base):
    """Join table tracking SMS template assignments per reservation"""

    __tablename__ = "reservation_sms_assignments"

    id = Column(Integer, primary_key=True, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True)
    template_key = Column(String(100), nullable=False, index=True)
    assigned_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)  # null=pending, value=sent
    assigned_by = Column(String(20), default="auto")  # 'auto', 'manual', 'schedule'

    reservation = relationship("Reservation", backref="sms_assignments")

    __table_args__ = (
        UniqueConstraint("reservation_id", "template_key", name="uq_res_sms_template"),
    )


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
    naver_biz_item_id = Column(String(50), nullable=True)  # Linked Naver product ID
    is_dormitory = Column(Boolean, default=False)
    dormitory_beds = Column(Integer, default=1)
    default_password = Column(String(20), nullable=True)  # 객실 고정 비밀번호
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RoomAssignment(Base):
    """Per-date room assignment records for reservations"""

    __tablename__ = "room_assignments"
    __table_args__ = (
        UniqueConstraint("reservation_id", "date", name="uq_room_assignment_res_date"),
        Index("ix_room_assignment_date_room", "date", "room_number"),
    )

    id = Column(Integer, primary_key=True, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(String(20), nullable=False)  # YYYY-MM-DD
    room_number = Column(String(20), nullable=False)
    room_password = Column(String(20), nullable=True)
    assigned_by = Column(String(10), default="auto")  # 'auto' or 'manual'
    sms_sent = Column(Boolean, default=False)
    sms_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    reservation = relationship("Reservation", back_populates="room_assignments")


class NaverBizItem(Base):
    """Naver Smart Place product/room types"""

    __tablename__ = "naver_biz_items"

    id = Column(Integer, primary_key=True, index=True)
    biz_item_id = Column(String(50), unique=True, nullable=False, index=True)  # Naver bizItemId
    name = Column(String(200), nullable=False)  # Product name from Naver
    biz_item_type = Column(String(50), nullable=True)  # STANDARD etc.
    is_exposed = Column(Boolean, default=True)  # 네이버 노출 상태
    is_active = Column(Boolean, default=True)
    is_dormitory = Column(Boolean, default=False)  # 도미토리 상품 여부
    dormitory_beds = Column(Integer, nullable=True)  # 도미토리 인실 수 (4, 8 등)
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


class User(Base):
    """User accounts for authentication"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password = Column(String(200), nullable=False)
    name = Column(String(100), nullable=False)
    role = Column(Enum(UserRole, name="user_role", native_enum=False), nullable=False, default=UserRole.STAFF)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
