# P1 사전조사 — `split_group_id` 컬럼 추가 + 신규 split 시 그룹 키 기록

> 부모 계획: naver_split 근본 해결 (2026-06-07 전수조사 + 5안 비교 심사 — 수정판 안 A 채택)
> 분류: 🟢 무동작 additive — 어떤 기존 코드도 이 컬럼을 읽지 않음 (P2 경보/P3 전파가 소비자)
> 변경 규모: models.py 1블록 + database.py 1블록 + alembic 1파일 + naver_sync.py 3지점 + 단위테스트 3건
> 후속 단계: P2(backfill+경보+drift 감지) → P3(자동 취소 전파, 플래그) → P4(freeze OR-강화) → P5(선택)

---

## 1. 목적

네이버 다객실(booking_count>1) 예약을 fan-out 한 primary↔sibling 사이에
**영속 연결 키가 전무**해서 (booking_source='naver_split' + NULL ID convention 만),
네이버 취소가 primary 에만 반영되고 sibling 이 CONFIRMED 로 잔존하는 사고가
반복 발생 (2026-06-05 김태우 res=6034/6035, 운영 DB 잔존 4건 실측 — 그중
[tid=2] res=6296 은 미래 체크인).

P1 은 그 연결 키(`split_group_id`)를 심는 단계만 수행한다.
**이 단계에서는 어떤 동작도 바뀌지 않는다** — 키를 읽는 코드가 아직 없다.

## 2. 설계 결정 (5안 비교 심사 + red-team 검증 반영)

- 키 형식: `nsplit-{naver_booking_id}` — stay_group 의 `manual-` 접두 전례
  (consecutive_stay.py:410). String(64) (naver_booking_id String(50) + prefix 7자 여유).
- **sibling 의 external_id/naver_booking_id NULL 불변** — existing_map 매칭 오염
  방지 가드(naver_sync.py:197-200, cf2ab7f CRITICAL)가 NULL 에 의존. 연결은
  100% 신규 컬럼이 전담.
- **sibling 식별은 계속 booking_source='naver_split'** — split_group_id 는 '연결'
  전용. consecutive_stay.py:115 등 기존 가드를 신규 컬럼 기준으로 바꾸지 않는다
  (test_consecutive_stay_split_guard.py 무수정 통과가 합격 기준).
- 마이그레이션 이중 트랙: alembic(최신 관례) + database.py auto-migrate
  (stay_group_id 전례 :241-244). 둘 다 inspector/IF NOT EXISTS 가드라 멱등.

---

## 3. 변경 대상 코드 (라인 단위 Before/After)

### 3-1. `backend/app/db/models.py` (line 92 다음, 신규 블록)

**Before** (line 92-94):
```python
    highlight_color = Column(String(20), nullable=True)              # UI highlight color for reservation card

    manually_extended_until = Column(String(20), nullable=True)  # protects against naver_sync overwrite when user manually extends
```

**After**:
```python
    highlight_color = Column(String(20), nullable=True)              # UI highlight color for reservation card

    # Naver multi-room split (다객실 분할) linking — naver_sync._split_multi_room_reservations 참조
    # primary + sibling 이 같은 키 공유: "nsplit-{naver_booking_id}".
    # 주의: sibling 식별은 계속 booking_source='naver_split' — 이 컬럼은 '연결' 전용 (식별용 아님).
    #       sibling 의 external_id/naver_booking_id 는 NULL 불변 (existing_map 매칭 오염 방지).
    split_group_id = Column(String(64), nullable=True, index=True)

    manually_extended_until = Column(String(20), nullable=True)  # protects against naver_sync overwrite when user manually extends
```

### 3-2. `backend/app/db/database.py` (line 250 다음, reservations 블록 내)

**Before** (line 248-250):
```python
            if "highlight_color" not in cols:
                conn.execute(text("ALTER TABLE reservations ADD COLUMN highlight_color VARCHAR(20)"))
                print("AUTO-MIGRATE: Added highlight_color column to reservations table")
```

**After** (직후 추가):
```python
            # Naver multi-room split linking (split-group P1)
            if "split_group_id" not in cols:
                conn.execute(text("ALTER TABLE reservations ADD COLUMN split_group_id VARCHAR(64)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reservations_split_group_id ON reservations (split_group_id)"))
                print("AUTO-MIGRATE: Added split_group_id column to reservations table")
```

### 3-3. `backend/alembic/versions/022_add_split_group_id.py` (신규)

head=021 (`021_add_manually_edited_fields.py`) → revision '022'.
`op.add_column` + `op.create_index`, downgrade 는 역순 drop.

### 3-4. `backend/app/services/naver_sync.py` — 3지점

**(a) `_split_multi_room_reservations` primary in-place 블록 (line 550-555)**

**Before**:
```python
        # primary in-place 수정
        res_data["booking_count"] = 1
        res_data["total_price"] = primary_price
        res_data["people_count"] = primary_people
        res_data["_split_male"] = primary_male
        res_data["_split_female"] = primary_female
```

**After**:
```python
        # primary in-place 수정
        res_data["booking_count"] = 1
        res_data["total_price"] = primary_price
        res_data["people_count"] = primary_people
        res_data["_split_male"] = primary_male
        res_data["_split_female"] = primary_female
        # split-group P1: primary↔sibling 영속 연결 키. sibling 은 dict(res_data)
        # 복사(아래)로 자동 상속. ext_id 부재 시 None (키 없는 split — 기존 동작 동일).
        res_data["_split_group_id"] = f"nsplit-{ext_id}" if ext_id else None
```

> 위치 근거: sibling 생성(`sibling = dict(res_data)`, line 559)이 primary 블록
> **이후**이므로 여기서 세팅하면 sibling 에 자동 상속. sibling override 8개 키
> (external_id/naver_booking_id/booking_count/total_price/people_count/
> _split_male/_split_female/_booking_source_override)에 `_split_group_id` 는
> 미포함 → 상속값 유지.

**(b) `naver_sync.split_multi_room` diag (line 570-576)** — `split_group_id` 필드 추가.

**(c) `_create_reservation` (line 611-640)** — `booking_source=` 라인(622) 다음에:
```python
        split_group_id=res_data.get("_split_group_id"),
```
비분할/수동/도미토리 예약은 `_split_group_id` 키 자체가 없어 `.get()` → None — 컬럼 기본값과 동일.

### 3-5. `backend/tests/unit/test_split_multi_room.py` — 3건 추가

1. `test_split_assigns_shared_group_key`: bc=2 → primary/sibling 모두 `"nsplit-12345"`.
2. `test_no_group_key_when_no_split`: bc=1 / 도미토리 / 미매핑 / 재동기화 → `_split_group_id` 키 부재.
3. `test_group_key_none_when_no_ext_id`: external_id/naver_booking_id 모두 None + bc=2 → split 은 되되 키는 None (graceful).

---

## 4. 동작 동등성 분석

| 경로 | P1 전 | P1 후 | 동등성 |
|---|---|---|---|
| 신규 split 예약 생성 | split_group_id 개념 없음 | 컬럼에 `nsplit-{id}` 기록 | **기록만** — 읽는 코드 0건 (grep 검증 항목) |
| 비분할/수동/도미토리 예약 생성 | — | split_group_id=NULL | 동일 (기본값) |
| 재동기화 `_update_reservation` | — | **무변경** (split_group_id 미접촉) | 동일 |
| existing_map 매칭 | sibling NULL ID 로 배제 | **무변경** | 동일 |
| 연박 자동감지 / 칩 / 배정 / SMS / 프론트 | booking_source 기준 | **무변경** | 동일 |
| API 응답 (`_to_response`) | — | **미노출** (P1 범위 밖) | 동일 — test_reservations_router_split.py 무수정 통과 |
| diag split_multi_room | 3필드 | +split_group_id 1필드 | diag-golden 에 split 이벤트 미등재 확인됨 → 필드 추가 무해 (P2 에서 정답지 등재 예정) |

**합격 기준**: 기존 테스트 전체(특히 test_split_multi_room.py 8건,
test_consecutive_stay_split_guard.py, test_reservations_router_split.py) **무수정** 통과.

## 5. 시나리오 비교

| 시나리오 | P1 전 | P1 후 |
|---|---|---|
| 신규 2객실 예약 sync | primary+sibling, 연결 단서 0 | 양쪽에 `nsplit-1255180281` — P2 경보가 이 키로 그룹 조회 가능해짐 |
| ext_id 없는 비정상 raw (이론상) | split 진행, 연결 없음 | split 진행, 키 None — **동작 변화 없이** 기존과 동일하게 고아 |
| 운영 PG 에 alembic 누락 배포 | — | startup auto-migrate 가 컬럼 생성 (이중 트랙) → 'column does not exist' 장애 차단 |
| 데모 SQLite `rm sms.db` 재시드 | — | create_all 이 컬럼 포함 생성 |
| 기존 데이터 (split 52건+) | — | split_group_id=NULL 유지 — **P2 backfill 범위** (P1 은 신규만) |

## 6. 리스크 및 롤백

- 리스크: 컬럼을 읽는 코드가 없으므로 기능 리스크 0. 유일 리스크는 마이그레이션
  자체(ALTER TABLE) — 양쪽 다 멱등 가드(inspector / IF NOT EXISTS), nullable 컬럼이라 락 비용 미미.
- 롤백: 코드 revert 만으로 충분. 컬럼/인덱스 잔존은 무해 (아무도 안 읽음).
  완전 제거 시 `alembic downgrade -1`.

## 7. 검증 계획

1. `pytest tests/unit/test_split_multi_room.py` — 기존 8 + 신규 3 = 11 green
2. `pytest tests/` 전체 — 무수정 통과
3. `grep -rn "split_group_id" backend/app/` — 쓰기 4지점(models/database/naver_sync×2)
   외 **읽기 0건** 확인 (무동작 additive 증명)
