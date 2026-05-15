"""surcharge.py — 인원 초과 추가요금 SMS 칩 자동 조정 (2-type).

객실 타입에 따라 2개 스케줄 중 하나로 칩 생성:
  - surcharge_standard: 일반 객실 초과
  - surcharge_double:   더블 객실 초과 (업그레이드비 포함)

단가/박수는 템플릿 변수로 동적 계산됨 (templates/variables.py 참조).
"""
import logging
from typing import Optional, List
from sqlalchemy.orm import Session

from app.db.models import (
    Reservation,
    Room,
    RoomAssignment,
    TemplateSchedule,
    RoomBizItemLink,
    NaverBizItem,
)
from app.diag_logger import diag

logger = logging.getLogger(__name__)

# 더블룸으로 취급할 네이버 biz_item_id (현재 stable 테넌트 기준)
DOUBLE_ROOM_BIZ_ITEM_IDS = {'4779024'}  # [특가] 오션뷰 더블룸 (1인~2인, 단독사용)

SURCHARGE_STANDARD = 'surcharge_standard'
SURCHARGE_DOUBLE = 'surcharge_double'
_ALL_SURCHARGE_TYPES = (SURCHARGE_STANDARD, SURCHARGE_DOUBLE)


def _is_double_room(db: Session, room: Room) -> bool:
    """방에 연결된 biz_item_id 중 DOUBLE_ROOM_BIZ_ITEM_IDS 에 속한 게 있으면 True."""
    links = db.query(RoomBizItemLink).filter(
        RoomBizItemLink.room_id == room.id
    ).all()
    for link in links:
        if link.biz_item_id in DOUBLE_ROOM_BIZ_ITEM_IDS:
            return True
    return False


def _is_dormitory_reservation(db: Session, reservation) -> bool:
    """예약의 naver_biz_item_id 매핑이 모두 도미토리 객실이면 True.

    도미토리 상품 손님은 침대 단가로 결제했으므로, 운영 편의로 일반실에
    배정해도 인원 초과 추가요금을 청구하지 않는다.
    biz_item 미상/매핑 없음은 False (보수적으로 일반실 룰 유지).
    """
    biz_id = getattr(reservation, 'naver_biz_item_id', None)
    if not biz_id:
        return False
    room_ids = [
        l.room_id for l in db.query(RoomBizItemLink)
        .filter(RoomBizItemLink.biz_item_id == str(biz_id))
        .all()
    ]
    if not room_ids:
        return False
    rooms = db.query(Room).filter(Room.id.in_(room_ids)).all()
    return bool(rooms) and all(r.is_dormitory for r in rooms)


def _find_schedule(db: Session, custom_type: str) -> Optional[TemplateSchedule]:
    return db.query(TemplateSchedule).filter(
        TemplateSchedule.schedule_category == 'custom_schedule',
        TemplateSchedule.custom_type == custom_type,
        TemplateSchedule.is_active == True,
    ).first()


def compute_guest_count(reservation) -> int:
    """예약의 게스트 인원 계산 (party_size 우선, 없으면 male+female, 없으면 1)."""
    return (
        getattr(reservation, 'party_size', None)
        or (reservation.male_count or 0) + (reservation.female_count or 0)
        or 1
    )


def resolve_product_base_capacity(db, reservation, room) -> int:
    """기준 인원 결정 — 예약 상품(NaverBizItem) 의 default_capacity 우선.

    객실 업그레이드(예약 상품보다 더 큰 객실 배정) 케이스에서도 예약 시점 기준으로
    초과 판정해야 한다. 예: 더블룸(default=2) 예약 → 스위트(base=4) 배정 → 3명 →
    추1 (이전 코드는 객실 base=4 기준으로 추0 처리하던 bug).

    biz_item 없거나 default_capacity 미설정인 경우는 객실 base 로 fallback.

    Public API — surcharge.py 외부 (room_upgrade_review 등) 에서도 같은 기준이 필요.
    """
    biz_id = getattr(reservation, 'naver_biz_item_id', None)
    if biz_id:
        item = db.query(NaverBizItem).filter(NaverBizItem.biz_item_id == str(biz_id)).first()
        if item and item.default_capacity:
            return item.default_capacity
    return (room.base_capacity if room else 0) or 0


def compute_excess(db, reservation, room) -> int:
    """기준 인원 초과분 계산 — 예약 상품 default_capacity 대비."""
    if room is None:
        return 0
    return max(0, compute_guest_count(reservation) - resolve_product_base_capacity(db, reservation, room))


def reconcile_surcharge(
    db: Session,
    reservation_id: int,
    date: str,
    room_id: Optional[int] = None,
) -> None:
    """예약-날짜 기준 surcharge 칩 재조정.

    객실 타입에 따라 surcharge_standard 또는 surcharge_double 칩을 생성.
    반대 타입의 기존 칩은 삭제. excess <= 0 이면 양쪽 모두 삭제.
    """
    diag("surcharge.reconcile.enter", level="verbose", res_id=reservation_id, date=date)
    try:
        # 1. RoomAssignment 조회
        q = db.query(RoomAssignment).filter(
            RoomAssignment.reservation_id == reservation_id,
            RoomAssignment.date == date,
        )
        if room_id is not None:
            q = q.filter(RoomAssignment.room_id == room_id)
        assignment = q.first()
        if not assignment:
            _delete_all_surcharge_chips(db, reservation_id, date)
            return

        # 2. Room 조회 + 도미토리 스킵
        room = db.query(Room).filter(Room.id == assignment.room_id).first()
        if not room or room.is_dormitory:
            _delete_all_surcharge_chips(db, reservation_id, date)
            return

        # 3. 객실 타입 판단
        is_double = _is_double_room(db, room)
        target_type = SURCHARGE_DOUBLE if is_double else SURCHARGE_STANDARD
        other_type = SURCHARGE_STANDARD if is_double else SURCHARGE_DOUBLE

        # 4. 초과 계산 (variables.py 와 공유 helper)
        reservation = db.query(Reservation).filter(
            Reservation.id == reservation_id
        ).first()
        if not reservation:
            return

        # 도미토리 상품 예약을 운영 편의로 일반실에 배정한 경우
        # 손님은 침대 단가로 결제했으므로 추가요금 청구 부적절.
        if _is_dormitory_reservation(db, reservation):
            _delete_all_surcharge_chips(db, reservation_id, date)
            return

        excess = compute_excess(db, reservation, room)

        # 5. 칩 생성/삭제
        if excess > 0:
            _ensure_chip(db, reservation_id, date, target_type)
            _remove_chip(db, reservation_id, date, other_type)
            diag("surcharge.chip_applied", level="verbose",
                 res_id=reservation_id, date=date,
                 type=target_type, excess=excess, is_double=is_double)
        else:
            _remove_chip(db, reservation_id, date, target_type)
            _remove_chip(db, reservation_id, date, other_type)

        db.flush()
    except Exception:
        # 돈 관련 로직이라 조용히 삼키지 않고 critical diag 로 기록.
        # 호출자 경로들은 개별 try/except 로 격리돼 있어 전체 차단은 방지.
        logger.exception(
            "surcharge: reconcile 실패 (reservation_id=%s, date=%s)",
            reservation_id, date,
        )
        diag(
            "surcharge.reconcile_failed",
            level="critical",
            reservation_id=reservation_id,
            date=date,
        )


def _ensure_chip(db: Session, reservation_id: int, date: str, custom_type: str) -> None:
    """해당 custom_type 의 스케줄에 대한 칩이 없으면 생성.

    chip_store.ensure_chip 위임 (PR5 이주). race 처리 + idempotent 보장은
    chip_store 내부 SAVEPOINT 가 담당. template 비활성화 상태면 skip.
    """
    schedule = _find_schedule(db, custom_type)
    if not schedule or not schedule.template or not schedule.template.is_active:
        return
    from app.services.chip_store import ensure_chip
    ensure_chip(
        db,
        reservation_id=reservation_id,
        template_key=schedule.template.template_key,
        date=date,
        assigned_by='auto',
        schedule_id=schedule.id,
    )


def _remove_chip(db: Session, reservation_id: int, date: str, custom_type: str) -> None:
    """해당 custom_type 의 미발송 칩 삭제.

    chip_store.remove_chip 위임 (PR5 이주). 가드 강화 — 기존 sent_at NULL 만
    가드 → PROTECTED_ASSIGNED_BY (manual/excluded/failed) 추가 보호 (OQ-1 fix).
    """
    schedule = _find_schedule(db, custom_type)
    if not schedule:
        return
    from app.services.chip_store import remove_chip
    remove_chip(
        db,
        reservation_id=reservation_id,
        template_key=schedule.template.template_key if schedule.template else "",
        date=date,
        schedule_id=schedule.id,
    )


def _delete_all_surcharge_chips(db: Session, reservation_id: int, date: str) -> None:
    """해당 예약-날짜의 미발송 surcharge 칩을 모두 삭제.

    chip_store.delete_chips_for_reservation 위임 (PR5 이주). 가드 강화 —
    기존 sent_at NULL 만 가드 → manual/excluded/failed 추가 보호 (OQ-1 fix).
    """
    surcharge_schedule_ids = [
        s.id for s in db.query(TemplateSchedule.id).filter(
            TemplateSchedule.schedule_category == 'custom_schedule',
            TemplateSchedule.custom_type.in_(_ALL_SURCHARGE_TYPES),
        ).all()
    ]
    if not surcharge_schedule_ids:
        return
    from app.services.chip_store import delete_chips_for_reservation
    deleted = delete_chips_for_reservation(
        db,
        reservation_id=reservation_id,
        dates=[date],
        schedule_ids=surcharge_schedule_ids,
    )
    if deleted:
        diag("surcharge.all_deleted", level="verbose",
             res_id=reservation_id, date=date, count=deleted)


def reconcile_surcharge_batch(
    db: Session,
    reservation_ids: List[int],
    date: str,
) -> None:
    """배치 reconcile (개별 실패가 전체 차단 안 함)."""
    diag("surcharge.batch.enter", level="verbose", count=len(reservation_ids))
    for rid in reservation_ids:
        try:
            reconcile_surcharge(db, rid, date)
        except Exception:
            logger.exception("surcharge: batch 처리 중 예외 (rid=%s, date=%s)", rid, date)
    diag("surcharge.batch.exit", level="verbose", count=len(reservation_ids))
