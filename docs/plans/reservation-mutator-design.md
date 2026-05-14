# ReservationMutator 설계안

> 작성일: 2026-05-14  
> 상태: 검토 대기  
> 관련 버그: check_in_date 네이버 싱크 덮어쓰기 (전 케이스 공통)

---

## 1. 배경 — 왜 이 설계가 필요한가

### 현재 문제의 근본 원인

예약 데이터를 변경하는 경로가 6개 있고, 각 경로가 DB를 **직접** 수정한다.

```
네이버 싱크     ──▶  Reservation 테이블 직접 수정
수동 예약 수정  ──▶  Reservation 테이블 직접 수정
연박 연장       ──▶  Reservation 테이블 직접 수정
드래그 이동     ──▶  Reservation 테이블 직접 수정
객실 배정       ──▶  RoomAssignment 테이블 직접 수정
수동 생성       ──▶  Reservation 테이블 직접 수정
```

"어떤 출처(source)가 어떤 필드를 바꿀 수 있는가"라는 규칙이 6개 파일에 각자 불완전하게 구현되어 있어서, 새 기능이 추가될 때마다 6군데를 모두 수정해야 하고 하나라도 빠지면 조용히 버그가 생긴다.

### 확인된 버그 케이스 (2026-05-14)

모두 같은 원인: `naver_sync.py:672` — `check_in_date` 무조건 덮어쓰기

| 케이스 | 증상 | 원인 |
|--------|------|------|
| 내일 예약자 → 오늘로 드래그 | 5분 뒤 원복 | check_in_date 보호 없음 |
| 드래그 + 수동 연박 | 5분 뒤 원복 | manually_extended_until이 check_out_date만 보호 |
| 수동 PUT으로 날짜 수정 | 5분 뒤 원복 | PUT이 보호 플래그 미설정 |
| 수정 + 드래그 + 연박 조합 | check_in_date만 원복, check_out_date는 유지 | 두 필드 보호 방식이 비대칭 |

---

## 2. 현재 구조 사전점검

### 2-1. 보호 메커니즘 비대칭 실태

| 필드 | 보호 수단 | 커버되는 경로 |
|------|---------|------------|
| `check_out_date` | `manually_extended_until` | 연박 연장만 ✅ / 수동 PUT ❌ / 드래그 ❌ |
| `check_in_date` | **(없음)** | 전체 무방비 ❌ |
| `male/female_count` | `gender_manual` | 수동 PUT만 ✅ |
| `party_size` | `is_split_managed` | 일반실+매핑 있을 때만 ✅ |
| SMS 칩 | `assigned_by=manual/excluded` | 발송 완료/수동 지정 ✅ |
| `stay_group` | `stay_group_excluded` | 수동 unlink 후만 ✅ |

→ 필드마다 보호 방식이 다르고 범위도 제각각. 새 필드가 생길 때마다 새 보호 패턴을 발명하는 구조.

### 2-2. 후처리 매트릭스 — 경로별 불일치

| 경로 | shift_daily | reconcile_dates | reconcile_all_chips | reconcile_chips_for_reservation |
|------|:-----------:|:---------------:|:-------------------:|:-------------------------------:|
| 네이버 싱크 | ✅ (조건부) | ✅ (조건부) | ❌ | ✅ (일부) |
| 수동 생성 | ❌ | ❌ | ✅ | ❌ |
| 수동 수정 PUT | ✅ (조건부) | ✅ (조건부) | ✅ | ❌ |
| 연박 연장 | ❌ | ❌ | ❌ | ⚠️ 구버전 |
| 연박 축소 | ❌ | ❌ | ❌ | ⚠️ 구버전 |
| 드래그 이동 | ❌ | ❌ | ❌ | ❌ |
| 객실 배정 | ❌ | ❌ | ✅ | ❌ |

⚠️ 구버전 = `reconcile_chips_for_reservation` (기본 칩만, surcharge/party3/room_upgrade 누락)

### 2-3. 중복 코드 인스턴스

| 패턴 | 위치 |
|------|------|
| stay_group unlink + peer sync_sms_tags | `naver_sync.py:841` / `reservations.py:364` / `reservations_stay.py:133` |
| shift_daily_records + reconcile_dates | `naver_sync.py:852` / `reservations.py:393` |
| invariant 검증 (성별/인원 변경 후) | `naver_sync.py:866` / `reservations.py:398` |
| dorm push-out cleanup (surcharge+room_upgrade) | `room_assignment.py:440` / `naver_sync.py:801` |

### 2-4. 현재 보호 플래그 전체 목록

#### `manually_extended_until`
- **SET**: `reservations_stay.py:223` (extend_stay)
- **CHECK**: `naver_sync.py:676-702` (_update_reservation)
- **CLEAR**: `naver_sync.py:702` (naver catch-up) / `naver_sync.py:742` (cancel) / `reservations.py:346` (cancel) / `reservations_stay.py:433` (reduce)

#### `gender_manual`
- **SET**: `reservations.py:310-311` (male/female 수동 변경 시 자동)
- **CHECK**: `naver_sync.py:720` (성별 인원 재계산 여부)

#### `is_split_managed`
- **계산**: `naver_sync.py:659` — `(not _is_dormitory) and _has_room_link`
- **영향**: party_size, booking_count, total_price 덮어쓰기 skip

#### `stay_group_excluded`
- **SET**: `consecutive_stay.py:284` (unlink_from_group, exclude_from_auto_link=True)
- **CHECK**: `consecutive_stay.py:102` (감지 루프에서 제외)

#### `assigned_by='manual'/'excluded'` (SMS 칩)
- **SET**: 직원이 직접 칩 on/off 시
- **CHECK**: `chip_reconciler.py:38,335` (stale 칩 삭제 시 skip)

---

## 3. 제안 구조 — ReservationMutator

### 3-1. 핵심 아이디어

```
현재:  6개 경로 → 각자 DB 직접 수정 (규칙 6군데)
제안:  6개 경로 → ReservationMutator → DB 수정 (규칙 1군데)
```

모든 경로가 `source` 파라미터와 변경할 `changes` dict를 Mutator에 넘기면, Mutator 내부에서:
1. 이 source가 이 필드를 바꿀 자격이 있는지 판단
2. 허용된 변경만 적용 + 필요한 필드에 pin 설정
3. 항상 동일한 후처리 파이프라인 실행

### 3-2. 전체 구조도

```
  [네이버 싱크]  [수동 생성]  [수동 수정]  [연박 연장]  [드래그]  [객실 배정]
       │              │             │             │           │          │
  source=NAVER   source=      source=       source=     source=   source=
                 MANUAL       MANUAL        MANUAL      MANUAL    MANUAL
       └──────────────┴─────────────┴─────────────┴───────────┴──────────┘
                                        │
                                        ▼
             ┌──────────────────────────────────────────────────────┐
             │                  ReservationMutator                  │
             │                                                      │
             │  1단계: 필드 권한 체크 (FIELD_PERMISSIONS 테이블)    │
             │    source=NAVER  → pinned 필드는 skip                │
             │    source=MANUAL → 모든 필드 허용                    │
             │                                                      │
             │  2단계: 변경 적용 + pin 설정                         │
             │    source=MANUAL이면 변경된 필드에 pin 추가          │
             │                                                      │
             │  3단계: 후처리 파이프라인 (항상 동일)                │
             │    ① 날짜 변경됐으면 → shift_daily_records           │
             │                      → reconcile_dates               │
             │    ② 항상           → reconcile_all_chips            │
             │    ③ 연박 관련이면  → detect_and_link                │
             └──────────────────────────────────────────────────────┘
                                        │
                       ┌────────────────┼────────────────┐
                       ▼                ▼                ▼
               ┌──────────────┐  ┌───────────┐  ┌──────────────┐
               │ Reservation  │  │RoomAssign │  │SmsAssignment │
               │ 테이블       │  │ment 테이블 │  │ 테이블       │
               └──────────────┘  └───────────┘  └──────────────┘
```

### 3-3. FIELD_PERMISSIONS 매트릭스

```python
# reservation_mutator.py 안에 단 하나의 테이블로 선언

class ChangeSource(str, Enum):
    NAVER   = "naver"    # 네이버 싱크 (자동)
    MANUAL  = "manual"   # 직원 직접 조작 (모든 수동 경로)
    SYSTEM  = "system"   # 내부 자동 처리 (배정, 후처리 등)

FIELD_PERMISSIONS = {
    #  필드명                   NAVER        MANUAL     SYSTEM
    "check_in_date":         ["guarded",   "always",  "always"],
    "check_out_date":        ["guarded",   "always",  "always"],
    "customer_name":         ["always",    "always",  "never" ],
    "phone":                 ["always",    "always",  "never" ],
    "visitor_name":          ["always",    "always",  "never" ],
    "party_size":            ["guarded",   "always",  "never" ],
    "male_count":            ["guarded",   "always",  "never" ],
    "female_count":          ["guarded",   "always",  "never" ],
    "gender":                ["always",    "always",  "never" ],
    "status":                ["always",    "always",  "never" ],
    "section":               ["never",     "always",  "always"],
    "naver_room_type":       ["always",    "never",   "never" ],
    "booking_options":       ["always",    "never",   "never" ],
    "special_requests":      ["always",    "always",  "never" ],
    "total_price":           ["guarded",   "always",  "never" ],
}

# guarded = 해당 필드가 pinned=True가 아닐 때만 덮어씀
# always  = 무조건 덮어씀
# never   = 이 source는 이 필드 변경 불가
```

### 3-4. Pin 메커니즘 — 현재 난립한 보호 플래그 통일

```
현재 플래그                          →  새 Pin 필드
───────────────────────────────────────────────────────────
manually_extended_until (check_out)  →  check_out_pinned (Boolean)
(없음)                               →  check_in_pinned  (Boolean)
gender_manual (male/female_count)    →  gender_manual 유지 (재활용)
is_split_managed (party_size 등)     →  party_size_pinned (Boolean) 또는 유지
assigned_by='manual' (SMS 칩)        →  유지 (이미 잘 동작)
stay_group_excluded                  →  유지 (이미 잘 동작)
```

**네이버 catch-up 조건** (단순화):
```python
# 현재: incoming_end < check_out_date AND incoming_end < manually_extended_until
# 제안: incoming_end가 현재 check_out_date를 초과하면 pin 자동 해제
if incoming_end > reservation.check_out_date:
    reservation.check_out_pinned = False
```

### 3-5. 후처리 파이프라인 통일

```python
# ReservationMutator.apply_changes() 내부 — 항상 이 순서로 실행

def _run_post_processing(db, reservation, old_dates, changes):
    # ① 날짜 변경 시
    if old_dates != (reservation.check_in_date, reservation.check_out_date):
        shift_daily_records(db, reservation, *old_dates)
        reconcile_dates(db, reservation)

    # ② 항상
    reconcile_all_chips(db, reservation.id)

    # ③ 연박 관련 변경 시
    if _is_stay_related(changes):
        detect_and_link_consecutive_stays(db, reservation.tenant_id)
```

모든 경로가 이 함수를 통과하므로, `extend_stay`의 구버전 `reconcile_chips_for_reservation` 호출 문제도 자동 해결.

---

## 4. 현재 vs 제안 비교

| 항목 | 현재 (As-Is) | 제안 (To-Be) |
|------|------------|------------|
| 규칙 위치 | 6개 파일에 분산 | `reservation_mutator.py` 1개 파일 |
| 보호 방식 | 필드마다 다른 플래그 4종 | `FIELD_PERMISSIONS` + `*_pinned` Boolean |
| 후처리 | 경로마다 다른 조합 (누락 있음) | 항상 동일한 파이프라인 |
| 새 필드 추가 | 6개 경로 전부 수정 필요 | 테이블에 1줄 추가 |
| 새 보호 추가 | 새 플래그 발명 → 또 다른 난립 | `*_pinned` Boolean 1개 추가 |
| 버그 발생 지점 | 경로 하나라도 빠지면 조용히 버그 | 관문 통과 시 항상 동일 처리 |
| 테스트 가능성 | 경로별 개별 테스트 필요 | Mutator 단위 테스트 1세트 |

---

## 5. 마이그레이션 단계

단계별로 독립 실행 가능, 각 단계 후 기존 integration test로 회귀 검증.

| 단계 | 작업 | 위험도 | 크기 |
|------|------|--------|------|
| **1** | `reservation_mutator.py` 신규 생성 — `FIELD_PERMISSIONS`, `apply_changes()`, `_run_post_processing()` 구현 | 낮음 | 중간 |
| **2** | DB 마이그레이션 — `check_in_pinned`, `check_out_pinned` 컬럼 추가 | 낮음 | 작음 |
| **3** | `naver_sync._update_reservation` → Mutator 호출로 교체, `manually_extended_until` 제거 | 중간 | 중간 |
| **4** | `reservations.py` PUT `update_reservation` → Mutator 호출 | 중간 | 중간 |
| **5** | `reservations_stay.py` extend/reduce → Mutator 호출, 구버전 chip reconcile 교체 | 낮음 | 작음 |
| **6** | `reservations_room.py` 드래그/배정 → Mutator 호출 | 낮음 | 작음 |
| **7** | 중복 코드 제거 (stay_group unlink, invariant 검증 등) | 낮음 | 작음 |

---

## 6. 미결 검토 항목

검토 전 확인이 필요한 것들:

- [ ] `is_split_managed`를 `party_size_pinned`으로 교체할지, 별도 로직으로 유지할지
  - 현재: `(not _is_dormitory) and _has_room_link` 동적 계산
  - 교체 시: 매핑 추가/삭제 시 pin 재설정 로직 필요
- [ ] `SYSTEM` source의 범위 — 자동 배정, reconcile 내부 처리 등이 어느 source로 분류되는가
- [ ] `check_in_pinned` 자동 해제 조건 — 네이버 catch-up 기준을 `incoming > current`로 단순화해도 되는가
  - 현재 `manually_extended_until` 로직은 `incoming >= manually_extended_until`
- [ ] 수동 생성 예약(`booking_source=manual`)은 네이버 싱크 대상에서 제외되는가
  - 현재: `naver_booking_id` 없으면 싱크 대상 아님 → Mutator에서도 동일 처리
- [ ] 기존 `manually_extended_until` 데이터 마이그레이션
  - 현재 값이 있는 레코드: `check_out_pinned = True`로 변환 필요

---

## 7. 관련 파일 위치

```
변경 대상:
  backend/app/services/naver_sync.py          — _update_reservation (L660-925)
  backend/app/api/reservations.py             — update_reservation (L261-454)
  backend/app/api/reservations_stay.py        — extend_stay (L156), reduce_extension (L316)
  backend/app/api/reservations_room.py        — assign_room (L44)
  backend/app/db/models.py                    — Reservation 모델

신규 생성:
  backend/app/services/reservation_mutator.py — 단일 관문

마이그레이션:
  backend/alembic/versions/XXX_add_pinned_fields.py

테스트:
  backend/tests/unit/test_reservation_mutator.py
  backend/tests/integration/ (기존 테스트로 회귀 검증)
```
