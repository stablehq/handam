"""
Shared Naver reservation sync logic.
Used by both the API endpoint and the scheduler job.
"""
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
import logging

import re

from app.db.models import Reservation, ReservationStatus, ReservationSmsAssignment, NaverBizItem, RoomBizItemLink, Room
from app.diag_logger import diag
from app.services import room_assignment
from app.services.consecutive_stay import compute_is_long_stay
from app.services.room_auto_assign import auto_assign_rooms
from app.config import KST, today_kst
from app.db.tenant_context import get_session_tenant_id

logger = logging.getLogger(__name__)


def _parse_gender_from_custom_form(text: str, total: int = 0) -> tuple[int, int] | None:
    """Parse gender counts from free-form text like '남 24 여 25 남 21'.
    Returns (male_count, female_count) or None if unparseable.
    total > 0이면 파싱 결과 합이 total과 일치할 때만 반환 (보조 도구).
    '남자'를 '남'보다 먼저 매칭하여 중복 카운트 방지."""
    if not text or not text.strip():
        return None
    males = len(re.findall(r'남자|남', text))
    females = len(re.findall(r'여자|여', text))
    if males == 0 and females == 0:
        return None
    # total이 지정되면 파싱 결과와 일치할 때만 신뢰
    if total > 0 and males + females != total:
        return None
    return (males, females)


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string to datetime, returning None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


async def sync_naver_to_db(reservation_provider, db: Session, target_date=None, from_date: str = None, reconcile_date: str = None, source: str = "stable") -> Dict[str, Any]:
    """
    [Phase 1~5 메인 함수] 네이버 예약 수신 → DB 저장 → 칩 생성 → 연박 감지 → 자동 배정.

    Phase 1: reservation_provider.get_reservations() — 네이버 API에서 예약 가져오기
    Phase 2: enrichment(biz_name/people_count/gender) + _create_reservation/_update_reservation
    Phase 3: reconcile_chips_for_reservation (1차) — 방 미배정 상태, building 칩 미생성
    Phase 4: detect_and_link_consecutive_stays — 연박 그룹 링크
    Phase 5: auto_assign_rooms → assign_room() → reconcile (2차) — building 칩 생성

    Args:
        from_date: Optional start date (YYYY-MM-DD) for historical sync.
        reconcile_date: Optional check-in date (YYYY-MM-DD) for reconciliation.
                        Uses STARTDATE filter instead of REGDATE.

    Returns summary dict with synced/added/updated counts.
    """
    diag(
        "naver_sync.enter",
        level="verbose",
        source=source,
        reconcile_date=reconcile_date,
        from_date=from_date,
    )

    if reconcile_date:
        logger.info(f"Starting Naver reconciliation for check-in date: {reconcile_date}")
        raw_reservations = await reservation_provider.fetch_by_checkin_date(reconcile_date)
    else:
        logger.info(f"Starting Naver reservation sync...{f' (from {from_date})' if from_date else ''}")
        raw_reservations = await reservation_provider.sync_reservations(target_date, from_date=from_date)

    diag(
        "naver_sync.fetched",
        level="verbose",
        raw_count=len(raw_reservations),
    )

    # Build lookup maps from DB (NaverBizItem + Room)
    biz_items = db.query(NaverBizItem).all()
    biz_name_map = {b.biz_item_id: (b.display_name or b.name) for b in biz_items}
    biz_section_map = {b.biz_item_id: b.section_hint for b in biz_items}
    biz_party_map = {b.biz_item_id: b.default_party_type for b in biz_items if b.default_party_type}
    biz_capacity_map = {b.biz_item_id: b.default_capacity for b in biz_items if b.default_capacity}

    # Build dormitory map and capacity fallback from RoomBizItemLink → Room
    # biz_link_set: RoomBizItemLink 에 매핑된 모든 biz_item_id (도미토리/일반실 무관).
    # 매핑 없는 biz_item (예: 차량투어, 미등록 상품) 은 split 대상 아님 — 가드용.
    biz_dormitory_map: Dict[str, bool] = {}
    biz_link_set: set[str] = set()
    links = db.query(RoomBizItemLink).join(
        Room, and_(Room.id == RoomBizItemLink.room_id, Room.tenant_id == RoomBizItemLink.tenant_id)
    ).all()
    for link in links:
        biz_link_set.add(link.biz_item_id)
        if link.biz_item_id not in biz_capacity_map:
            biz_capacity_map[link.biz_item_id] = link.room.base_capacity
        if link.room.is_dormitory:
            biz_dormitory_map[link.biz_item_id] = True

    # Deduplicate by external_id (monthly chunks can overlap)
    seen_ids = {}
    for r in raw_reservations:
        ext_id = r.get("external_id") or r.get("naver_booking_id")
        if ext_id:
            seen_ids[ext_id] = r  # keep latest
        else:
            seen_ids[id(r)] = r
    reservations = list(seen_ids.values())
    if len(reservations) != len(raw_reservations):
        logger.info(f"Deduplicated: {len(raw_reservations)} → {len(reservations)}")

    # ── Phase 2: enrichment ──
    # 네이버 상품ID → DB 매핑(상품명, 도미토리 여부, 기준인원, 섹션 힌트)으로 변환
    for res_data in reservations:
        bid = res_data.get("naver_biz_item_id", "")

        if source == "unstable":
            # 언스테이블: NaverBizItem 매핑 없음 — 직접 설정
            name = res_data.get("biz_item_name") or bid
            res_data["room_type"] = name
            res_data["biz_item_name"] = name
            # 인원: bookingCount가 곧 인원수 (도미토리와 동일 방식)
            res_data["people_count"] = res_data.get("booking_count") or 1
            # section: 항상 unstable
            res_data["_section_hint"] = "unstable"
            # 성별: customFormInputJson 파싱 → fallback으로 기존 gender(userId API)
            total = res_data["people_count"]
            parsed = _parse_gender_from_custom_form(res_data.get("custom_form_input"), total)
            if parsed:
                # 파싱 성공 = 남+여 합계가 total과 일치
                res_data["_unstable_male"] = parsed[0]
                res_data["_unstable_female"] = parsed[1]
            else:
                # fallback: userId API 성별로 전체 인원 배정
                booker_gender = res_data.get("gender", "")
                if booker_gender == "남":
                    res_data["_unstable_male"] = total
                    res_data["_unstable_female"] = 0
                elif booker_gender == "여":
                    res_data["_unstable_male"] = 0
                    res_data["_unstable_female"] = total
                # else: None으로 남겨서 _init_gender_counts fallback
        else:
            # 스테이블: 기존 로직 그대로
            name = biz_name_map.get(bid, bid)
            res_data["room_type"] = name
            res_data["biz_item_name"] = name
            # 인원 enrichment: 도미토리 vs 일반실 분기
            if biz_dormitory_map.get(bid, False):
                # 도미토리: bookingCount = 인원 (인원수 옵션 무시)
                res_data["people_count"] = res_data.get("booking_count") or 1
                res_data["_is_dormitory"] = True
            else:
                # 일반실: 인원수 옵션 우선, 없으면 기준인원(base_capacity)
                pc = res_data.get("people_count")
                if not pc:
                    res_data["people_count"] = biz_capacity_map.get(bid, 1)
            # split 가드: RoomBizItemLink 매핑 없는 biz_item (차량투어, 미등록 상품 등) 은
            # 도미토리/일반실 판단 불가 → split 대상에서 제외.
            res_data["_has_room_link"] = bid in biz_link_set
            # section_hint enrichment (res_data에 저장해서 _create_reservation에서 사용)
            res_data["_section_hint"] = biz_section_map.get(bid)
            # 패키지 상품 기본 파티타입 (새 예약 생성 시에만 적용)
            res_data["_default_party_type"] = biz_party_map.get(bid)

    # Bulk-fetch existing reservations by external_id/naver_booking_id in one query
    all_ext_ids = [
        r.get("external_id") or r.get("naver_booking_id")
        for r in reservations
        if r.get("external_id") or r.get("naver_booking_id")
    ]
    existing_map: Dict[str, Reservation] = {}
    if all_ext_ids:
        existing_rows = (
            db.query(Reservation)
            .filter(
                or_(
                    Reservation.external_id.in_(all_ext_ids),
                    Reservation.naver_booking_id.in_(all_ext_ids),
                )
            )
            .all()
        )
        for row in existing_rows:
            if row.external_id:
                existing_map[row.external_id] = row
            # naver_split sibling 은 naver_booking_id 가 NULL 이라 매칭 후보 아님 (안전).
            # 일반 row 만 naver_booking_id 로 매핑하여 primary 매칭이 sibling 에 의해 오염되지 않도록 한다.
            if row.naver_booking_id and row.booking_source != "naver_split":
                existing_map[row.naver_booking_id] = row

    # ── Phase 2.5: 일반실 booking_count>1 split (신규 예약만) ──
    # primary 1개 + sibling N-1개. sibling 은 수동 예약처럼 독립 row.
    reservations = _split_multi_room_reservations(reservations, existing_map)

    # ── Phase 2 계속: DB 저장 (신규 → _create_reservation, 기존 → _update_reservation) ──
    added_count = 0
    updated_count = 0
    new_reservation_ids = []  # 칩 생성 대상: 새 예약 ID
    date_changed_ids = []  # 칩 재계산 대상: 날짜 변경 예약 ID

    for res_data in reservations:
        external_id = res_data.get("external_id") or res_data.get("naver_booking_id")
        existing = existing_map.get(external_id) if external_id else None

        if existing:
            old_dates = (existing.check_in_date, existing.check_out_date)
            _update_reservation(db, existing, res_data)
            new_dates = (existing.check_in_date, existing.check_out_date)
            if old_dates != new_dates:
                date_changed_ids.append(existing.id)
            updated_count += 1
        else:
            new_res = _create_reservation(res_data)
            db.add(new_res)
            db.flush()  # ID 즉시 할당 (commit 후 N+1 lazy reload 방지)
            new_reservation_ids.append(new_res.id)
            added_count += 1

    db.commit()

    # ── Phase 3: 칩 reconcile은 Phase 5(자동배정) 이후 1회로 통합 ──
    # 이전에는 여기서 1차 reconcile 했으나, RoomAssignment 없는 상태에서
    # building 필터 칩이 생성 안 되고 Phase 5에서 다시 돌려야 해서 2중 실행이었음.
    # 이제 Phase 5 이후 칩 reconcile 1회로 통합하여 연산 50% 감소.
    chip_target_ids = new_reservation_ids + date_changed_ids

    # ── Phase 4: 연박 감지 (같은 이름+전화의 연속 날짜 예약 → stay_group으로 링크) ──
    if added_count > 0 or updated_count > 0:
        try:
            from app.services.consecutive_stay import detect_and_link_consecutive_stays
            stay_result = detect_and_link_consecutive_stays(db)
            db.commit()
            if stay_result["linked"] > 0 or stay_result["unlinked"] > 0:
                logger.info(f"Consecutive stay detection after sync: {stay_result}")
            # ── Phase 4-b: 연박 그룹 bed_order 정합성 체크 ──
            # 새로 연결된 그룹에서 같은 방인데 bed_order가 다른 경우 통일
            if stay_result["linked"] > 0:
                _align_bed_orders_for_groups(db)
                db.flush()
        except Exception as e:
            logger.error(f"Consecutive stay detection failed: {e}")
            db.rollback()

    # ── Phase 5: 자동 객실 배정 ──
    # auto_assign_rooms → assign_room() → ★ 칩 reconcile (2차)
    # 이번에는 RoomAssignment 있으므로 building 필터 통과 → 칩 생성됨
    # reconcile 경로: 항상 오늘 포함 (09:55 일일 대사)
    # 일반 sync 경로: 15:00 KST 이전이면 오늘 포함, 이후엔 내일 이후만 (오후 늦게 들어온
    # 당일 예약은 운영자 수동 배정에 맡김 — 아래 SAME_DAY_AUTO_CUTOFF_HOUR 참조)
    if added_count > 0 or date_changed_ids:
        try:
            now_kst = datetime.now(KST)
            today = now_kst.strftime("%Y-%m-%d")

            # 당일 예약 자동 배정 컷오프 (15:00 KST).
            # - 15:00 이전: 오늘 포함 자동 배정 (운영자 도착 전 자동 처리)
            # - 15:00 이후: 오늘 제외 (체크인 임박 — 운영자 수동 배정에 맡김)
            # reconcile 모드 (09:55 일일 대사) 는 항상 오늘 포함 (시각상 항상 cutoff 이전).
            SAME_DAY_AUTO_CUTOFF_HOUR = 15
            include_today_in_auto = now_kst.hour < SAME_DAY_AUTO_CUTOFF_HOUR
            tomorrow = (now_kst + timedelta(days=1)).strftime("%Y-%m-%d")
            auto_assign_threshold = today if (reconcile_date or include_today_in_auto) else tomorrow

            dates = set()

            # added reservations
            new_external_ids = set()
            for res_data in reservations:
                ext = res_data.get("external_id") or res_data.get("naver_booking_id")
                if ext and existing_map.get(ext) is None:
                    new_external_ids.add(ext)
            for res_data in reservations:
                ext = res_data.get("external_id") or res_data.get("naver_booking_id")
                if ext not in new_external_ids:
                    continue
                d = res_data.get("date")
                if d and d >= auto_assign_threshold:
                    dates.add(d)

            # date_changed reservations: 전체 체류 범위 수집
            if date_changed_ids:
                from app.services.schedule_utils import date_range as _date_range
                changed = db.query(Reservation).filter(
                    Reservation.id.in_(date_changed_ids)
                ).all()
                for res in changed:
                    if res.check_in_date and res.check_out_date:
                        for d in _date_range(str(res.check_in_date), str(res.check_out_date)):
                            if d >= auto_assign_threshold:
                                dates.add(d)

            assigned_total = 0
            for d in sorted(dates):
                result = auto_assign_rooms(db, d, created_by="reconcile" if reconcile_date else "sync")
                assigned_total += result.get("assigned", 0)
            if dates:
                logger.info(f"Auto-assigned {assigned_total} rooms after sync (dates: {sorted(dates)})")
                db.commit()

            diag("naver_sync.phase5", level="verbose", added_count=added_count,
                 date_changed_count=len(date_changed_ids), dates=sorted(dates),
                 auto_assign_threshold=auto_assign_threshold,
                 same_day_included=include_today_in_auto,
                 reconcile_mode=bool(reconcile_date))
        except Exception as e:
            logger.error(f"Auto-assign after sync failed: {e}")
            db.rollback()

    # ── Phase 5 이후: ★ 칩 reconcile (통합 1회) ──
    # Phase 5 자동배정 완료 후 RoomAssignment가 확정된 상태에서 칩 생성.
    # building/room 필터 포함 모든 스케줄 칩이 한 번에 정확하게 생성됨.
    # 자동배정 실패 예약도 여기서 building 무관 칩(hook, 후기 등)이 생성됨.
    if chip_target_ids:
        try:
            from app.services.chip_reconciler import reconcile_chips_for_reservation
            from app.db.models import TemplateSchedule
            # Defense-in-depth: explicit tenant filter — the implicit
            # before_compile filter is skipped under a leaked bypass, which
            # historically pulled cross-tenant schedules into chip reconcile.
            _tid_for_chips = get_session_tenant_id(db)
            if _tid_for_chips is None:
                raise RuntimeError("naver_sync chip reconcile requires tenant context")
            active_schedules = db.query(TemplateSchedule).filter(
                TemplateSchedule.tenant_id == _tid_for_chips,
                TemplateSchedule.is_active == True,
            ).all()
            for res_id in chip_target_ids:
                reconcile_chips_for_reservation(db, res_id, schedules=active_schedules)
            db.commit()
        except Exception as e:
            logger.error(f"Chip reconciliation after sync failed: {e}")
            db.rollback()

        # Surcharge reconcile for synced reservations
        try:
            from app.services.surcharge import reconcile_surcharge_batch
            today_str = today_kst()
            reconcile_surcharge_batch(db, chip_target_ids, today_str)
        except Exception as e:
            logger.warning(f"Surcharge batch reconcile after sync failed: {e}")

        # room_upgrade_promise / _review reconcile (무료 업그레이드 안내).
        # 각자 진입 가드 + target_mode 가드 가 있어 스케줄 비활성 시 즉시 return.
        try:
            from app.services.room_upgrade_promise import reconcile_room_upgrade_promise_batch
            from app.services.room_upgrade_review import reconcile_room_upgrade_review_batch
            today_str = today_kst()
            reconcile_room_upgrade_promise_batch(db, chip_target_ids, today_str)
            reconcile_room_upgrade_review_batch(db, chip_target_ids, today_str)
        except Exception as e:
            logger.warning(f"room_upgrade batch reconcile after sync failed: {e}")

    # ── Phase 6: event SMS 즉시 발송 훅 (fire-and-forget, 격리) ──
    # 활성 event 스케줄(gender_filter / hours_since_booking 등) 매칭되는 신규 예약에
    # 즉시 안내 SMS 발송. 실패는 sync 메인 흐름에 영향 없음.
    if new_reservation_ids:
        try:
            from app.services.event_sms_hook import schedule_event_sms_hook
            schedule_event_sms_hook(new_reservation_ids, tenant_id=get_session_tenant_id(db))
        except Exception as e:
            logger.exception(f"event_sms_hook scheduling failed (suppressed): {e}")

    logger.info(f"Naver sync completed: {added_count} added, {updated_count} updated")

    diag(
        "naver_sync.exit",
        level="verbose",
        synced=len(reservations),
        added=added_count,
        updated=updated_count,
    )

    return {
        "success": True,
        "synced": len(reservations),
        "added": added_count,
        "updated": updated_count,
        "message": f"{len(reservations)}건 조회, {added_count}건 추가, {updated_count}건 갱신",
    }


def _align_bed_orders_for_groups(db: Session):
    """연박 그룹 내 같은 방 배정의 bed_order를 통일한다.

    그룹 내 먼저 배정된 멤버의 bed_order를 기준으로,
    같은 방에 배정된 다른 멤버의 bed_order를 맞춘다.
    """
    from app.db.models import RoomAssignment, Room
    from sqlalchemy import and_

    # stay_group 이 있고, 체크아웃 오늘 이후이면서 체크인 5일 이내인 예약만 대상.
    # — 과거 그룹: bed_order 재정렬 의미 없음 (이미 배정 고정).
    # — 먼 미래 그룹: 입실일 가까워지면 다음 주기에 자동 정렬됨.
    from datetime import timedelta
    from app.config import today_kst, today_kst_date
    today_str = today_kst()
    max_checkin = (today_kst_date() + timedelta(days=5)).strftime("%Y-%m-%d")
    grouped = (
        db.query(Reservation)
        .filter(
            Reservation.stay_group_id.isnot(None),
            Reservation.check_in_date <= max_checkin,
            or_(
                Reservation.check_out_date >= today_str,
                Reservation.check_out_date.is_(None),
            ),
        )
        .all()
    )
    if not grouped:
        return

    # 그룹별로 묶기
    groups: Dict[str, list] = {}
    for res in grouped:
        groups.setdefault(res.stay_group_id, []).append(res)

    updated = 0
    for group_id, members in groups.items():
        member_ids = [m.id for m in members]

        # 이 그룹의 모든 RoomAssignment (도미토리만)
        assignments = (
            db.query(RoomAssignment)
            .join(Room, and_(Room.id == RoomAssignment.room_id, Room.tenant_id == RoomAssignment.tenant_id))
            .filter(
                RoomAssignment.reservation_id.in_(member_ids),
                Room.is_dormitory == True,
            )
            .all()
        )
        if not assignments:
            continue

        # room_id별로 그룹 내 bed_order 수집
        room_orders: Dict[int, int] = {}  # room_id → 기준 bed_order
        for a in assignments:
            if a.room_id not in room_orders and a.bed_order and a.bed_order > 0:
                room_orders[a.room_id] = a.bed_order

        # 같은 방인데 bed_order가 다른 경우 통일
        for a in assignments:
            ref = room_orders.get(a.room_id)
            if ref and a.bed_order != ref:
                a.bed_order = ref
                updated += 1

    if updated > 0:
        logger.info(f"Aligned {updated} bed_orders for stay groups")
    diag(
        "naver_sync.bed_order_align",
        level="verbose",
        groups_scanned=len(groups),
        members_scanned=len(grouped),
        bed_orders_updated=updated,
        window_max_checkin=max_checkin,
    )


def _init_gender_counts(res_data: Dict[str, Any]) -> tuple:
    """성별 인원 계산: gender="남" → (people_count, 0), "여" → (0, people_count), 그 외 → (None, None)."""
    # 일반실 booking_count>1 split: 사전 분할된 정확한 값 우선
    if "_split_male" in res_data:
        return (res_data["_split_male"], res_data["_split_female"])

    # 언스테이블: customFormInputJson 파싱 결과 우선
    if "_unstable_male" in res_data:
        return (res_data["_unstable_male"], res_data["_unstable_female"])

    gender = res_data.get("gender", "")
    people = res_data.get("people_count", 1) or 1
    if gender == "남":
        return (people, 0)
    elif gender == "여":
        return (0, people)
    else:
        return (None, None)


def _split_multi_room_reservations(
    reservations: list,
    existing_map: Dict[str, Reservation],
) -> list:
    """일반실 + booking_count > 1 인 신규 예약을 primary 1개 + sibling N-1개로 분할.

    네이버는 한 예약에 객실 N개 (bookingCount) 를 1건으로 보내지만, 우리 스키마
    `RoomAssignment.UniqueConstraint(reservation_id, date)` 가 한 예약-한 방-한 날짜 모델이라
    충돌. 첫 동기화 시 sibling N-1개를 "수동 예약"처럼 별도 row 로 만들어 자연스럽게 자동배정
    가능하게 함. sibling 은 external_id/naver_booking_id 모두 NULL 이라 재동기화 매칭 후보가
    아니며, 네이버 측 변경/취소는 primary 에만 자동 반영됨 (운영자 수동 처리).

    도미토리는 booking_count 가 인원수 의미라 split 대상 아님.
    재동기화 (existing_map 매칭됨) 도 split 안 함 (이미 처리 완료).
    """
    extras = []
    skip_bc1 = 0
    skip_dorm = 0
    skip_existing = 0
    skip_unmapped = 0
    for res_data in reservations:
        bc = res_data.get("booking_count") or 1
        if bc <= 1:
            skip_bc1 += 1
            continue
        if res_data.get("_is_dormitory"):
            skip_dorm += 1
            continue
        # split 가드: RoomBizItemLink 매핑 없는 biz_item 은 정체 불명 (차량투어 등 비숙박 상품
        # 가능성). 운영 사고 방지를 위해 split 제외 — 운영자가 NaverBizItem + RoomBizItemLink
        # 등록 후에만 자동 split 대상.
        if not res_data.get("_has_room_link"):
            skip_unmapped += 1
            continue
        ext_id = res_data.get("external_id") or res_data.get("naver_booking_id")
        if ext_id and existing_map.get(ext_id):
            skip_existing += 1
            continue

        # 인원수: gender 단일값으로 male/female 계산해두고, floor 분할
        male, female = _init_gender_counts(res_data)
        male = male or 0
        female = female or 0

        # 균등분할: floor + 나머지는 primary 에 몰빵 (인원/금액/people_count 합계 보존)
        sibling_male = male // bc
        sibling_female = female // bc
        primary_male = male - sibling_male * (bc - 1)
        primary_female = female - sibling_female * (bc - 1)

        price = res_data.get("total_price") or 0
        sibling_price = price // bc
        primary_price = price - sibling_price * (bc - 1)

        # people_count → party_size: sibling 도 분할해야 도미토리 전환/용량 체크 정합성 유지
        people = res_data.get("people_count") or 1
        sibling_people = max(1, people // bc)
        primary_people = max(1, people - sibling_people * (bc - 1))

        # primary in-place 수정
        res_data["booking_count"] = 1
        res_data["total_price"] = primary_price
        res_data["people_count"] = primary_people
        res_data["_split_male"] = primary_male
        res_data["_split_female"] = primary_female

        # sibling N-1 개 생성 (수동 예약처럼)
        for _ in range(bc - 1):
            sibling = dict(res_data)
            sibling["external_id"] = None
            sibling["naver_booking_id"] = None
            sibling["booking_count"] = 1
            sibling["total_price"] = sibling_price
            sibling["people_count"] = sibling_people
            sibling["_split_male"] = sibling_male
            sibling["_split_female"] = sibling_female
            sibling["_booking_source_override"] = "naver_split"
            extras.append(sibling)

        diag(
            "naver_sync.split_multi_room",
            level="info",
            naver_booking_id=res_data.get("naver_booking_id") or ext_id,
            booking_count=bc,
            siblings_created=bc - 1,
        )

    if extras or skip_bc1 or skip_dorm or skip_existing or skip_unmapped:
        diag(
            "naver_sync.split_summary",
            level="verbose",
            total_input=len(reservations),
            siblings_added=len(extras),
            skip_bc1=skip_bc1,
            skip_dorm=skip_dorm,
            skip_existing=skip_existing,
            skip_unmapped=skip_unmapped,
        )

    return reservations + extras


def _create_reservation(res_data: Dict[str, Any]) -> Reservation:
    """Create a new Reservation from Naver API data."""
    try:
        status_enum = ReservationStatus(res_data.get("status", "pending"))
    except ValueError:
        status_enum = ReservationStatus.CONFIRMED

    male_count, female_count = _init_gender_counts(res_data)

    naver_room_type = res_data.get("room_type", "")
    section_hint = res_data.get("_section_hint")
    section = section_hint if section_hint in ('party', 'room', 'unstable') else 'unassigned'

    # 패키지 상품: default_party_type이 있으면 Reservation.party_type 자동 세팅
    default_pt = res_data.get("_default_party_type")
    if default_pt and not res_data.get("party_type"):
        res_data["party_type"] = default_pt

    reservation = Reservation(
        external_id=res_data.get("external_id"),
        naver_booking_id=res_data.get("naver_booking_id"),
        naver_biz_item_id=res_data.get("naver_biz_item_id"),
        customer_name=res_data.get("customer_name", ""),
        phone=res_data.get("phone", ""),
        visitor_name=res_data.get("visitor_name"),
        visitor_phone=res_data.get("visitor_phone"),
        check_in_date=res_data.get("date", ""),
        check_in_time=res_data.get("time", ""),
        status=status_enum,
        booking_source=res_data.get("_booking_source_override", "naver"),
        naver_room_type=naver_room_type,
        party_size=res_data.get("people_count") or 1,
        male_count=male_count,
        female_count=female_count,
        check_out_date=res_data.get("end_date"),
        biz_item_name=res_data.get("biz_item_name"),
        booking_count=res_data.get("booking_count", 1),
        booking_options=res_data.get("booking_options"),
        special_requests=res_data.get("custom_form_input"),
        total_price=res_data.get("total_price"),
        confirmed_at=_parse_datetime(res_data.get("confirmed_at")),
        cancelled_at=_parse_datetime(res_data.get("cancelled_at")),
        gender=res_data.get("gender"),
        age_group=res_data.get("age_group"),
        visit_count=res_data.get("visit_count", 1),
        section=section,
        party_type=res_data.get("party_type"),
    )
    reservation.is_long_stay = compute_is_long_stay(reservation)
    return reservation


def _update_reservation(db: Session, existing: Reservation, res_data: Dict[str, Any]):
    """[Phase 2] 기존 예약 갱신. 성별 인원은 gender_manual=False일 때만 재계산."""
    # Phase 2-5c: 제약 관련 필드의 이전 값 캡처 (invariant 재검증에 사용)
    old_male = existing.male_count
    old_female = existing.female_count
    old_party_size = existing.party_size
    old_gender = existing.gender
    # F1: SMS 칩 영향 필드 변경 감지용 (reservations.py::PATCH _SMS_TAG_FIELDS 와 동일 규약)
    old_naver_room_type = existing.naver_room_type

    # split 정책: 일반실(매핑된 biz_item)의 primary 는 booking_count/total_price/party_size 가
    # split 시 분할된 값이라 네이버 원본값으로 덮어쓰면 sibling 들과 합계 어긋남.
    # 도미토리(booking_count=인원수 의미)와 매핑 없는 정체불명 상품은 네이버 원본 그대로.
    is_split_managed = (not res_data.get("_is_dormitory")) and res_data.get("_has_room_link")

    # PR1: 5 개 운영자 편집 가능 필드를 Mutator 통과 (manually_edited_fields 가드).
    # naver_room_type 은 NAVER=always 유지 (운영자 편집 안 함).
    from app.services.reservation_mutator import ReservationMutator, ChangeSource
    ReservationMutator.apply_changes(
        db, existing, ChangeSource.NAVER,
        {
            "customer_name":    res_data.get("customer_name",    existing.customer_name),
            "phone":            res_data.get("phone",            existing.phone),
            "visitor_name":     res_data.get("visitor_name",     existing.visitor_name),
            "visitor_phone":    res_data.get("visitor_phone",    existing.visitor_phone),
            "special_requests": res_data.get("custom_form_input", existing.special_requests),
        },
    )
    existing.naver_biz_item_id = res_data.get("naver_biz_item_id", existing.naver_biz_item_id)
    existing.naver_room_type = res_data.get("room_type", existing.naver_room_type)
    if not is_split_managed:
        existing.party_size = res_data.get("people_count", existing.party_size)
    old_date = existing.check_in_date
    old_end_date = existing.check_out_date
    incoming_check_in = res_data.get("date", existing.check_in_date)
    # Mutator: pinned=True 면 guarded → skip (한번 직접수정한 건 영구. cancel/manual 해제만 인정)
    from app.services.reservation_mutator import ReservationMutator, ChangeSource
    ReservationMutator.apply_changes(
        db, existing, ChangeSource.NAVER, {"check_in_date": incoming_check_in}
    )
    existing.check_in_time = res_data.get("time", existing.check_in_time)
    incoming_end = res_data.get("end_date")
    if incoming_end is not None:
        # 보호 가드 — check_out_pinned 단독으로 모든 수동 변경 케이스 cover.
        # manually_extended_until 의 보호 효과는 단계 #8 1:1 매핑으로 check_out_pinned 가 흡수.
        # manually_extended_until 은 운영 표시용 (UI "연박 취소" 버튼 + cancel 진입 조건).
        if existing.check_out_pinned and incoming_end < existing.check_out_date:
            # User manually changed check_out — preserve; naver hasn't caught up yet
            diag(
                "naver_sync.user_extension_preserved",
                level="critical",
                reservation_id=existing.id,
                incoming_end=incoming_end,
                existing_end=existing.check_out_date,
                manually_extended_until=existing.manually_extended_until,
                naver_booking_id=existing.naver_booking_id,
            )
            # skip overwrite
        else:
            if existing.manually_extended_until and incoming_end >= existing.manually_extended_until:
                # Naver caught up — clear flag
                diag(
                    "naver_sync.user_extension_overridden",
                    level="critical",
                    reservation_id=existing.id,
                    incoming_end=incoming_end,
                    manually_extended_until=existing.manually_extended_until,
                )
                existing.manually_extended_until = None
            # Mutator: pinned=True 면 guarded → skip (한번 직접수정한 건 영구. cancel/manual 해제만 인정)
            ReservationMutator.apply_changes(
                db, existing, ChangeSource.NAVER, {"check_out_date": incoming_end}
            )
    existing.biz_item_name = res_data.get("biz_item_name", existing.biz_item_name)
    if not is_split_managed:
        existing.booking_count = res_data.get("booking_count", existing.booking_count)
    existing.booking_options = res_data.get("booking_options", existing.booking_options)
    # special_requests 는 위 Mutator.apply_changes 가 처리 (PR1) — 중복 setattr 제거
    if not is_split_managed:
        existing.total_price = res_data.get("total_price", existing.total_price)
    existing.confirmed_at = _parse_datetime(res_data.get("confirmed_at")) if res_data.get("confirmed_at") is not None else existing.confirmed_at
    existing.cancelled_at = _parse_datetime(res_data.get("cancelled_at")) if res_data.get("cancelled_at") is not None else existing.cancelled_at
    if res_data.get("gender"):
        existing.gender = res_data["gender"]
    if res_data.get("age_group"):
        existing.age_group = res_data["age_group"]
    if res_data.get("visit_count"):
        existing.visit_count = res_data["visit_count"]
    # 성별 인원 재계산: 도미토리는 매 동기화마다, 일반실은 초기화 시에만
    if not existing.gender_manual:
        is_dormitory = res_data.get("_is_dormitory", False)
        if is_dormitory:
            # 도미토리: booking_count + gender로 항상 재계산
            male_count, female_count = _init_gender_counts(res_data)
            existing.male_count = male_count
            existing.female_count = female_count
        elif existing.male_count is None and existing.female_count is None:
            # 일반실: 최초 세팅 시에만
            male_count, female_count = _init_gender_counts(res_data)
            existing.male_count = male_count
            existing.female_count = female_count

    # Update status based on Naver status
    naver_status = res_data.get("status", "confirmed")
    _prev_status = existing.status
    if naver_status == "confirmed":
        existing.status = ReservationStatus.CONFIRMED
    elif naver_status == "cancelled":
        existing.status = ReservationStatus.CANCELLED
        # S4 fix: 취소 시 manually_extended_until 클리어 — 재활성 시 stale flag로
        # naver_sync 영구 차단되는 silent data drift 방지
        if existing.manually_extended_until:
            existing.manually_extended_until = None
            existing.check_out_pinned = False
    # status 트랜지션 진단 — 강태호 케이스(2026-04-29) 같은 cancel 누락 재발 시
    # 응답에 들어왔는데 매칭됐는지 추적. idempotent (변경 없으면 noise X).
    if _prev_status != existing.status:
        try:
            diag(
                "reservation.status_changed",
                level="critical",
                res_id=existing.id,
                naver_booking_id=existing.naver_booking_id,
                from_status=str(_prev_status),
                to_status=str(existing.status),
                source=res_data.get("_source", "naver_sync"),
            )
        except Exception:
            pass
        # lifecycle 단계 #15: status 변화 처리 (CANCELLED 만 — 재활성 시 idempotent 라 skip 안전)
        if existing.status == ReservationStatus.CANCELLED:
            today_str = today_kst()
            check_in_str = str(existing.check_in_date) if existing.check_in_date else ""
            is_same_day_cancel = (check_in_str == today_str)
            from app.services.reservation_lifecycle import on_status_cancelled
            on_status_cancelled(db, existing, same_day=is_same_day_cancel)
        # Remove from consecutive stay group on cancellation + peer 칩 재동기화
        # (reservations.py PATCH 의 CANCELLED 분기와 동일 정책 — peer 의 is_long_stay/
        # stay_group_order 가 unlink 로 갱신되므로 stay_filter 칩 재계산 필수)
        if existing.stay_group_id:
            from app.services.consecutive_stay import unlink_from_group
            peer_ids = [
                r.id for r in db.query(Reservation).filter(
                    Reservation.stay_group_id == existing.stay_group_id,
                    Reservation.id != existing.id,
                ).all()
            ]
            unlink_from_group(db, existing.id)
            if peer_ids:
                db.flush()
                # 5종 칩 통합 — naver 가 cancel 감지 후 unlink 시 peer 의 4종 칩
                # stale 방지 (sync-sms-tags PR4).
                from app.services.reconcile import reconcile_all_chips
                for peer_id in peer_ids:
                    try:
                        reconcile_all_chips(db, peer_id)
                    except Exception as e:
                        logger.warning(f"naver_sync peer reconcile_all_chips after unlink failed: res={peer_id} err={e}")

    # Reconcile room assignments if dates changed (lifecycle 단계 #13)
    if existing.check_in_date != old_date or existing.check_out_date != old_end_date:
        from app.services.reservation_lifecycle import on_dates_changed
        on_dates_changed(db, existing, old_date, old_end_date)

    # Recompute is_long_stay (stay_group_id may be set later by detect_and_link)
    existing.is_long_stay = compute_is_long_stay(existing)

    # Phase 2-5c: 성별/인원 변경 시 invariant 체크 (C-2)
    _CONSTRAINT_CHANGED = (
        old_male != existing.male_count or
        old_female != existing.female_count or
        old_party_size != existing.party_size or
        old_gender != existing.gender
    )

    if _CONSTRAINT_CHANGED:
        # lifecycle 단계 #14
        from app.services.reservation_lifecycle import on_constraints_changed
        _changed_set = set()
        if old_male != existing.male_count:
            _changed_set.add("male_count")
        if old_female != existing.female_count:
            _changed_set.add("female_count")
        if old_party_size != existing.party_size:
            _changed_set.add("party_size")
        if old_gender != existing.gender:
            _changed_set.add("gender")
        on_constraints_changed(db, existing, _changed_set, actor="naver_sync")

    # F1: SMS 필터 영향 필드 변경 시 칩 재동기화 (sync-sms-tags PR4 후 5종 통합)
    #   reservations.py::PATCH 는 _SMS_TAG_FIELDS 변경 시 reconcile_all_chips 를 호출하는데,
    #   naver_sync 경로에서는 `gender` / `naver_room_type` 만 실제로 변경 가능
    #   (section/party_type/notes 는 _update_reservation 이 만지지 않음).
    #   column_match 필터가 이 두 필드를 참조할 수 있어 stale 칩 방지용으로 동기화.
    _sms_fields_changed = (
        existing.gender != old_gender or
        existing.naver_room_type != old_naver_room_type
    )
    if _sms_fields_changed and existing.status == ReservationStatus.CONFIRMED:
        diag(
            "naver_sync.sms_field_changed",
            level="critical",
            reservation_id=existing.id,
            gender_changed=(existing.gender != old_gender),
            naver_room_type_changed=(existing.naver_room_type != old_naver_room_type),
        )
        try:
            db.flush()
            # 5종 칩 통합 — naver sms field (gender / room_type) 변경 시 party3
            # / surcharge 등 영향 가능 (sync-sms-tags PR4).
            from app.services.reconcile import reconcile_all_chips
            reconcile_all_chips(db, existing.id)
        except Exception as e:
            logger.warning(f"naver_sync sms field-change reconcile_all_chips failed: {e}")

    existing.updated_at = datetime.now(timezone.utc)
