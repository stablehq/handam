# 사전조사 — soft-cancel 후속 보강 (검증 #2·#3·#4)

> 선행 문서: `docs/plans/delete-soft-cancel-design.md`
> 분류: 🟠 안전망 + 🔵 운영 가시 변화(고아 핀 자동 정리)
> 변경 규모: backend 3 파일(naver_sync / reservations / reservation_mutator) + 설계문서 1 + 1회 DB 정리 스크립트
> 결정: 사용자 선택 — #3=guarded 유지+문서화, #2=1회정리+self-heal 둘 다

---

## 0. 배경

`delete` soft-cancel 1차 검증에서 3개 후속 항목 도출:

- **#2** 고아 핀(`mef["status"]` 있는데 `status=CONFIRMED`) 2건(res 5311, 5995) — 가드 배포 시 매 sync `status_pin_invariant_violation` critical 무한 발화 + self-heal 없음.
- **#3** `FIELD_PERMISSIONS["status"]` 를 NAVER `guarded` 로 바꾼 부수효과 — MANUAL PATCH 취소도 자동 핀. 설계문서 Q4 는 "PATCH 는 미룸"이라 모순.
- **#4** `delete_reservation` 가 `on_status_cancelled` 를 status 세팅 **전에** 호출(naver_sync 는 후) + restore 블록의 mutator-then-undo 순서 의존성 무주석.

---

## 1. #4 — `delete_reservation` 순서 정리 + restore 주석

### 1-1. `reservations.py::delete_reservation` (L491-504)

**Before**:
```python
if is_soft_cancel:
    today_str = today_kst()
    check_in_str = str(db_reservation.check_in_date) if db_reservation.check_in_date else ""
    is_same_day = (check_in_str == today_str)
    on_status_cancelled(db, db_reservation, same_day=is_same_day)   # ← status 세팅 前 호출

    mef = dict(db_reservation.manually_edited_fields or {})
    mef["status"] = True
    db_reservation.manually_edited_fields = mef
    db_reservation.status = ReservationStatus.CANCELLED
    db_reservation.cancelled_at = datetime.now(KST).replace(tzinfo=None)
```

**After**:
```python
if is_soft_cancel:
    today_str = today_kst()
    check_in_str = str(db_reservation.check_in_date) if db_reservation.check_in_date else ""
    is_same_day = (check_in_str == today_str)

    # status/cancelled_at/핀 을 먼저 확정한 뒤 lifecycle 후처리 호출.
    # naver_sync (status 세팅 → on_status_cancelled 순서) 와 통일.
    # 현재 on_status_cancelled 는 reservation.status 를 읽지 않아 무해하나,
    # 미래에 status 분기가 추가돼도 안전하도록 방어적 정렬.
    mef = dict(db_reservation.manually_edited_fields or {})
    mef["status"] = True
    db_reservation.manually_edited_fields = mef
    db_reservation.status = ReservationStatus.CANCELLED
    db_reservation.cancelled_at = datetime.now(KST).replace(tzinfo=None)

    on_status_cancelled(db, db_reservation, same_day=is_same_day)
```

**동작 동등성**: `on_status_cancelled` 는 `reservation.status` 미참조(architect 확인: `reservation_lifecycle.py:123-191` 은 RA unassign + chip delete 만, status 안 읽음). 따라서 순서 교체는 **현재 동작 100% 동일**, 미래 회귀 방지용 방어.

### 1-2. `reservations.py::update_reservation` restore 블록 (L337) — 주석만 추가

mutator(L335)가 status=CONFIRMED 적용 시 `guarded` 규칙으로 `mef["status"]=timestamp` 를 자동 stamp → restore 블록(L342)이 즉시 `del` 로 되돌림. **이 순서(apply_changes → restore)가 뒤집히면 핀이 안 풀려 또 고아 핀 생성.** 의도 명시 주석 추가 (코드 로직 변경 없음).

---

## 2. #2 — naver_sync 가드 self-heal + 1회 DB 정리

### 2-1. `naver_sync.py::_update_reservation` 가드 (L755-767)

**Before**:
```python
_status_pinned = "status" in _mef
if _status_pinned:
    if _prev_status != ReservationStatus.CANCELLED:
        # invariant 위반 — 핀 있는데 status≠CANCELLED. 경보만.
        diag("naver_sync.status_pin_invariant_violation", level="critical",
             reservation_id=existing.id, prev_status=str(_prev_status), naver_status=naver_status)
elif naver_status == "confirmed":
    existing.status = ReservationStatus.CONFIRMED
elif naver_status == "cancelled":
    ...
```

**After**:
```python
_status_pinned = "status" in _mef
if _status_pinned:
    if _prev_status == ReservationStatus.CANCELLED:
        # 정상 soft-cancel — 네이버 응답 무관하게 CANCELLED 유지 (부활 차단).
        pass
    elif naver_status == "confirmed":
        # self-heal: 핀 있는데 status=CONFIRMED 이고 네이버도 confirmed →
        # 양측 합의(둘 다 confirmed) → 핀은 stale. 제거해서 무한 invariant 경보 차단.
        _mef_healed = dict(_mef)
        del _mef_healed["status"]
        existing.manually_edited_fields = _mef_healed
        if existing.cancelled_at:   # paired-state: CONFIRMED ⇔ cancelled_at NULL
            existing.cancelled_at = None
        diag("naver_sync.status_pin_self_healed", level="critical",
             reservation_id=existing.id, naver_status=naver_status)
    else:
        # 핀 있고 status≠CANCELLED 인데 네이버도 confirmed 아님 (cancelled 등) —
        # 진짜 모순. 자동 보정은 위험하니 경보만 (auto-correct 보류).
        diag("naver_sync.status_pin_invariant_violation", level="critical",
             reservation_id=existing.id, prev_status=str(_prev_status), naver_status=naver_status)
elif naver_status == "confirmed":
    existing.status = ReservationStatus.CONFIRMED
elif naver_status == "cancelled":
    ...
```

**동작 동등성/변화**:
| 케이스 | Before | After |
|---|---|---|
| 핀 O + status=CANCELLED (정상 soft-cancel) | CANCELLED 유지 | **동일** (CANCELLED 유지) |
| 핀 O + status=CONFIRMED + naver=confirmed (고아) | 매 sync critical 경보, status 그대로 | **핀 제거 + cancelled_at 정리 + self_healed diag 1회** → 다음 sync 부턴 정상 |
| 핀 O + status=CONFIRMED + naver=cancelled (진짜 모순) | invariant_violation 경보 | **동일** (경보, 보정 안 함) |
| 핀 X | 기존 로직 | **동일** |

**self-heal 안전성**: confirmed 합의일 때만 핀 제거 → 핀 제거 후 status 는 이미 CONFIRMED 라 변화 없음(L779 `_prev_status != existing.status` 블록 미진입, 잘못된 on_status_cancelled 호출 없음). naver=cancelled 인 모순 케이스는 보정 안 함(데이터 안전 우선).

### 2-2. 1회 정리 스크립트

기존 고아 핀(현 DB res 5311, 5995 등 `"status" in mef AND status != CANCELLED`)을 즉시 제거. self-heal 이 다음 sync 에 자동 처리하지만, 배포~첫 sync 사이 critical 폭주 방지 위해 선제 정리.

```python
# scripts 1회용: 고아 핀 제거
rows = db.query(Reservation).all()  # bypass_tenant
for r in rows:
    mef = r.manually_edited_fields or {}
    if "status" in mef and r.status != ReservationStatus.CANCELLED:
        mef2 = dict(mef); del mef2["status"]
        r.manually_edited_fields = mef2
db.commit()
```

---

## 3. #3 — guarded 유지 + 문서화

코드 변경 **없음** (`FIELD_PERMISSIONS["status"]` = NAVER `guarded` 유지). 문서/주석만:

### 3-1. `reservation_mutator.py` L50-51 주석 갱신
- 현재 주석: "NAVER=guarded 는 안전망 (현재 caller 0건)" — NAVER 관점만 기술.
- 추가: MANUAL PATCH 취소 시 auto-mark(L170-173)로 `mef["status"]` 자동 stamp → **의도된 동작**(DELETE/PATCH 무관 운영자 취소는 네이버 부활 차단). is_manual_cancel=True 로 CancelledZone 노출.

### 3-2. `delete-soft-cancel-design.md` §9 Q4 갱신
- "PATCH 경로는 별도 단계로 미룸" → "해결됨: FIELD_PERMISSIONS guarded 로 PATCH 취소도 자동 핀. 의도된 통일 동작."

**동작 영향**: 이미 현 코드에서 발생 중인 동작이라 **신규 변화 0**. 문서-코드 갭만 해소.

---

## 4. 시나리오 매트릭스 (후속 변경 후)

| # | 진입 | 사전조건 | 액션 | 기대 |
|---|---|---|---|---|
| 1 | naver_sync | 정상 soft-cancel(핀+CANCELLED) | sync confirmed | CANCELLED 유지 ✅ (변화 없음) |
| 2 | naver_sync | 고아 핀(핀+CONFIRMED) | sync confirmed | 핀 제거 + self_healed diag → 정상화 ✅ |
| 3 | naver_sync | 핀+CONFIRMED + naver cancelled | sync | invariant_violation 경보(보정 X) ✅ |
| 4 | 운영자 | confirmed 예약 | PATCH status=cancelled | mutator 자동 핀 + CANCELLED + CancelledZone (의도) ✅ |
| 5 | 운영자 | #4 직후 | PATCH status=confirmed | restore 블록이 핀 해제 + cancelled_at None ✅ |
| 6 | 운영자 | naver 예약 | DELETE (우클릭) | 순서 정렬됨(status 先, lifecycle 後) — 결과 동일 ✅ |

---

## 5. 영향 파일 요약

| 파일 | 변경 | 종류 |
|---|---|---|
| `naver_sync.py:755-767` | self-heal 분기 추가 | 🔵 동작 변화(고아 핀 자동 정리) |
| `reservations.py:491-504` | status/cancelled_at/핀 → on_status_cancelled 앞으로 | 🟢 방어적(동작 동일) |
| `reservations.py:337` | restore 순서 의존성 주석 | 🟢 주석 |
| `reservation_mutator.py:50-51` | guarded 부수효과 의도 명시 주석 | 🟢 주석 |
| `delete-soft-cancel-design.md` §9 Q4 | 결정 반영 | 📄 문서 |
| 1회 스크립트 | 고아 핀 제거 | 🔵 데이터 정리 |

## 6. 롤백
- self-heal/순서/주석은 단순 git revert 안전.
- 1회 스크립트는 핀 제거(데이터)라 revert 불가하나, 고아 핀은 원래 stale 라 복구 불필요.
