# 단계 #7 사전조사 — `sms_tracking.py` 이주

> 부모 계획: [chip-store-migration-plan.md](./chip-store-migration-plan.md) §6 단계 #7
> 분류: 🔵 의도된 변화 — OQ-5 silent fix 발효 (failed 칩 영구 보호)
> 변경 규모: 5 호출처 교체 + `sms_tracking.py` 파일 삭제 (108 LOC 제거)
> 첫 caller 이주 PR — mutator-step 형식 본격 적용 시작점

---

## 1. 목적

기존 `sms_tracking.py` 의 3 함수를 PR3 의 `chip_store.record_sent` / `record_failed` 호출로 교체.
완전 이주 → `sms_tracking.py` 파일 자체 삭제.

부수 정리:
- `sms_type_label` 미사용 파라미터 (dead code) 제거
- diag 키 전환: `sms.sent_recorded` → `chip_store.record_sent`, `sms.failed_recorded` → `chip_store.record_failed`
- OQ-5 silent fix **발효** — failed 칩이 다음 reconcile 사이클에서 영구 보호 → 무한 재시도 종료

---

## 2. 변경 대상 코드

### 2-1. `app/services/sms_sender.py` — 3 호출처 (record_sms_failed 만)

#### 라인 88~93 — phone 형식 오류 시
**Before**:
```python
from app.services.sms_tracking import record_sms_failed
record_sms_failed(
    db, reservation.id, template_key,
    error=f"전화번호 형식 오류: {reservation.phone!r}",
    date=str(date) if date else "",
)
```
**After**:
```python
from app.services.chip_store import record_failed
record_failed(
    db,
    reservation_id=reservation.id,
    template_key=template_key,
    error=f"전화번호 형식 오류: {reservation.phone!r}",
    date=str(date) if date else "",
)
```
**변경**: positional → keyword-only. 행동 동등 (+ OQ-5 fix 발효).

#### 라인 133~138 — 템플릿 없음
**Before**:
```python
from app.services.sms_tracking import record_sms_failed
record_sms_failed(
    db, reservation.id, template_key,
    error=f"템플릿 없음: {template_key}",
    date=effective_date or "",
)
```
**After**:
```python
from app.services.chip_store import record_failed
record_failed(
    db,
    reservation_id=reservation.id,
    template_key=template_key,
    error=f"템플릿 없음: {template_key}",
    date=effective_date or "",
)
```

#### 라인 159~164 — 방 정보 누락
동일 패턴.

### 2-2. `app/scheduler/template_scheduler.py` — 2 호출처

#### 라인 16 (top-level import) + 라인 202~209 — 발송 성공
**Before**:
```python
from app.services.sms_tracking import record_sms_sent
# ...
record_sms_sent(
    self.db,
    reservation.id,
    template_key,
    schedule.template.category,   # ← sms_type_label (dead code, 미사용)
    assigned_by='schedule',
    date=target_date or '',
)
```
**After**:
```python
from app.services.chip_store import record_sent
# ...
record_sent(
    self.db,
    reservation_id=reservation.id,
    template_key=template_key,
    assigned_by='schedule',
    date=target_date or '',
    schedule_id=schedule.id,   # 🟢 신규 추가 — chip_store 가 sms_tracking 보다 정확
)
```
**변경**: `sms_type_label` (dead) 제거 + `schedule_id` 추가 (enrichment).

#### 라인 227~232 — 발송 실패
**Before**:
```python
from app.services.sms_tracking import record_sms_failed
record_sms_failed(
    self.db, reservation.id, template_key,
    error=error_msg, date=target_date or '',
)
```
**After**:
```python
from app.services.chip_store import record_failed
record_failed(
    self.db,
    reservation_id=reservation.id,
    template_key=template_key,
    error=error_msg,
    date=target_date or '',
    schedule_id=schedule.id,   # 🟢 신규
)
```

### 2-3. `app/services/sms_tracking.py` — 파일 삭제

전체 143 LOC 제거. 모든 함수 (`_resolve_reservation_tenant`, `record_sms_sent`, `record_sms_failed`) 가 chip_store 로 이주됨.

---

## 3. 동작 동등성 근거

### 3-1. 호출처 매핑 표 (5 위치)

| 호출처 | 기존 함수 | 신규 함수 | 시그니처 변경 | 동작 변화 |
|--------|-----------|----------|--------------|---------|
| sms_sender.py:88~93 | `record_sms_failed` | `chip_store.record_failed` | positional → keyword | ✅ + 🔵 OQ-5 fix |
| sms_sender.py:133~138 | 동일 | 동일 | 동일 | 동일 |
| sms_sender.py:159~164 | 동일 | 동일 | 동일 | 동일 |
| template_scheduler.py:202~209 | `record_sms_sent` | `chip_store.record_sent` | `sms_type_label` 제거 + `schedule_id` 추가 | ✅ |
| template_scheduler.py:227~232 | `record_sms_failed` | `chip_store.record_failed` | `schedule_id` 추가 | ✅ + 🔵 OQ-5 fix |

### 3-2. 시그니처별 동작 비교 — `record_sent`

| 인자 | sms_tracking (현재) | chip_store (신규) | 동등? |
|------|-------------------|-------------------|------|
| `db` | positional | positional | ✅ |
| `reservation_id` | positional | keyword | ✅ |
| `template_key` | positional | keyword | ✅ |
| `sms_type_label` | positional, 함수 내 **미사용** | (제거) | 🟢 dead code 정리 |
| `assigned_by` | keyword, default 'auto' | keyword, default 'auto' | ✅ |
| `date` | keyword, default '' | keyword, default '' | ✅ |
| `schedule_id` | (없음) | keyword, default None | 🟢 enrichment |
| `sent_at` | 내부에서 `datetime.now(timezone.utc)` | keyword (default None → `datetime.now(timezone.utc)`) | ✅ 기본 동작 동일 |

**내부 동작 비교**:
| 단계 | sms_tracking | chip_store | 동등? |
|------|--------------|-----------|------|
| ① diag emit | `sms.sent_recorded` verbose | `chip_store.record_sent` verbose | 🟡 키 변경 — 정답지 갱신 필요 |
| ② tenant 해석 | `_resolve_reservation_tenant` (별도 SessionLocal) | `_resolve_reservation_tenant` (db 일시 bypass 토글) | ✅ 결과 동등 (PR3 §3 검증) |
| ③ existing 조회 | (tid, res_id, template_key, date) | 동일 | ✅ |
| ④ existing 있을 때 | sent_at + send_status='sent' + send_error=None | 동일 | ✅ |
| ⑤ existing 없을 때 INSERT | (tid, res_id, template_key, assigned_by, sent_at, send_status='sent', date) | + `schedule_id` (optional) | 🟢 enrichment |
| ⑥ 반환값 | None | ReservationSmsAssignment | 🟢 (caller 가 무시) |

### 3-3. 시그니처별 동작 비교 — `record_failed`

| 인자 | sms_tracking | chip_store | 동등? |
|------|-------------|-----------|------|
| `db` | positional | positional | ✅ |
| `reservation_id` | positional | keyword | ✅ |
| `template_key` | positional | keyword | ✅ |
| `error` | keyword | keyword | ✅ |
| `date` | keyword default '' | keyword default '' | ✅ |
| `schedule_id` | (없음) | keyword default None | 🟢 enrichment |

**내부 동작 비교**:
| 단계 | sms_tracking | chip_store | 동등? |
|------|--------------|-----------|------|
| ① diag emit | `sms.failed_recorded` critical | `chip_store.record_failed` critical | 🟡 키 변경 |
| ② tenant 해석 | 동일 | 동일 | ✅ |
| ③ existing 조회 | 동일 | 동일 | ✅ |
| ④ existing 있을 때 send_status | 'failed' | 동일 | ✅ |
| ④ existing 있을 때 send_error | truncate(500) | 동일 | ✅ |
| ④ existing 있을 때 **assigned_by** | **불변 (그대로 유지)** | **'failed' 로 승격** | ⚠️ **silent fix (OQ-5)** |
| ⑤ existing 없을 때 INSERT **assigned_by** | **'auto'** | **'failed'** | ⚠️ **silent fix (OQ-5)** |

### 3-4. ⚠️ Silent Fix 정당화 — OQ-5

**이전 동작** (sms_tracking 시점):
1. 운영자 phone 오타 → 스케줄러가 발송 시도 → Aligo 응답 fail
2. `record_sms_failed` → 칩의 `send_status='failed'`, `send_error` 기록. **assigned_by 는 'auto' 그대로**
3. 다음 reconcile 사이클 (예: surcharge_batch) → 가드 = `sent_at NULL + manual/excluded 가드만` → 'auto' 칩 삭제 대상
4. 자동 재시도 → 같은 phone 오류 → 또 실패 → 사이클 무한 반복

**관찰된 사례**:
- 5/10 res=5099 phone='010655<2887' 4회 연속 실패 (state.json:614 "sms.failed_recorded 35ms 간격 2회 중복")
- 5/14 res=5284 동일 패턴 4건 (state.json:656)

**이후 동작** (chip_store 시점):
1. 동일하게 운영자 phone 오타
2. `chip_store.record_failed` → `assigned_by='failed'` 강제 마크
3. 다음 reconcile → 가드 = `PROTECTED_ASSIGNED_BY = (manual, excluded, failed)` 포함 → failed 칩 보존
4. 자동 재시도 발생 안 함 → 운영자 화면 ⚠️ 표시 → 운영자 phone 수정 후 명시적 재발송

**의도된 fix**. OQ-5 사용자 결정 (2026-05-15) 의 직접 발효.

### 3-5. diag 키 전환 영향 — 정답지 1건

검색 결과 (§7 사전조사 grep):
- `docs/diag-golden/actions/_draft/sms-blocked-invalid-phone.yaml` 에 `sms.failed_recorded` 참조

**조치**:
1. 본 PR 머지 후 정답지 갱신 — `sms.failed_recorded` → `chip_store.record_failed`
2. instance_count 카운트 비교 (기존 발화 vs 신규 발화 동등 빈도?)
3. state.json pending 등록: "`sms.sent_recorded`/`sms.failed_recorded` 키 전환 — 정답지 1건 갱신 + 신규 키 사용 검증"

### 3-6. cross-tenant 검증 영향

- 기존 diag 키 `sms_tracking.cross_tenant_reservation` → 신규 `chip_store.cross_tenant_reservation`
- 발화 빈도는 동일 (cross-tenant 사고 발생 시만)
- 검색 결과: 정답지에 없음 → 영향 0

---

## 4. 시나리오별 결과

| 시나리오 | Before | After | 판정 |
|---------|--------|-------|------|
| 정상 발송 성공 (스케줄러) | sent_at 기록 | 동일 + schedule_id 기록 | ✅ + 🟢 enrichment |
| 발송 실패 (Aligo timeout, 신규 칩) | INSERT assigned_by='auto' | INSERT assigned_by='failed' | ⚠️ silent fix |
| 발송 실패 (기존 'auto' 칩) | send_status='failed', assigned_by 'auto' 유지 | + assigned_by → 'failed' 승격 | ⚠️ silent fix |
| phone 형식 오류 (sms_sender 가드) | record_sms_failed(error="전화번호 형식 오류:...") | 동일 (assigned_by='failed') | ⚠️ silent fix |
| 발송 실패 후 다음날 reconcile | failed 칩 삭제 → 재시도 | failed 칩 보존 → 운영자 알람 | ⚠️ **무한 재시도 종료** |
| 이벤트 SMS 즉시 발송 (chip 없음) | INSERT assigned_by='auto', sent | 동일 (assigned_by 'auto' 유지, sent) | ✅ (OQ-4 정상 동작) |
| cross-tenant 시도 | diag sms_tracking.cross_tenant | diag chip_store.cross_tenant | 🟡 키 변경 |

---

## 5. 영향받지 않음을 확인할 코드 경로

- `sms_sender.py:1~87` (import + send_single_sms 함수 시작 부분) — 변경 0
- `sms_sender.py:94~132` (effective_date 계산) — 변경 0
- `sms_sender.py:139~158` (방 정보 검증 분기) — 변경 0
- `sms_sender.py:165~end` (실제 발송 + log_activity) — 변경 0
- `template_scheduler.py:1~15` (import 외 — 변경 0)
- `template_scheduler.py:17~201` (필터링 8단계 + send_single_sms 호출) — 변경 0
- `template_scheduler.py:210~226` (성공 후 self.db.commit + send_results 추가) — 변경 0
- `template_scheduler.py:233~end` (실패 후처리 + 후속 로직) — 변경 0
- 모든 다른 파일 — 변경 0

---

## 6. 검증 체크리스트

- [ ] **syntax**: 모든 변경 파일 py_compile 통과
- [ ] **외부 참조 검증**:
  - `grep -rn "from app.services.sms_tracking" app/` → 0 건
  - `grep -rn "record_sms_sent\|record_sms_failed" app/` → 0 건 (chip_store 이주 후)
- [ ] **import 검증**: `from app.services.chip_store import record_sent, record_failed` 5 곳 모두 성공
- [ ] **단위 테스트**: chip_store 42 케이스 PASS 유지
- [ ] **통합 테스트**: 기존 sms_sender / template_scheduler 통합 테스트 (있다면) PASS 유지
- [ ] **회귀 비교**:
  - 정상 발송 시나리오 → sent_at 기록 동일
  - 실패 시나리오 → send_status='failed', send_error 동일
  - silent fix → assigned_by='failed' 마크 확인 (의도)
- [ ] **diag-golden 정답지 갱신**:
  - `_draft/sms-blocked-invalid-phone.yaml` 에서 `sms.failed_recorded` → `chip_store.record_failed`
  - state.json 의 "sms.failed_recorded 중복" pending 종결 (silent fix 로 자동 해결)
- [ ] **state.json pending 신규**: diag 키 전환 + OQ-5 발효 확인 — 다음 검증 회차에서 확인

---

## 7. 본 단계 이후의 후속 의존성

- **#8 (PR5)**: `surcharge.py` 의 `_ensure_chip`/`_remove_chip`/`_delete_all_surcharge_chips` 이주
- **#9 (PR6)**: `party3_mms` + `room_upgrade_common` 이주
- **#10 (PR7)**: `chip_reconciler` 이주
- **#11 (PR8)**: `reservations_sms` (운영자 토글) 이주
- **#12 (PR9)**: `reservation_lifecycle` (cc1/cc2/delete) — OQ-2 force=True 발효
- **#13 (PR10)**: 잔여 4 파일
- **#14 (PR11)**: CI lint

---

## 8. 머지 후 다음 액션

1. `chip-store-step-08-surcharge-migration.md` 작성 (PR5)
2. diag-golden 정답지 1건 갱신 (`sms-blocked-invalid-phone.yaml`)
3. state.json pending 갱신:
   - "sms.failed_recorded 중복" → 종결 (OQ-5 fix 효과)
   - 신규 pending: "chip_store.record_sent/failed 키 전환 후 첫 발화 정답지 검증"

---

## 9. 회귀 위험 평가

| 위험 카테고리 | 평가 | 근거 |
|---|---|---|
| 정상 발송 회귀 | **없음** | record_sent 내부 동작 동등 (PR3 §3 검증) + schedule_id enrichment 만 추가 |
| 실패 기록 회귀 | **🔵 의도된 변화** | OQ-5 silent fix — assigned_by='failed' 승격. 사용자 결정 발효 |
| 자동 재시도 무한루프 | **🟢 해결** | failed 칩이 PROTECTED 가드로 보존 → 재시도 중단 |
| 데이터 무결성 | 없음 | INSERT 시 tenant_id=res_tid 명시 (PR3 검증) |
| 성능 영향 | 없음 | 호출 빈도 동일, 내부 query 1회 동등 |
| 보안 영향 | 없음 | cross-tenant 검증 패턴 보존 |
| diag-golden 회귀 | **🟡 정답지 1건 갱신 필요** | `sms.failed_recorded` → `chip_store.record_failed` |
| 운영자 UX 영향 | **🟢 개선** | failed 칩이 화면에 ⚠️ 로 영구 표시 → 명확한 운영자 액션 트리거 |

**판정**: 🔵 의도된 변화 (OQ-5 silent fix) + ⚪ 리팩토링 (이주 + dead code 정리). 회귀 위험 작음, 정답지 1건 갱신 필요.
