# Impact Analysis — `/clean` 연박 판정에 stay_group(경로 B) 포함

작성일: 2026-05-30 (KST) · 상태: 사전조사(수정 전) · DB 검증: Supabase 운영(tenant 2)

## 0. 한 줄 요약

`/clean`(청소 스킵 = 연박 객실) 은 "어제·오늘 **같은 reservation_id**" 만 연박으로 보아
**경로 A(단일 예약 다박)만** 잡고 **경로 B(stay_group 분할 연박)를 놓침** → A307(박가람) 누락.
수정 범위는 **`api/cleancrew.py` 단일 함수 1개**로 한정되나, "OR 한 줄 추가"가 아니라
**EXISTS 기반 쿼리 소규모 재작성**이 정답(도미토리 인원 합계 fan-out 안전성 + status/NULL 가드 동반).

## 1. 연박의 정의 — 시스템에는 정확히 2경로 (전수조사 결과)

| | 경로 A: 단일 예약 다박 | 경로 B: stay_group 분할 |
|---|---|---|
| 저장 | 예약 1건 check_in~check_out ≥ 2박 | 1박 예약 N개를 `stay_group_id` 로 연결 |
| `stay_group_id` | NULL | 있음(UUID / `manual-UUID`) |
| 날짜별 배정 `reservation_id` | 매일 동일 | 날마다 다름 |
| 판정 함수 | `compute_is_long_stay`: `(co-ci).days > 1` | `compute_is_long_stay`: `stay_group_id` 존재 |

- **`manually_extended_until` 은 제3경로가 아님**: extend_stay 시 항상 `check_out_date` 와 동반 갱신(클램프로 초과 불가) → 경로 A로 흡수. 배정/연박판정/칩 어디서도 독립 입력 아님. (근거: `reservations_stay.py:224-226`, `reservations.py:413-424`, `naver_sync.py:688-717`)
- `is_long_stay` 플래그가 두 경로를 통합 표현(`consecutive_stay.py:28-45`).

## 2. 정상 동작 기준선 — 객실배정 (N/M) 칩

`frontend/.../GuestRow.tsx:104-122`, `MobileGuestRow.tsx:74-96` = 두 경로 모두 처리:
- 경로 B: 백엔드가 내려준 `stay_group_total_nights` / `stay_group_night_offset` 사용 (`reservations_shared.py:220-248`)
- 경로 A: `check_out - check_in` 날짜차이로 총 박수 계산

→ **칩은 연박 정의의 정답 기준선.** `/clean` 을 여기에 맞추는 것이 목표.

## 3. 결함 위치 — `api/cleancrew.py:64-83`

```python
.join(ra_today, ra_today.room_id == Room.id)
.join(ra_yest, and_(
    ra_yest.reservation_id == ra_today.reservation_id,   # ← 경로 A만
    ra_yest.room_id == ra_today.room_id,
))
.join(Reservation, Reservation.id == ra_today.reservation_id)
.filter(ra_today.date == today, ra_yest.date == yesterday)
```

- 경로 A(B207 백재준, B301 여크루): 어제·오늘 같은 res_id → **정상 표시** ✓
- 경로 B(A307 박가람: 어제 res=6033, 오늘 res=5884): res_id 다름 → **누락** ✗
- status 필터 없음(취소 예약 잔존 배정이 있으면 표시될 수 있는 잠재 결함, 현재 데이터엔 0건).

## 4. DB 검증 (tenant 2, 오늘=2026-05-30 / 어제=2026-05-29)

| 검증 | 결과 | 의미 |
|---|---|---|
| 현재 로직 표시 | `B207, B301` | 경로 A만 |
| `OR stay_group` 적용 | `A307, B207, B301` | A307 복구, 정확 |
| stay_group 도미토리 존재 | 18 배정행 | fan-out 위험원 존재 |
| OR self-join fan-out (오늘) | 전부 1 | 중복집계 없음 |
| **OR self-join fan-out (전체기간)** | **0건** | self+group 동시매칭 미발생(멤버 날짜 비겹침) |
| 그룹 내 인접일 방변경 | 1건(과거) | `room_id` 동일 조건이 올바르게 제외 |
| 취소 예약 잔존 배정(오늘/어제) | 0건(전부 CONFIRMED) | status 부재 영향 현재 없음 |

## 5. 수정안 (제안) — Before/After

대상: `list_today_stayover_rooms()` 단 1개 함수. self-join → **EXISTS 상관 서브쿼리**로 재작성하여
ra_today 1행당 1행 보장(fan-out 원천 차단) + 경로 A/B + status/NULL 가드 동시 충족.

```python
# After (개념)
ra_yest = aliased(RoomAssignment); res_yest = aliased(Reservation)
yest_continuation = (
    db.query(ra_yest.id)
      .join(res_yest, res_yest.id == ra_yest.reservation_id)
      .filter(
          ra_yest.date == yesterday,
          ra_yest.room_id == ra_today.room_id,
          res_yest.status != ReservationStatus.CANCELLED,
          or_(
              ra_yest.reservation_id == ra_today.reservation_id,                    # 경로 A
              and_(Reservation.stay_group_id.isnot(None),                           # 경로 B
                   res_yest.stay_group_id == Reservation.stay_group_id),
          ),
      ).exists()
)
rows = (db.query(Room.room_number, Room.is_dormitory, Room.max_capacity,
                 func.coalesce(func.sum(guest_count), 0).label("stayover_count"))
          .join(ra_today, ra_today.room_id == Room.id)
          .join(Reservation, Reservation.id == ra_today.reservation_id)
          .filter(ra_today.date == today,
                  Reservation.status != ReservationStatus.CANCELLED,
                  yest_continuation)
          .group_by(Room.id, Room.room_number, Room.is_dormitory, Room.max_capacity)
          .all())
```

추가 import: `or_`, `exists`(또는 `.exists()`), `ReservationStatus`.

## 6. Impact / Blast Radius

| 영역 | 영향 |
|---|---|
| 변경 파일 | `backend/app/api/cleancrew.py` 1개 (함수 1개) |
| DB 모델 / 마이그레이션 | **없음** (스키마 무변경) |
| API 계약 (`CleanSkipRoom`) | **무변경** (행 개수만 증가) |
| 프론트(`ConsecutiveStays.tsx`) | **무변경** (단순 리스트 렌더) |
| 다른 엔드포인트/중복 로직 | **없음** (이 self-join 패턴은 코드베이스 유일) |
| 멀티테넌트 | `get_tenant_scoped_db` 자동 필터 유지 |

## 7. 동작 동등성 / 회귀 시나리오

| 시나리오 | 현재 | 수정 후 | 비고 |
|---|---|---|---|
| 경로 A 연박(B207/B301) | 표시 | 표시 | 동등 유지 |
| 경로 B 연박(A307) | 누락 | 표시 | **버그 수정** |
| 방 회전(퇴실+신규, A207) | 미표시 | 미표시 | stay_group 상이/NULL → 영향 없음 |
| 그룹 내 방변경 | 미표시 | 미표시 | `room_id` 동일 조건 |
| 도미토리 인원합계 | 정상 | 정상(EXISTS로 fan-out 차단) | 강건성 ↑ |
| 취소 잔존 배정 | (표시 위험) | 미표시 | status 가드로 잠재결함 동시 제거 |

## 8. 결론 — "지금과 같은 수정범위면 충분한가?"

- **충분함(범위 측면)**: 변경은 `cleancrew.py` 단일 함수에 갇힘. 모델/마이그레이션/프론트/타 API 무영향.
- **단, "OR 한 줄"로는 불충분**: 도미토리 인원합계의 fan-out 안전성(현재 데이터 0건이나 구조적 취약) 때문에
  EXISTS 재작성 + 어제측 `Reservation` 추가 join + NULL 가드 + (권장)status 가드까지 한 묶음으로 가야 안전.
- 권장 검증: 수정 후 위 6개 시나리오를 동일 SQL 로 재실행해 `A307,B207,B301` 정확 산출 + 도미토리 합계 회귀 확인.
