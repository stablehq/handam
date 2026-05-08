"""
Consecutive stay (연박) detection and linking service.

Detects guests who made separate single-day bookings for consecutive dates
and links them via a shared stay_group_id (UUID).

Detection criteria:
  - Same (customer_name, phone) OR (visitor_name, phone) OR (customer_name, visitor_phone)
  - A.check_out_date == B.check_in_date
  - Both CONFIRMED status

Idempotent: safe to run multiple times. Auto-unlinks stale groups.
"""
import logging
import uuid
from collections import defaultdict
from typing import List

from sqlalchemy.orm import Session

from app.db.models import Reservation, ReservationStatus
from app.db.tenant_context import get_session_tenant_id
from app.diag_logger import diag

logger = logging.getLogger(__name__)


def compute_is_long_stay(res) -> bool:
    """연박자(2박+) OR naver 연속 그룹(stay_group_id) 판단.

    After extend-stay refactor (2026-05-09): merged single-record multi-day
    stays have stay_group_id=NULL but check_out_date - check_in_date > 1 day,
    so the date-diff branch correctly catches them.
    """
    if res.stay_group_id:
        return True
    if res.check_in_date and res.check_out_date:
        from datetime import date as date_type
        try:
            ci = date_type.fromisoformat(str(res.check_in_date))
            co = date_type.fromisoformat(str(res.check_out_date))
            return (co - ci).days > 1
        except ValueError:
            return False
    return False


def detect_and_link_consecutive_stays(db: Session, tenant_id: int = None) -> dict:
    """
    Scan all CONFIRMED reservations and link consecutive stays.

    Groups by (name, phone) identity, sorts by check_in_date,
    and links where A.check_out_date == B.check_in_date.

    Idempotent: re-scans every time. Unlinks reservations that are
    no longer consecutive. Preserves existing group IDs where valid.

    Args:
        tenant_id: explicit tenant scope. Falls back to ContextVar if omitted.

    Returns:
        dict with counts: {"linked": N, "unlinked": M, "groups": G}
    """
    diag("stay_group.detect.enter", level="verbose")
    tid = tenant_id or get_session_tenant_id(db)
    if tid is None:
        raise RuntimeError("detect_and_link_consecutive_stays requires tenant context")

    # 임박한 예약만 스캔 — 체크아웃이 오늘 이후이고 체크인이 5일 이내.
    # — 과거 예약은 감지해도 배정/SMS 에 반영될 일 없음 (이미 이벤트 끝남).
    # — 먼 미래 예약은 입실일 가까워지면 다음 주기 감지에서 자동 커버됨 (5분 + 피크 10분).
    # — 과거 예약의 기존 stay_group_id 는 스캔에서 빠지므로 그대로 보존.
    from datetime import timedelta
    from app.config import today_kst, today_kst_date
    today_str = today_kst()
    max_checkin = (today_kst_date() + timedelta(days=5)).strftime("%Y-%m-%d")
    # excluded 카운트: stay_group_excluded=True 인 예약은 자동 재묶기에서 제외
    excluded_skipped = (
        db.query(Reservation)
        .filter(
            Reservation.tenant_id == tid,
            Reservation.status == ReservationStatus.CONFIRMED,
            Reservation.check_out_date.isnot(None),
            Reservation.check_out_date >= today_str,
            Reservation.check_in_date <= max_checkin,
            Reservation.phone.isnot(None),
            Reservation.phone != "",
            Reservation.stay_group_excluded == True,
        )
        .count()
    )
    reservations = (
        db.query(Reservation)
        .filter(
            Reservation.tenant_id == tid,
            Reservation.status == ReservationStatus.CONFIRMED,
            Reservation.check_out_date.isnot(None),
            Reservation.check_out_date >= today_str,
            Reservation.check_in_date <= max_checkin,
            Reservation.phone.isnot(None),
            Reservation.phone != "",
            Reservation.stay_group_excluded == False,
        )
        .order_by(Reservation.check_in_date)
        .all()
    )

    # Build identity groups: multiple keys per reservation for fuzzy matching
    identity_map: dict[str, list[Reservation]] = defaultdict(list)
    siblings_skipped = 0
    for res in reservations:
        # naver_split sibling 은 chain 후보에서 제외.
        # 같은 customer_name+phone 으로 묶이면 sibling 이 다음날 진짜 예약과 가짜 chain 을
        # 형성해 primary 가 stay_group 에서 누락되는 정합성 위반 발생 (CRITICAL).
        if res.booking_source == "naver_split":
            siblings_skipped += 1
            continue
        name = (res.customer_name or "").strip()
        phone = (res.phone or "").strip()
        if name and phone:
            identity_map[f"{name}|{phone}"].append(res)
        # Also match visitor_name/visitor_phone combinations
        vname = (res.visitor_name or "").strip()
        vphone = (res.visitor_phone or "").strip()
        if vname and phone and vname != name:
            identity_map[f"{vname}|{phone}"].append(res)
        if name and vphone and vphone != phone:
            identity_map[f"{name}|{vphone}"].append(res)

    # Deduplicate: merge groups that share reservations
    res_to_group: dict[int, set[int]] = {}
    for _key, group in identity_map.items():
        if len(group) < 2:
            continue
        res_ids = {r.id for r in group}
        # Find existing merged groups
        merged = set()
        for rid in res_ids:
            if rid in res_to_group:
                merged |= res_to_group[rid]
        merged |= res_ids
        for rid in merged:
            res_to_group[rid] = merged

    # Build final groups (sets of reservation IDs)
    seen_groups: list[set[int]] = []
    seen_ids: set[int] = set()
    for rid, group in res_to_group.items():
        if rid not in seen_ids:
            seen_groups.append(group)
            seen_ids |= group

    # Build reservation lookup
    res_lookup = {r.id: r for r in reservations}

    linked_count = 0
    unlinked_count = 0
    group_count = 0

    # Track which reservations should be in a stay group
    should_be_grouped: set[int] = set()

    for group_ids in seen_groups:
        # Sort by check_in_date
        group_res = sorted(
            [res_lookup[rid] for rid in group_ids if rid in res_lookup],
            key=lambda r: r.check_in_date,
        )
        if len(group_res) < 2:
            continue

        # Find consecutive chains within this identity group
        chains: list[list[Reservation]] = []
        current_chain = [group_res[0]]

        for i in range(1, len(group_res)):
            prev = current_chain[-1]
            curr = group_res[i]
            if prev.check_out_date and prev.check_out_date == curr.check_in_date:
                current_chain.append(curr)
            else:
                if len(current_chain) >= 2:
                    chains.append(current_chain)
                current_chain = [curr]

        if len(current_chain) >= 2:
            chains.append(current_chain)

        # Assign stay_group_id to each chain
        for chain in chains:
            group_count += 1
            # Reuse existing group ID if any member already has one
            existing_group_id = None
            for res in chain:
                if res.stay_group_id:
                    existing_group_id = res.stay_group_id
                    break
            group_id = existing_group_id or str(uuid.uuid4())

            diag(
                "stay_group.chain_formed",
                level="verbose",
                group_id=group_id,
                member_count=len(chain),
            )

            for order, res in enumerate(chain):
                should_be_grouped.add(res.id)
                is_last = (order == len(chain) - 1)
                if res.stay_group_id != group_id or res.stay_group_order != order or res.is_last_in_group != is_last:
                    res.stay_group_id = group_id
                    res.stay_group_order = order
                    res.is_last_in_group = is_last
                    res.is_long_stay = True
                    linked_count += 1
                elif not res.is_long_stay:
                    res.is_long_stay = True

    # Unlink reservations that are no longer consecutive
    for res in reservations:
        if res.stay_group_id and res.id not in should_be_grouped and not res.stay_group_id.startswith("manual-"):
            res.stay_group_id = None
            res.stay_group_order = None
            res.is_last_in_group = None
            res.is_long_stay = compute_is_long_stay(res)
            unlinked_count += 1

    if linked_count > 0 or unlinked_count > 0:
        db.flush()

    result = {"linked": linked_count, "unlinked": unlinked_count, "groups": group_count}
    if linked_count > 0 or unlinked_count > 0:
        logger.info(f"Consecutive stay detection: {result}")
    diag(
        "stay_group.detect.exit",
        level="verbose",
        linked=result["linked"],
        unlinked=result["unlinked"],
        groups=result["groups"],
        siblings_skipped=siblings_skipped,
        excluded_skipped=excluded_skipped,
    )
    return result


def unlink_from_group(
    db: Session,
    reservation_id: int,
    exclude_from_auto_link: bool = False,
) -> bool:
    """
    Remove a reservation from its stay group.
    Re-orders remaining members. If only 1 member remains, dissolves the group.

    Args:
        exclude_from_auto_link: True 이면 stay_group_excluded=True 를 설정해
            자동 재묶기(detect_and_link_consecutive_stays)에서 영구 제외.
            사용자 의도(수동 unlink) 경로에서만 True 로 호출해야 함.
            시스템 자동 unlink(네이버 sync, cascade) 경로는 기본값 False 사용.

    Returns True if the reservation was unlinked.
    """
    tid = get_session_tenant_id(db)

    query = db.query(Reservation).filter(Reservation.id == reservation_id)
    if tid:
        query = query.filter(Reservation.tenant_id == tid)
    res = query.first()
    if not res or not res.stay_group_id:
        return False

    group_id = res.stay_group_id
    diag(
        "stay_group.unlinked",
        level="critical",
        res_id=reservation_id,
        group_id=group_id,
        excluded=exclude_from_auto_link,
    )
    res.stay_group_id = None
    res.stay_group_order = None
    res.is_last_in_group = None
    if exclude_from_auto_link:
        res.stay_group_excluded = True
    res.is_long_stay = compute_is_long_stay(res)

    # Re-order remaining members
    remaining_q = (
        db.query(Reservation)
        .filter(
            Reservation.stay_group_id == group_id,
            Reservation.id != reservation_id,
        )
    )
    if tid:
        remaining_q = remaining_q.filter(Reservation.tenant_id == tid)
    remaining = remaining_q.order_by(Reservation.stay_group_order).all()

    if len(remaining) <= 1:
        # Dissolve group if only 1 member left
        for r in remaining:
            r.stay_group_id = None
            r.stay_group_order = None
            r.is_last_in_group = None
            r.is_long_stay = compute_is_long_stay(r)
    else:
        for i, r in enumerate(remaining):
            r.stay_group_order = i
            r.is_last_in_group = (i == len(remaining) - 1)

    db.flush()
    return True


def _validate_link_inputs(reservations: List[Reservation]) -> None:
    """수동 연박 묶기 입력 검증. 실패 시 ValueError.

    조건:
      - 2건 이상
      - 모두 CONFIRMED
      - check_in_date 오름차순 정렬 시 아래 중 하나를 만족해야 "연속"으로 인정:
          (a) prev.check_out_date == curr.check_in_date  (표준 체크아웃/체크인 연결)
          (b) prev.check_out_date IS NULL 이고 prev.check_in_date + 1일 == curr.check_in_date
              (수동 입력 1박 예약 호환 — checkout 이 비어 있어도 이어진다고 판단)
    """
    if len(reservations) < 2:
        diag("stay_group.validate_failed", level="verbose",
             reason="too_few", count=len(reservations))
        raise ValueError("예약 2개 이상이 필요합니다")

    for r in reservations:
        if r.status != ReservationStatus.CONFIRMED:
            name = r.customer_name or f"예약#{r.id}"
            diag("stay_group.validate_failed", level="verbose",
                 reason="not_confirmed", reservation_id=r.id,
                 status=getattr(r.status, 'value', str(r.status)))
            raise ValueError(f"{name} 님은 확정 상태가 아닙니다")

    sorted_res = sorted(reservations, key=lambda r: r.check_in_date or "")
    for i in range(len(sorted_res) - 1):
        prev = sorted_res[i]
        curr = sorted_res[i + 1]
        # 표준 케이스: prev.check_out == curr.check_in (완전 연결)
        if prev.check_out_date and prev.check_out_date == curr.check_in_date:
            continue
        # NULL check_out: "1박 예약"으로 해석 → check_in + 1일 = 다음 check_in 이면 연속으로 인정
        # (수동 입력 예약 등에서 check_out 이 NULL 인 케이스 호환)
        if prev.check_out_date is None and prev.check_in_date:
            from datetime import datetime as _dt, timedelta as _td
            try:
                next_day = (_dt.strptime(prev.check_in_date, "%Y-%m-%d") + _td(days=1)).strftime("%Y-%m-%d")
                if next_day == curr.check_in_date:
                    continue
            except (ValueError, TypeError):
                pass
        diag("stay_group.validate_failed", level="verbose",
             reason="dates_not_consecutive",
             prev_id=prev.id, curr_id=curr.id,
             prev_checkout=prev.check_out_date, curr_checkin=curr.check_in_date)
        raise ValueError("예약 날짜가 이어지지 않습니다")


def link_reservations(db: Session, reservation_ids: List[int]) -> tuple[str, List[int]]:
    """
    Manually link multiple reservations into a stay group.

    동작:
      1. 입력 ID 로 예약 로드
      2. 기존 그룹 멤버(CONFIRMED 만) 자동 확장 — 부분 선택 실수로 외톨이 발생 방지
      3. 정렬 후 검증 (_validate_link_inputs)
      4. 항상 새 manual-UUID 생성 (사용자 개입 = manual 격리)
      5. 전체 멤버에 group_id/order/is_last/is_long_stay 할당

    Returns:
        (group_id, linked_reservation_ids) — group_id 는 manual- 접두사.
        linked_reservation_ids 는 자동 확장 후 실제 그룹에 포함된 전체 ID 목록.
        호출자는 이 ID 리스트를 기준으로 sync_sms_tags 등 후속 처리를 해야 함.

    Raises:
        ValueError: 2건 미만 / 비CONFIRMED 포함 / 날짜 불연속.
    """
    reservations = (
        db.query(Reservation)
        .filter(Reservation.id.in_(reservation_ids))
        .all()
    )

    # 기존 그룹 멤버 자동 확장 (CONFIRMED 만 — stale CANCELLED 는 제외)
    existing_group_ids = {r.stay_group_id for r in reservations if r.stay_group_id}
    if existing_group_ids:
        extra = (
            db.query(Reservation)
            .filter(
                Reservation.stay_group_id.in_(existing_group_ids),
                Reservation.status == ReservationStatus.CONFIRMED,
            )
            .all()
        )
        merged = {r.id: r for r in reservations}
        for r in extra:
            merged[r.id] = r
        reservations = list(merged.values())

    reservations.sort(key=lambda r: r.check_in_date or "")

    # 검증 (실패 시 ValueError)
    _validate_link_inputs(reservations)

    # 수동 개입 표시 — 항상 새 manual- UUID 로 격리
    group_id = f"manual-{uuid.uuid4()}"

    relinked_ids = []
    for order, res in enumerate(reservations):
        if res.stay_group_excluded:
            relinked_ids.append(res.id)
        res.stay_group_id = group_id
        res.stay_group_order = order
        res.is_last_in_group = (order == len(reservations) - 1)
        res.is_long_stay = True
        res.stay_group_excluded = False  # 수동 link 시 excluded 플래그 해제

    if relinked_ids:
        diag(
            "stay_group.relinked_after_exclude",
            level="critical",
            group_id=group_id,
            res_ids=relinked_ids,
        )

    diag(
        "stay_group.manually_linked",
        level="critical",
        group_id=group_id,
        member_count=len(reservations),
    )

    db.flush()
    return group_id, [r.id for r in reservations]
