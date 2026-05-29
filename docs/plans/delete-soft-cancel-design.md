# 사전조사 — `DELETE /reservations/{id}` 네이버 예약 soft-cancel 라우팅

> 분류: 🔵 운영 가시 변화 (네이버 예약 삭제 시 row 잔존 + CancelledZone 이동)
> 변경 규모: backend 3 파일 / frontend 2 파일
> 회귀 차단: 5/15 `6519493` (1분 38초 뒤 `10ca466` 으로 revert) 의 재발 방지

---

## 1. 목적

`DELETE /reservations/{id}` 가 현재는 `db.delete(row)` 로 물리 삭제. 네이버 발 예약(`naver_booking_id` 있음)을 운영자가 객실배정 페이지에서 삭제하면, 5분 후 `naver_sync` 가 네이버 API 에서 `confirmed` 상태로 재수신 → `existing_map` 매칭 실패 → `_create_reservation` 으로 신규 row 부활.

→ "운영자가 지웠지만 네이버는 여전히 살아있음" 상태를 표현할 수단이 없는 게 근본 원인.

본 변경은 **삭제 = "운영자가 시스템에서만 보이지 않게 처리"** 로 의미를 재정의:
- row 자체는 살려둠 (`status=CANCELLED`, `cancelled_at` 마킹, `manually_edited_fields["status"]=True` 핀)
- 화면에서는 기존 CancelledZone 컴포넌트로 이동 (이미 존재)
- 발송 완료 SMS 칩(`sent_at NOT NULL`)은 보존, 미발송 칩은 정리
- naver_sync 가 핀 가드로 status 부활 차단

---

## 2. 배경 — 5/15 패치 revert 회고

`6519493` (`2026-05-15 14:40:12`) 가 본 변경과 유사한 패치를 도입했으나 1분 38초 뒤 `10ca466` 로 revert. 본 변경은 그 패치 대비 **두 가지 보강**:

| 항목 | 5/15 원본 | 본 변경 | 비고 |
|---|---|---|---|
| cascade 처리 | `on_reservation_deleted` 호출 (RA/칩/DailyInfo/PartyCheckin 전체 삭제) | `on_status_cancelled` 호출 (RA 정리 + `protect_sent=True` 로 발송 이력 보존) | 1분 revert 의 가장 유력한 원인 제거 |
| 복구 경로 (재활성) | 핀 해제 로직 없음 | `update_reservation` PATCH `status=confirmed` 시 자동 핀 해제 + 컨텍스트 메뉴 "삭제 취소" 단일 액션 | 핀 영구화 silent drift 차단 |

---

## 3. 변경 범위

| 파일 | 라인 | 변경 종류 | 분류 |
|---|---|---|---|
| `backend/app/api/reservations.py::delete_reservation` | 432-459 | DELETE 분기 추가 (naver/manual) | 🔵 동작 변화 (의도) |
| `backend/app/api/reservations.py::update_reservation` | 337-376 | status=CONFIRMED 분기 추가 (핀 해제) | 🔵 동작 변화 (의도) |
| `backend/app/services/naver_sync.py::_update_reservation` | 748-753 | status 핀 가드 추가 | 🔵 동작 변화 (의도) |
| `backend/app/services/reservation_mutator.py::FIELD_PERMISSIONS` | 50 | `status` NAVER `always` → `guarded` | ⚪ 안전망 (현재 caller 없음) |
| `frontend/src/pages/RoomAssignment.tsx` | ~565 | CancelledZone 컨텍스트 메뉴: "삭제 취소" 단일 액션 | 🔵 UX 변화 |
| `frontend/src/services/api.ts` / `frontend/src/pages/Reservations.tsx` / `frontend/src/pages/RoomAssignment/hooks/useReservationForm.ts` | toast | "삭제 완료" → API 응답 메시지 표시 (네이버 발은 "취소 처리되었습니다") | 🟡 메시지 정합 |

---

## 4. 변경 대상 코드 — Before / After

### 4-1. `backend/app/api/reservations.py::delete_reservation` (L432-459)

**Before**:
```python
@router.delete("/{reservation_id}", response_model=ActionResponse)
async def delete_reservation(reservation_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Delete a reservation"""
    db_reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not db_reservation:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    # 연박 그룹 정리 (삭제 전에 unlink해야 남은 멤버의 is_long_stay가 복원됨)
    if db_reservation.stay_group_id:
        from app.services.consecutive_stay import unlink_from_group
        unlink_from_group(db, reservation_id)

    # 연관 레코드 정리 (lifecycle 단계 #12)
    from app.services.reservation_lifecycle import on_reservation_deleted
    on_reservation_deleted(db, reservation_id)

    db.delete(db_reservation)
    db.commit()

    diag("reservation.deleted", level="critical", reservation_id=reservation_id,
         actor=current_user.username if current_user else None,
         customer_name=db_reservation.customer_name)

    return {"success": True, "message": "예약이 삭제되었습니다"}
```

**After**:
```python
@router.delete("/{reservation_id}", response_model=ActionResponse)
async def delete_reservation(reservation_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Delete a reservation.

    네이버 예약 (naver_booking_id 있음): soft cancel.
      - status=CANCELLED + cancelled_at=now + mef["status"]=True 핀
      - on_status_cancelled 로 RA 정리 (sent 칩은 protect_sent=True 로 보존)
      - stay_group unlink + peer 칩 reconcile (수동 PATCH CANCELLED 와 동일 정책)
    수동 예약 (naver_booking_id 없음): 기존 hard delete.
    """
    from datetime import datetime
    from app.config import KST, today_kst
    from app.db.models import ReservationStatus
    from app.services.reservation_lifecycle import on_status_cancelled, on_reservation_deleted

    db_reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not db_reservation:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    is_soft_cancel = bool(db_reservation.naver_booking_id)

    # 연박 그룹 정리 (양 경로 공통 — unlink 후 peer 의 is_long_stay 복원).
    # peer 칩 reconcile 은 양 경로 다 필요 (stay_filter='exclude' 등 영향).
    peer_ids: list[int] = []
    if db_reservation.stay_group_id:
        from app.services.consecutive_stay import unlink_from_group
        peer_ids = [
            r.id for r in db.query(Reservation).filter(
                Reservation.stay_group_id == db_reservation.stay_group_id,
                Reservation.id != reservation_id,
            ).all()
        ]
        unlink_from_group(db, reservation_id)

    if is_soft_cancel:
        # 네이버 예약: row 살려두고 cancelled 마킹 + RA/미발송 칩 정리.
        today_str = today_kst()
        check_in_str = str(db_reservation.check_in_date) if db_reservation.check_in_date else ""
        is_same_day = (check_in_str == today_str)
        on_status_cancelled(db, db_reservation, same_day=is_same_day)

        # status 핀 (다음 naver_sync 가 confirmed 로 되돌리지 못하게 차단).
        mef = dict(db_reservation.manually_edited_fields or {})
        mef["status"] = True
        db_reservation.manually_edited_fields = mef
        db_reservation.status = ReservationStatus.CANCELLED
        db_reservation.cancelled_at = datetime.now(KST).replace(tzinfo=None)
    else:
        # 수동 예약: 기존 cascade 삭제.
        on_reservation_deleted(db, reservation_id)
        db.delete(db_reservation)

    # peer 칩 재동기화 (양 경로 공통).
    if peer_ids:
        db.flush()
        from app.services.reconcile import reconcile_all_chips
        for peer_id in peer_ids:
            try:
                reconcile_all_chips(db, peer_id)
            except Exception as e:
                logger.warning(f"peer reconcile_all_chips after delete failed: res={peer_id} err={e}")

    db.commit()

    diag("reservation.deleted", level="critical", reservation_id=reservation_id,
         actor=current_user.username if current_user else None,
         customer_name=db_reservation.customer_name,
         soft_cancel=is_soft_cancel)

    return {
        "success": True,
        "message": "예약이 취소 처리되었습니다" if is_soft_cancel else "예약이 삭제되었습니다",
    }
```

**변경 의도**:
- `is_soft_cancel = bool(naver_booking_id)` 단일 분기 변수
- `on_status_cancelled` (sent 칩 보존) ↔ `on_reservation_deleted` (전부 cascade) 분기
- `manually_edited_fields["status"]=True` 핀 — naver_sync 의 status 부활 차단
- `cancelled_at` KST naive datetime (기존 PATCH 분기 / `_parse_datetime` 출력과 동일 포맷)
- stay_group unlink + peer reconcile 을 try 블록 밖으로 빼서 양 경로 공통화 (기존 PATCH cancel 패턴과 1:1)

---

### 4-2. `backend/app/api/reservations.py::update_reservation` — status=CONFIRMED 분기 추가 (L337 직전 또는 L376 직후)

**Before**: status=CANCELLED 분기만 존재 (L341-376).

**After** — CANCELLED 분기 직후에 다음 블록 추가:
```python
# CANCELLED → CONFIRMED 복구 경로 — 운영자가 "삭제 취소" 액션 실행.
# mef["status"] 핀이 남아있으면 다음 naver_sync 가 영원히 status 갱신 못 함 (silent drift).
# delete_reservation 의 soft-cancel 핀을 여기서 해제.
if (
    "status" in update_data
    and update_data["status"] == ReservationStatus.CONFIRMED
):
    mef = dict(db_reservation.manually_edited_fields or {})
    if "status" in mef:
        del mef["status"]
        db_reservation.manually_edited_fields = mef
        diag(
            "reservation.status_pin_released",
            level="critical",
            reservation_id=reservation_id,
            actor=current_user.username if current_user else None,
        )
    # cancelled_at 도 클리어 (재활성 = 취소 시각 무효)
    if db_reservation.cancelled_at:
        db_reservation.cancelled_at = None
```

**변경 의도**:
- mef["status"] 핀 자동 해제 — UI 메뉴 우회 경로(자동화 스크립트 등)에서도 안전
- `cancelled_at = None` — paired-state invariant (`CANCELLED ⇔ cancelled_at NOT NULL`) 유지
- diag 발화로 운영 가시성 확보

> Note: RA / 칩 자동 복원은 본 단계 비목표. 운영자가 필요시 수동 재배정.

---

### 4-3. `backend/app/services/naver_sync.py::_update_reservation` — status 핀 가드 (L748-753)

**Before**:
```python
    # Update status based on Naver status
    naver_status = res_data.get("status", "confirmed")
    _prev_status = existing.status
    if naver_status == "confirmed":
        existing.status = ReservationStatus.CONFIRMED
    elif naver_status == "cancelled":
        existing.status = ReservationStatus.CANCELLED
        # S4 fix: 취소 시 manually_extended_until 클리어
        if existing.manually_extended_until:
            existing.manually_extended_until = None
            existing.check_out_pinned = False
```

**After**:
```python
    # Update status based on Naver status.
    # manually_edited_fields["status"] 핀 — 운영자 수동 취소. 네이버 상태와 무관하게 유지.
    naver_status = res_data.get("status", "confirmed")
    _prev_status = existing.status
    _mef = existing.manually_edited_fields or {}
    _status_pinned = "status" in _mef
    if _status_pinned:
        # 운영자 DELETE 로 cancelled 처리됨 — 네이버가 confirmed/cancelled 어느 쪽이든 무시.
        # cancelled_at 만 네이버 값으로 정밀화 (L726 에서 별도 처리, 핀 무관).
        if _prev_status != ReservationStatus.CANCELLED:
            # 방어적 — 핀이 있는데 status 가 CANCELLED 가 아니면 invariant 위반.
            # 운영 가시성을 위해 diag, 그러나 강제 보정하지는 않음 (caller 책임).
            diag("naver_sync.status_pin_invariant_violation", level="critical",
                 reservation_id=existing.id, prev_status=str(_prev_status))
    elif naver_status == "confirmed":
        existing.status = ReservationStatus.CONFIRMED
    elif naver_status == "cancelled":
        existing.status = ReservationStatus.CANCELLED
        if existing.manually_extended_until:
            existing.manually_extended_until = None
            existing.check_out_pinned = False
```

**변경 의도**:
- 가드 위치: status 처리의 가장 처음(`naver_status` 읽은 직후).
- `cancelled_at` 덮어쓰기는 별도 L726 — 핀 영향 없음 (타임스탬프 정밀화는 정합성 측면에서 OK).
- invariant 위반 시 diag 만 발화 (auto-correct 안 함 — 데이터 손상 회피).
- `_prev_status != existing.status` 트랜지션 블록(L760~) 은 status 변경 시에만 동작하므로 핀 발동 시 자동 skip.

---

### 4-4. `backend/app/services/reservation_mutator.py::FIELD_PERMISSIONS` (L50) — 옵션 안전망

**Before**:
```python
    "status":           {ChangeSource.NAVER: "always",  ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
```

**After**:
```python
    "status":           {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
```

**변경 의도** (defense-in-depth):
- 현 시점 `ReservationMutator.apply_changes(NAVER, {"status": ...})` 호출자 0건 → 즉시 효과 없음.
- 미래에 누가 status 변경을 Mutator 경유로 보낼 때 자동으로 핀 가드 발동.
- `_PIN_ATTR_FOR` 에 `"status"` 추가는 **하지 않음** (status 는 pin 컬럼 없이 mef dict 전용 가드).
- `apply_changes` L128-149 guarded 로직: pin 컬럼 없으면 `is_pinned_dict = field in edits` 만 체크 → mef["status"]=True 면 skip.

본 변경 단독으로는 효과 0. **`4-3` 가드가 실질적 효과의 100%.** 시간 압박 시 **이 변경 생략 가능**.

---

### 4-5. Frontend — CancelledZone 컨텍스트 메뉴 + 토스트 정합

**Before**:
- `frontend/src/pages/RoomAssignment.tsx` L555-570: 컨텍스트 메뉴 `onDelete` 가 zone 무관 노출.
- 3개 페이지의 toast: `'삭제 완료'` 하드코딩.

**After**:
- CancelledZone 행 우클릭 시 컨텍스트 메뉴 = **"삭제 취소" 단일 액션**:
  ```ts
  // RoomAssignment.tsx contextMenuActions 분기
  if (res.status === 'cancelled') {
    return [
      { label: '삭제 취소', onClick: async () => {
        await reservationsAPI.update(id, { status: 'confirmed' });
        _invalidateReservations();
      }},
    ];
  }
  // 기존 메뉴 (active 행 전용)
  ```
- 토스트 메시지: API 응답의 `message` 필드를 표시 (현재 일부 페이지는 무시). 응답이 `"예약이 취소 처리되었습니다"` 또는 `"예약이 삭제되었습니다"` 면 자동 반영.

---

## 5. 동작 동등성

### 5-1. 수동 예약(naver_booking_id 없음) — 변화 0

| 시나리오 | Before | After | 동등 |
|---|---|---|---|
| 수동 예약 삭제 | `db.delete` + `on_reservation_deleted` cascade | 동일 (분기 `is_soft_cancel=False`) | ✅ |
| 수동 예약 stay_group | unlink + (peer reconcile 없음) | unlink + peer reconcile 추가 | ⚪ 의도된 보강 (5/15 패치도 안 했던 부분) |

### 5-2. 네이버 예약 — 본 변경의 의도된 변화

| 시나리오 | Before | After |
|---|---|---|
| 객실배정 페이지에서 네이버 예약 삭제 | row 물리 제거 → 5분 후 부활 | row 잔존 (status=CANCELLED, mef["status"]=True) → 부활 차단 |
| 화면 표시 | 사라짐 | CancelledZone 으로 이동 (line-through + 취소 시각) |
| sent SMS 칩 | cascade 삭제 (이력 손실) | `protect_sent=True` 로 보존 |
| 미발송 SMS 칩 | cascade 삭제 | 동일 (`force=True, protect_sent=True` → unsent 만 삭제) |
| 다음 naver_sync (네이버 confirmed) | `_create_reservation` 으로 신규 생성 | `existing_map` 매칭 성공 → `_update_reservation` 진입 → 핀 가드로 status 유지 |
| 다음 naver_sync (네이버 cancelled) | `_create_reservation` 분기 안 탐 (cancelled 도 sync 대상) | 핀 가드로 status 유지 (어차피 둘 다 CANCELLED) |

### 5-3. peer 칩 reconcile

| 케이스 | Before | After | 판정 |
|---|---|---|---|
| stay_group 의 한 멤버 hard delete | unlink → peer 의 is_long_stay 복원, peer 칩 reconcile **없음** (PATCH 와 비대칭) | unlink + peer reconcile_all_chips | ⚪ 의도된 보강 (asymmetric update fix) |

---

## 6. 시나리오 매트릭스

| # | 진입점 | 사전조건 | 액션 | 기대 결과 | 판정 |
|---|---|---|---|---|---|
| 1 | 운영자 | 네이버 예약, naver=confirmed | DELETE | status=CANCELLED + mef["status"]=True + CancelledZone 이동 | ✅ |
| 2 | naver_sync (5분 후) | #1 직후 | sync 응답 confirmed | 핀 가드로 status 유지 | ✅ |
| 3 | naver_sync | #1 직후 + 네이버에서도 진짜 취소 | sync 응답 cancelled | 핀 가드로 status 유지 (둘 다 CANCELLED) + cancelled_at 정밀화 | ✅ |
| 4 | 운영자 | #1 직후 (잘못 삭제) | CancelledZone 컨텍스트 메뉴 "삭제 취소" → PATCH status=confirmed | mef["status"] 자동 해제, cancelled_at=None, status=CONFIRMED, 활성 zone 복귀 | ✅ |
| 5 | naver_sync | #4 직후 | sync 응답 confirmed | 핀 없음 → 정상 동작 (status 그대로 CONFIRMED) | ✅ |
| 6 | 운영자 | 수동 예약(naver_booking_id=None) | DELETE | 기존 hard delete (변화 0) | ✅ |
| 7 | 운영자 | 같은 booking_id 로 재예약 | 환불 후 네이버 재결제 | 네이버는 새 booking_id 발급 → `existing_map` 매칭 안 됨 → 신규 row 생성 (정상) | ✅ |
| 8 | 운영자 | sent 칩 있는 예약 삭제 | DELETE | sent 칩 보존, CancelledZone 에 표시. 미발송 칩만 삭제 | ✅ |
| 9 | 자동화 스크립트 / API | #1 직후 | PATCH status=confirmed (UI 우회) | 4-2 의 핀 해제 로직이 자동 동작 | ✅ |
| 10 | naver_sync | invariant 위반 (핀 있는데 status=CONFIRMED) | sync | diag `naver_sync.status_pin_invariant_violation` critical 발화, auto-correct 없음 | ✅ |

---

## 7. 데이터 마이그레이션 영향

- **기존 cancelled row** (현 DB 의 cancelled 예약들): `mef["status"]` 핀이 없는 상태. 본 변경 머지 후 다음 naver_sync 가 들어오면 4-3 가드에서 `_status_pinned=False` 라 기존 로직 그대로 동작 → 동작 변화 0. ✅
- **신규 마이그레이션 불필요** — 기존 컬럼(`status`, `cancelled_at`, `manually_edited_fields`) 그대로 사용.
- **컬럼 default**: `manually_edited_fields` 는 nullable JSON, 기존 default `{}`. `mef.get("status")` 가 KeyError 안 냄.

---

## 8. 롤백 전략

```bash
# 5/15 처럼 단순 revert
git revert <merge-sha>
```

revert 시 :
- 핀 박혀있는 row들은 그대로 (`mef["status"]=True` 잔존). 다음 naver_sync 가 status 를 그대로 둠 (가드 코드 사라졌으니 4-3 분기 안 들어가지만, `if naver_status == "confirmed":` 가 다시 실행됨 → cancelled 였던 row 가 confirmed 로 부활).
- 즉 revert 직후 한 차례 sync 사이클에서 핀 박힌 row 들이 다시 활성화될 수 있음. **운영자가 다시 삭제하면 hard delete 로 처리됨 (기존 동작)**.
- 데이터 손상 없음.

**Hot rollback 필요 시**: 4-3 가드 한 줄만 주석 처리해도 5/15 revert 시 발생했던 cascade 손상 없이 즉시 기존 동작 복귀 (`is_soft_cancel` 분기는 그대로 두고 status 가 매 sync 마다 confirmed 로 덮어쓰여짐).

---

## 9. 미해결 질문

1. **재활성 시 RA 자동 복원?** — 본 변경은 `update_reservation` PATCH `status=confirmed` 에서 핀만 해제. RA 는 운영자가 수동 재배정. (자동 복원하려면 cancel 시 RA 를 cascade 삭제 안 하고 `is_active=False` 같은 flag 도입 필요 — 본 변경 범위 밖.)
2. **stay_group 자동 재연결?** — unlink 된 그룹은 운영자가 수동 재연결. consecutive_stay 자동 감지가 다음 sync 에서 트리거되긴 함.
3. **컨텍스트 메뉴 vs 일괄 액션** — 우클릭 일괄 삭제 (RoomAssignment.tsx L565) 가 cancelled 행을 포함할 때 처리 방향. 본 PR 에서는 cancelled 행을 일괄 액션 대상에서 자동 제외 (drag/click 비활성 패턴 차용).
4. **운영자 수동 cancel vs DELETE soft-cancel 의 mef["status"] 동등성** — ✅ **해결됨 (followup-234 §3)**.
   `FIELD_PERMISSIONS["status"]` 를 NAVER `guarded` 로 둠으로써, mutator auto-mark(L170-173)가 MANUAL PATCH
   `status=cancelled` 에도 `mef["status"]=timestamp` 핀을 자동으로 박는다. 즉 DELETE(우클릭 삭제)와 PATCH
   취소가 **동일하게** 네이버 부활을 차단하고 `is_manual_cancel=True` 로 CancelledZone 에 노출된다.
   "어떤 경로의 운영자 취소든 네이버가 못 살린다" 는 통일 동작으로 의도 확정. 복구는 PATCH `status=confirmed`
   가 restore 블록에서 핀 해제. (별도 plan 불필요.)

---

## 10. 적용 순서 (시간 압박 시 우선순위)

1. **🔴 필수** — `4-1` (delete_reservation 분기) + `4-3` (naver_sync 핀 가드). 이 두 개만 있어도 핵심 이슈 해결.
2. **🔴 필수** — `4-2` (PATCH status=confirmed 핀 해제). 없으면 silent drift 잔존.
3. **🔵 권장** — `4-5` frontend 컨텍스트 메뉴 + 토스트. UX 정합.
4. **⚪ 옵션** — `4-4` FIELD_PERMISSIONS guarded. 안전망.

---

## 11. 검증 체크리스트 (적용 후)

- [ ] DELETE 네이버 예약 → CancelledZone 이동 + sent 칩 잔존
- [ ] 5분 후 sync → CancelledZone 유지 (status_changed diag 없음)
- [ ] CancelledZone 컨텍스트 메뉴 "삭제 취소" 클릭 → 활성 zone 복귀 + diag `reservation.status_pin_released` 발화
- [ ] 복귀 후 sync → 정상 동작 (status 변경 가능)
- [ ] DELETE 수동 예약 → hard delete (기존 동작)
- [ ] diag-golden 정답지 업데이트 — `reservation.deleted` 에 `soft_cancel` 필드 추가, `reservation.status_pin_released` / `naver_sync.status_pin_invariant_violation` 신규 이벤트 등록.
