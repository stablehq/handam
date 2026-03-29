"""
SQLAlchemy database models
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Float, Enum, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship, declared_attr
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone
import enum


def utc_now():
    return datetime.now(timezone.utc)

Base = declarative_base()


class TenantMixin:
    """Mixin that adds tenant_id to models requiring tenant isolation."""
    @declared_attr
    def tenant_id(cls):
        return Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)


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


class Message(TenantMixin, Base):
    """SMS message records"""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String(100))  # indexed via uq_tenant_message_id (tenant_id, message_id)
    direction = Column(Enum(MessageDirection, name="message_direction", native_enum=False), nullable=False, index=True)
    from_ = Column("from_phone", String(20), nullable=False, index=True)
    to = Column(String(20), nullable=False, index=True)
    content = Column("message", Text, nullable=False)
    status = Column(Enum(MessageStatus, name="message_status", native_enum=False), default=MessageStatus.PENDING)
    created_at = Column(DateTime, default=utc_now)

    # Auto-response metadata
    auto_response = Column(Text, nullable=True)
    auto_response_confidence = Column(Float, nullable=True)
    needs_review = Column("is_needs_review", Boolean, default=False, index=True)
    response_source = Column(String(20), nullable=True, index=True)  # 'rule', 'llm', 'manual'

    __table_args__ = (
        UniqueConstraint("tenant_id", "message_id", name="uq_tenant_message_id"),
    )


class Reservation(TenantMixin, Base):
    """Reservation records - Extended for SMS system integration"""

    __tablename__ = "reservations"

    # Core fields (original)
    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(100), nullable=True)  # indexed via uq_tenant_external_id (tenant_id, external_id)
    customer_name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False, index=True)
    check_in_date = Column("date", String(20), nullable=False, index=True)  # YYYY-MM-DD  # TODO: PostgreSQL 전환 시 Date 타입으로 변경
    check_in_time = Column("time", String(10), nullable=False)  # HH:MM  # TODO: PostgreSQL 전환 시 Time 타입으로 변경
    status = Column(Enum(ReservationStatus, name="reservation_status", native_enum=False), default=ReservationStatus.PENDING, index=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    booking_source = Column("source", String(20), default="manual")  # 'naver', 'manual', 'phone'
    section = Column(String(20), default="unassigned")  # 'room', 'unassigned', 'party'

    # Naver Booking integration fields
    naver_booking_id = Column(String(50), nullable=True, index=True)
    naver_biz_item_id = Column(String(50), nullable=True)  # Room type ID
    visitor_name = Column(String(100), nullable=True)  # Alternative contact
    visitor_phone = Column(String(20), nullable=True)

    # Room assignment fields
    room_number = Column(String(20), nullable=True)  # e.g., A101, B205
    room_password = Column(String(20), nullable=True)  # Auto-generated password
    naver_room_type = Column("room_info", String(200), nullable=True)  # Room type description

    # User demographics (from Naver user info)
    gender = Column(String(10), nullable=True)  # '남', '여'
    age_group = Column(String(20), nullable=True)  # '20대', '30대', etc.
    visit_count = Column(Integer, default=1)

    # Room occupant counts (mixed gender support)
    male_count = Column(Integer, nullable=True)   # 남성 투숙 인원
    female_count = Column(Integer, nullable=True) # 여성 투숙 인원

    # Party/dormitory fields
    party_size = Column("party_participants", Integer, default=0)
    party_type = Column(String(10), nullable=True)  # '1'=1차만, '2'=1+2차, '2차만'=2차만

    # Multi-booking flag
    is_multi_booking = Column(Boolean, default=False)

    # Consecutive stay (연박) linking
    stay_group_id = Column(String(36), nullable=True, index=True)   # UUID — same value for all reservations in a consecutive stay group
    stay_group_order = Column(Integer, nullable=True)                # Order within group (0, 1, 2...)
    is_last_in_group = Column(Boolean, nullable=True)                # True: last reservation in consecutive stay group
    is_long_stay = Column(Boolean, default=False)                    # 연박자(2박+) OR 연장자(stay_group_id) 통합

    # Extended Naver booking data
    check_out_date = Column("end_date", String(20), nullable=True)  # checkout date YYYY-MM-DD  # TODO: PostgreSQL 전환 시 Date 타입으로 변경
    biz_item_name = Column(String(200), nullable=True)  # product/room name from Naver
    booking_count = Column(Integer, default=1)  # quantity
    booking_options = Column(Text, nullable=True)  # JSON string from bookingOptionJson
    special_requests = Column("custom_form_input", Text, nullable=True)  # JSON string from customFormInputJson (요청사항)
    total_price = Column(Integer, nullable=True)  # total payment amount
    confirmed_at = Column(String(50), nullable=True)  # ISO string — TODO: Alembic 마이그레이션 후 DateTime 전환
    cancelled_at = Column(String(50), nullable=True)  # ISO string — TODO: Alembic 마이그레이션 후 DateTime 전환

    # Per-date room assignments relationship
    room_assignments = relationship("RoomAssignment", back_populates="reservation", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_tenant_external_id"),
    )


# DEACTIVATED: LLM/RAG auto-response feature — preserved for Alembic migration compatibility
class Rule(TenantMixin, Base):
    """Auto-response rules"""

    __tablename__ = "rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    pattern = Column(String(500), nullable=False)  # Regex pattern
    response = Column(Text, nullable=False)
    priority = Column(Integer, default=0)  # Higher = higher priority
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


# DEACTIVATED: LLM/RAG auto-response feature — preserved for Alembic migration compatibility
class Document(TenantMixin, Base):
    """Knowledge base documents for RAG"""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(200), nullable=False)
    content = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=True)
    uploaded_at = Column(DateTime, default=utc_now)
    is_indexed = Column(Boolean, default=False)  # ChromaDB indexing status


class MessageTemplate(TenantMixin, Base):
    """Message templates for SMS campaigns"""

    __tablename__ = "message_templates"

    id = Column(Integer, primary_key=True, index=True)
    template_key = Column("key", String(100), nullable=False)
    name = Column(String(200), nullable=False)
    short_label = Column(String(10), nullable=True)  # 2-4 char abbreviation for chip display
    content = Column(Text, nullable=False)
    variables = Column(Text, nullable=True)  # JSON list of variable names
    category = Column(String(50), nullable=True)  # 'room_guide', 'party_guide', etc.
    is_active = Column(Boolean, default=True)
    participant_buffer = Column(Integer, default=0)  # 참여인원 버퍼 (+N명)
    male_buffer = Column(Integer, default=0)           # 남성 인원 버퍼 (+N명)
    female_buffer = Column(Integer, default=0)          # 여성 인원 버퍼 (+N명)
    gender_ratio_buffers = Column(Text, nullable=True)  # JSON: {"male_high": {"m": 2, "f": 6}, "female_high": {"m": 6, "f": 6}}
    round_unit = Column(Integer, default=0)             # 반올림 단위 (0=미사용, 10=10명 단위)
    round_mode = Column(String, default='ceil')          # 반올림 모드: ceil(올림), round(반올림), floor(내림)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def get_buffer_vars(self) -> dict:
        """Return template buffer settings as custom_vars dict for SMS rendering."""
        return {
            '_participant_buffer': self.participant_buffer or 0,
            '_male_buffer': self.male_buffer or 0,
            '_female_buffer': self.female_buffer or 0,
            '_gender_ratio_buffers': self.gender_ratio_buffers,
            '_round_unit': self.round_unit or 0,
            '_round_mode': self.round_mode or 'ceil',
        }

    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_tenant_template_key"),
    )


class ReservationSmsAssignment(TenantMixin, Base):
    """Join table tracking SMS template assignments per reservation"""

    __tablename__ = "reservation_sms_assignments"

    id = Column(Integer, primary_key=True, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True)
    template_key = Column(String(100), nullable=False, index=True)
    assigned_at = Column(DateTime, default=utc_now)
    sent_at = Column(DateTime, nullable=True)  # null=pending, value=sent
    assigned_by = Column(String(20), default="auto")  # 'auto', 'manual', 'schedule'

    date = Column(String(20), nullable=False, default='')  # YYYY-MM-DD, 발송 대상 날짜

    reservation = relationship("Reservation", backref="sms_assignments")

    __table_args__ = (
        UniqueConstraint("reservation_id", "template_key", "date", name="uq_res_sms_template_date"),
    )


class CampaignLog(TenantMixin, Base):
    """SMS campaign execution logs
    DEPRECATED: ActivityLog로 완전 대체됨. 신규 코드에서 생성 금지.
    기존 데이터 유지를 위해 모델은 보존하되, 조회 전용으로만 사용.
    """

    __tablename__ = "campaign_logs"

    id = Column(Integer, primary_key=True, index=True)
    campaign_type = Column(String(50), nullable=False)  # 'tag_based', 'room_guide', 'party_guide'
    target_tag = Column(String(50), nullable=True)
    target_count = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    sent_at = Column(DateTime, default=utc_now)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    extra_data = Column("metadata", Text, nullable=True)  # JSON for additional info


class GenderStat(TenantMixin, Base):
    """Gender statistics for party planning"""

    __tablename__ = "gender_stats"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String(20), nullable=False, index=True)  # YYYY-MM-DD
    male_count = Column(Integer, default=0)
    female_count = Column(Integer, default=0)
    participant_count = Column("total_participants", Integer, default=0)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class RoomBizItemLink(TenantMixin, Base):
    """N:M association table: Room <-> NaverBizItem"""

    __tablename__ = "room_biz_item_links"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    biz_item_id = Column(String(100), nullable=False, index=True)
    male_priority = Column(Integer, default=0)      # 남성 배정 순서 (낮을수록 먼저, 0=미설정)
    female_priority = Column(Integer, default=0)     # 여성 배정 순서 (낮을수록 먼저, 0=미설정)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("room_id", "biz_item_id", name="uq_room_biz_item"),
    )

    # Relationships
    room = relationship("Room", back_populates="biz_item_links")
    biz_item = relationship(
        "NaverBizItem",
        primaryjoin="and_(foreign(RoomBizItemLink.biz_item_id) == NaverBizItem.biz_item_id, foreign(RoomBizItemLink.tenant_id) == NaverBizItem.tenant_id)",
        lazy="joined",
        viewonly=True,
    )


class Building(TenantMixin, Base):
    """건물 관리 (본관, 별관, 로하스 등)"""

    __tablename__ = "buildings"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)  # "본관", "별관", "로하스"
    description = Column(String(200), nullable=True)  # 건물 설명/주소
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tenant_building_name"),
    )

    # Relationships
    rooms = relationship("Room", back_populates="building")


class RoomGroup(TenantMixin, Base):
    """Visual grouping of rooms with box borders"""

    __tablename__ = "room_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    sort_order = Column(Integer, default=0)
    color = Column(String(20), nullable=True)  # optional border color override
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tenant_room_group_name"),
    )

    rooms = relationship("Room", back_populates="room_group")


class Room(TenantMixin, Base):
    """Room configuration for room assignment"""

    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    room_number = Column(String(20), nullable=False, index=True)  # e.g., A101, B205, 별관 (duplicates allowed)
    room_type = Column(String(50), nullable=False)  # e.g., 더블룸, 트윈룸, 패밀리룸
    base_capacity = Column(Integer, default=2)  # 기준 인원
    max_capacity = Column(Integer, default=4)  # 최대 인원
    is_active = Column(Boolean, default=True)  # Active/inactive flag
    sort_order = Column(Integer, default=0)  # Display order
    naver_biz_item_id = Column(String(50), nullable=True)  # Deprecated: use biz_item_links instead
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=True)
    room_group_id = Column(Integer, ForeignKey("room_groups.id", ondelete="SET NULL"), nullable=True)
    is_dormitory = Column(Boolean, default=False)
    bed_capacity = Column("dormitory_beds", Integer, default=1)
    door_password = Column("default_password", String(20), nullable=True)  # 객실 고정 비밀번호
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # N:M relationship to NaverBizItem via RoomBizItemLink
    biz_item_links = relationship("RoomBizItemLink", back_populates="room", cascade="all, delete-orphan")
    building = relationship("Building", back_populates="rooms")
    room_group = relationship("RoomGroup", back_populates="rooms")


class RoomAssignment(TenantMixin, Base):
    """Per-date room assignment records for reservations"""

    __tablename__ = "room_assignments"
    __table_args__ = (
        UniqueConstraint("reservation_id", "date", name="uq_room_assignment_res_date"),
        Index("ix_room_assignment_date_room", "date", "room_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(String(20), nullable=False)  # YYYY-MM-DD
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    room_password = Column(String(20), nullable=True)
    assigned_by = Column(String(10), default="auto")  # 'auto' or 'manual'
    bed_order = Column(Integer, default=0)  # 도미토리 행 순서 (1부터 시작, 0=미지정)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    reservation = relationship("Reservation", back_populates="room_assignments")
    room = relationship("Room")


class NaverBizItem(TenantMixin, Base):
    """Naver Smart Place product/room types"""

    __tablename__ = "naver_biz_items"

    id = Column(Integer, primary_key=True, index=True)
    biz_item_id = Column(String(50), nullable=False, index=True)  # Naver bizItemId
    name = Column(String(200), nullable=False)  # Product name from Naver
    display_name = Column(String(200), nullable=True)  # 관리자 지정 표시명 (동기화 시 유지)
    biz_item_type = Column(String(50), nullable=True)  # STANDARD etc.
    is_exposed = Column(Boolean, default=True)  # 네이버 노출 상태
    is_active = Column(Boolean, default=True)
    default_capacity = Column(Integer, default=1, nullable=True)  # 예약 단위 기본 인원 (도미토리=1, 개인실=2~3)
    section_hint = Column(String(20), nullable=True)  # 'party' | 'room' | null(=unassigned)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "biz_item_id", name="uq_tenant_biz_item_id"),
    )


class TemplateSchedule(TenantMixin, Base):
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
    active_start_hour = Column(Integer, nullable=True)  # 활성화 시작 시간 (0-23), hourly/interval 타입에서 사용
    active_end_hour = Column(Integer, nullable=True)    # 활성화 종료 시간 (0-23), hourly/interval 타입에서 사용
    timezone = Column(String(50), default="Asia/Seoul")

    # Target filters
    filters = Column(Text, nullable=True)  # JSON array: [{"type": "tag", "value": "객후"}, {"type": "building", "value": "1"}]

    # SMS tracking
    exclude_sent = Column("is_exclude_sent", Boolean, default=True)  # Prevent duplicate sending

    # Activation
    is_active = Column(Boolean, default=True)

    # Metadata
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)

    target_mode = Column(String(20), default='once')  # 'once' | 'daily' | 'last_day' (체크아웃 전날만)
    once_per_stay = Column("is_once_per_stay", Boolean, default=False)  # True: 연박 그룹 내 최초 체크인에만 발송
    date_target = Column(String(30), nullable=True)   # 'today' | 'tomorrow' | 'today_checkout' | 'tomorrow_checkout'
    stay_filter = Column(String(20), nullable=True)    # null(include) | 'exclude'(no consecutive)

    # Send condition (optional — standard schedules only)
    send_condition_date = Column(String(20), nullable=True)    # 'today' | 'tomorrow'
    send_condition_ratio = Column(Float, nullable=True)        # N:1 의 N
    send_condition_operator = Column(String(10), nullable=True) # 'gte' | 'lte'

    # Event schedule fields
    schedule_category = Column(String(20), default='standard')  # 'standard' | 'event'
    hours_since_booking = Column(Integer, nullable=True)  # 예약 확정 후 N시간 이내 (이벤트 필수)
    gender_filter = Column(String(10), nullable=True)  # 'male' | 'female' | NULL(전체)
    max_checkin_days = Column(Integer, nullable=True)  # 최대 N일 이내 체크인
    expires_after_days = Column(Integer, nullable=True)  # 생성 후 N일간 운영 (UI용)
    expires_at = Column(DateTime, nullable=True)  # 실제 만료 시각 (생성 시 자동 계산)

    # Relationship
    template = relationship("MessageTemplate", backref="schedules")


class ActivityLog(TenantMixin, Base):
    """시스템 활동 로그 — 주요 변경사항 기록"""

    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    activity_type = Column("type", String(50), nullable=False, index=True)  # room_assign, sms_template, sms_manual, sms_campaign, naver_sync, schedule_execute
    title = Column(String(200), nullable=False)  # 사람이 읽을 수 있는 제목
    detail = Column(Text, nullable=True)  # JSON 상세 정보
    status = Column(String(20), default="success", index=True)  # success, failed, partial
    target_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now, index=True)
    created_by = Column(String(50), nullable=True)  # username 또는 "system"


class PartyCheckin(TenantMixin, Base):
    """Party check-in records per date"""

    __tablename__ = "party_checkins"
    __table_args__ = (
        UniqueConstraint("reservation_id", "date", name="uq_party_checkin_res_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    checked_in_at = Column(DateTime, nullable=True)

    reservation = relationship("Reservation", backref="party_checkins")


class ReservationDailyInfo(TenantMixin, Base):
    """날짜별 예약 부가 정보 (파티 참여 등)"""
    __tablename__ = "reservation_daily_info"

    id = Column(Integer, primary_key=True, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False)
    date = Column(String(20), nullable=False)  # YYYY-MM-DD
    party_type = Column(String(20), nullable=True)  # '1'=1차만, '2'=1+2차, '2차만'=2차만, 'X'=미참여
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    reservation = relationship("Reservation", backref="daily_info")

    __table_args__ = (
        UniqueConstraint("reservation_id", "date", name="uq_reservation_daily_info"),
        Index("ix_reservation_daily_date", "reservation_id", "date"),
    )


class User(Base):
    """User accounts for authentication"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password = Column(String(200), nullable=False)
    name = Column(String(100), nullable=False)
    role = Column(Enum(UserRole, name="user_role", native_enum=False), nullable=False, default=UserRole.STAFF)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class ParticipantSnapshot(TenantMixin, Base):
    """Daily participant count snapshot for consistent SMS template variables"""
    __tablename__ = "participant_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String(20), nullable=False)  # YYYY-MM-DD, indexed via uq_tenant_snapshot_date (tenant_id, date)
    male_count = Column(Integer, default=0)
    female_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "date", name="uq_tenant_snapshot_date"),
    )


class Tenant(Base):
    """펜션(테넌트) 마스터 테이블"""
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(50), unique=True, nullable=False, index=True)  # 'handam', 'stable'
    name = Column(String(100), nullable=False)  # '한담 펜션', '스테이블 펜션'
    naver_business_id = Column(String(50), nullable=True)
    naver_cookie = Column(Text, nullable=True)
    naver_email = Column(String(200), nullable=True)
    naver_password = Column(String(200), nullable=True)
    aligo_sender = Column(String(20), nullable=True)  # 펜션별 발신번호
    aligo_testmode = Column(Boolean, default=True)  # True=테스트모드(실제 미발송), False=실제 발송
    chip_priority_keys = Column(Text, nullable=True)  # JSON array of template_keys for chip display order
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class UserTenantRole(Base):
    """유저별 테넌트 접근 매핑"""
    __tablename__ = "user_tenant_roles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),
    )

    user = relationship("User", backref="tenant_roles")
    tenant = relationship("Tenant")


# ---------------------------------------------------------------------------
# Register tenant models for automatic SELECT filtering
# ---------------------------------------------------------------------------
from app.db.tenant_context import register_tenant_model as _register  # noqa: E402

for _model in [
    Message, Reservation, Rule, Document, MessageTemplate, ReservationSmsAssignment,
    CampaignLog, GenderStat, RoomBizItemLink, Building, RoomGroup, Room, RoomAssignment,
    NaverBizItem, TemplateSchedule, ActivityLog, PartyCheckin, ReservationDailyInfo,
    ParticipantSnapshot,
]:
    _register(_model)
