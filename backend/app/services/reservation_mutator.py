"""ReservationMutator — Reservation 필드 변경 단일 게이트웨이 (스켈레톤).

본 모듈은 단계 #1 시점에서는 어디서도 호출되지 않는다. FIELD_PERMISSIONS /
ChangeSource 정의를 후속 단계 (#4 이후 가드 추가, #11 이후 caller 전환) 가
참조할 수 있도록 인터페이스만 노출한다.

참고: docs/plans/reservation-mutator-design.md
      docs/plans/mutator-migration-plan.md
      docs/plans/mutator-step-01-mutator-skeleton.md
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.db.models import Reservation


class ChangeSource(str, Enum):
    """예약 필드 변경의 출처. FIELD_PERMISSIONS 의 행 인덱스."""

    NAVER = "naver"     # naver_sync._update_reservation 경로
    MANUAL = "manual"   # reservations.py PUT, reservations_stay extend/reduce, reservations_room 등 직원 조작
    SYSTEM = "system"   # 자동 객실 배정, push-out, reconcile 내부 처리, 마이그레이션 등


# Reservation 필드별 source 권한 — 단계 #11 부터 ReservationMutator.apply_changes 가 평가.
# 단계 #1 시점에서는 어떤 caller 도 이 테이블을 참조하지 않음.
#
# 권한 값:
#   "guarded" = 해당 필드의 pin 이 True 인 레코드에서만 skip, 아니면 덮어씀
#   "always"  = pin 무관, 항상 덮어씀
#   "never"   = 이 source 는 이 필드 변경 불가
FIELD_PERMISSIONS: dict[str, dict[ChangeSource, str]] = {
    "check_in_date":    {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "always"},
    "check_out_date":   {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "always"},
    # PR1: 5 신규 보호 필드 — NAVER always → guarded 로 변경. manually_edited_fields dict 가드.
    "customer_name":    {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "phone":            {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "visitor_name":     {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "visitor_phone":    {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "special_requests": {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "party_size":       {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "male_count":       {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "female_count":     {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "gender":           {ChangeSource.NAVER: "always",  ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "status":           {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "section":          {ChangeSource.NAVER: "never",   ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "always"},
    "naver_room_type":  {ChangeSource.NAVER: "always",  ChangeSource.MANUAL: "never",  ChangeSource.SYSTEM: "never" },
    "booking_options":  {ChangeSource.NAVER: "always",  ChangeSource.MANUAL: "never",  ChangeSource.SYSTEM: "never" },
    "total_price":      {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
}


# 단계 #11: guarded 평가 시 참조할 pin 컬럼 매핑 (확장 가능).
# 다른 guarded 필드 (party_size, male_count, total_price) 는 기존 보호 플래그
# (is_split_managed, gender_manual) 가 caller 측에서 처리 — Mutator 가 만지지 않음.
_PIN_ATTR_FOR: dict[str, str] = {
    "check_in_date": "check_in_pinned",
    "check_out_date": "check_out_pinned",
}


class ReservationMutator:
    """예약 필드 변경의 단일 진입점.

    단계 #11 에서 실제 구현. caller 가 source + fields dict 를 넘기면:
      1) FIELD_PERMISSIONS 로 source 별 권한 평가
      2) 권한 통과한 필드만 setattr
      3) check_in/out_date 변경 + source=MANUAL 시 pin 자동 세팅
      4) 적용 결과를 {필드명: (old, new)} 로 반환

    호출자는 본 함수의 결과 dict 로 "실제로 무엇이 변했나" 를 판단해서
    후속 처리 (shift_daily_records, reconcile_all_chips 등) 분기 가능.
    """

    @staticmethod
    def apply_changes(
        db: "Session",
        reservation: "Reservation",
        source: ChangeSource,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Reservation 필드 변경을 권한 검사 후 적용.

        Args:
            db: 호출자가 관리하는 트랜잭션. 본 함수는 flush/commit 하지 않음.
            reservation: 변경 대상 ORM 객체.
            source: 변경 출처 (NAVER / MANUAL / SYSTEM).
            fields: {필드명: 새 값} dict.

        Returns:
            {필드명: (old, new)} 형태로 실제 적용된 변경만 반환. 권한 거부된
            필드 + 값 동일 필드는 포함하지 않음.
        """
        from datetime import datetime, timezone
        from app.diag_logger import diag

        applied: dict[str, Any] = {}

        # 운영자 수정 방명록 — PR1 신규 가드.
        # 기존 dict 사본 (SQLAlchemy JSON mutation 감지 위해 dict() 복사 필수).
        edits = dict(reservation.manually_edited_fields or {})

        for field, new_value in fields.items():
            # 1) 권한 평가
            perm_row = FIELD_PERMISSIONS.get(field)
            if perm_row is None:
                # 미등록 필드 — caller 의지 그대로 setattr (allow-all 정책)
                permission = "always"
            else:
                permission = perm_row.get(source, "never")

            if permission == "never":
                # silent skip 가시화 — 정책 위반 caller 추적
                diag(
                    "mutator.skipped",
                    level="critical",
                    res_id=reservation.id,
                    source=source.value,
                    field=field,
                    reason="never",
                )
                continue

            if permission == "guarded":
                # 가드 평가 — 2 메커니즘 병행 (PR1 점진):
                #   1) 기존 pin 컬럼 (check_in_pinned, check_out_pinned)
                #   2) 신규 방명록 (manually_edited_fields dict)
                # PR2 에서 1번을 2번으로 통합 예정.
                pin_attr = _PIN_ATTR_FOR.get(field)
                is_pinned_column = pin_attr and getattr(reservation, pin_attr, False)
                is_pinned_dict = field in edits

                if is_pinned_column or is_pinned_dict:
                    diag(
                        "mutator.skipped",
                        level="critical",
                        res_id=reservation.id,
                        source=source.value,
                        field=field,
                        reason="pinned",
                        pin_source="column" if is_pinned_column else "dict",
                    )
                    continue
                # pin 없는 guarded 필드 (party_size, male_count 등):
                # 기존 caller 보호 로직 (is_split_managed, gender_manual) 가 미리 처리.
                # Mutator 단계에서는 always 처럼 통과.

            # 2) setattr (값 동일 시 setattr 자체는 무해하지만 applied 에 미포함)
            old_value = getattr(reservation, field, None)
            if old_value != new_value:
                setattr(reservation, field, new_value)
                applied[field] = (old_value, new_value)

        # 3) source=MANUAL 의 변경 자동 마크
        if source == ChangeSource.MANUAL and applied:
            now_iso = datetime.now(timezone.utc).isoformat()
            # 기존 pin 컬럼 자동 세팅 (점진 호환)
            if "check_in_date" in applied:
                reservation.check_in_pinned = True
            if "check_out_date" in applied:
                reservation.check_out_pinned = True
            # 방명록에 모든 변경 필드 + timestamp 기록 (가드 대상 필드만)
            for field in applied:
                perm_row = FIELD_PERMISSIONS.get(field)
                if perm_row and perm_row.get(ChangeSource.NAVER) == "guarded":
                    edits[field] = now_iso
            # SQLAlchemy 가 JSON 변경 감지하도록 새 dict 할당
            reservation.manually_edited_fields = edits

        return applied

    @staticmethod
    def release_manual_pin(reservation: "Reservation", field: str) -> bool:
        """Manual pin 해제 (방명록 dict + pin 컬럼 둘 다).

        cancel / 연박취소 경로 등 "운영자 수정 → 자동 동기화로 복귀" 의도
        호출자가 사용. 실제 해제 1건 이상 발생 시 mutator.pin_released diag 발화.

        Returns:
            True  — dict 또는 pin 컬럼 중 1건이라도 해제됨
            False — 둘 다 비어있어 no-op
        """
        from app.diag_logger import diag

        released_dict = False
        released_column = False

        edits = dict(reservation.manually_edited_fields or {})
        if field in edits:
            del edits[field]
            reservation.manually_edited_fields = edits
            released_dict = True

        pin_attr = _PIN_ATTR_FOR.get(field)
        if pin_attr and getattr(reservation, pin_attr, False):
            setattr(reservation, pin_attr, False)
            released_column = True

        if released_dict or released_column:
            diag(
                "mutator.pin_released",
                level="critical",
                res_id=reservation.id,
                field=field,
                released_dict=released_dict,
                released_column=released_column,
            )
        return released_dict or released_column
