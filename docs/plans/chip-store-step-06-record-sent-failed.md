# 단계 #6 사전조사 — `record_sent` + `record_failed` (`sms_tracking` 패턴 일반화)

> 부모 계획: [chip-store-migration-plan.md](./chip-store-migration-plan.md) §6 단계 #6
> 분류: ⚪ 인프라 — caller 0 (호출처 없음). 본 PR 동작 변화 0.
> 변경 규모: `app/services/chip_store.py` 스켈레톤 2 함수 → 실구현 + 보조 헬퍼 추가
> 후속 영향: PR4 의 sms_tracking 이주 시 **silent 정책 fix 발효** (OQ-5: failed 칩 영구 보호)

---

## 1. 목적

발송 성공/실패 기록을 칩에 upsert 하는 패턴을 `sms_tracking.py` 에서 `chip_store` 로 일반화. PR4 (#7) 에서 sms_tracking 의 두 함수를 chip_store 위임 래퍼로 축소할 준비.

흡수할 패턴:
- `sms_tracking.record_sms_sent` (line 54~99) — 92 LOC
- `sms_tracking.record_sms_failed` (line 101~143) — 43 LOC
- `sms_tracking._resolve_reservation_tenant` (line 14~52) — 38 LOC cross-tenant 검증

---

## 2. 변경 대상 코드

### 2-1. `app/services/chip_store.py` — 신규 헬퍼 + 2 함수 실구현

#### 추가: `_resolve_reservation_tenant` (private 헬퍼)

`sms_tracking._resolve_reservation_tenant` 와 **동등 로직 복제**. cross-tenant 검증 포함.

```python
def _resolve_reservation_tenant(db: 'Session', reservation_id: int) -> int:
    """Reservation 의 실제 tenant_id + cross-tenant 검증.

    session.info['tenant_id'] 와 reservation 의 실제 tenant_id 다르면
    critical diag 발화. 옵션 C Phase 6 강화 (silent cross-tenant 가시화).

    Returns: tenant_id (없으면 RuntimeError).
    """
    from app.db.database import session_bypass

    bypass_db = session_bypass()
    try:
        tid = (
            bypass_db.query(Reservation.tenant_id)
            .filter(Reservation.id == reservation_id)
            .scalar()
        )
    finally:
        bypass_db.close()
    if tid is None:
        raise RuntimeError(f"reservation {reservation_id} not found for chip_store")

    session_tid = db.info.get('tenant_id')
    if session_tid is not None and session_tid != tid:
        diag(
            "chip_store.cross_tenant_reservation",
            level="critical",
            session_tid=session_tid,
            reservation_id=reservation_id,
            reservation_tid=tid,
        )
    return tid
```

**diag 키 차이**: `sms_tracking.cross_tenant_reservation` → `chip_store.cross_tenant_reservation`.
PR4 의 sms_tracking 이주 시 두 이벤트가 동일 의미로 발화 가능 (이주 중간 단계). PR4 완료 후 sms_tracking 측 키 제거 예정.

#### `record_sent`

**Before** (PR2 직후):

```python
def record_sent(db, *, reservation_id, template_key, date=None, sent_at=None, **extra):
    """발송 성공 기록 — 기존 칩 update or 신규 INSERT.
    OQ-4 결정: 칩 없을 시 신규 INSERT 정상 흐름...
    PR3 (#6) 에서 구현."""
    raise NotImplementedError("PR3 (#6) 에서 구현")
```

**After** (~40 lines):

```python
def record_sent(
    db: 'Session', *,
    reservation_id: int,
    template_key: str,
    date: str = "",
    assigned_by: str = "auto",
    sent_at: Optional[datetime] = None,
    schedule_id: Optional[int] = None,
    **extra,
) -> ReservationSmsAssignment:
    """발송 성공 기록 — 기존 칩 update or 신규 INSERT.

    OQ-4: 칩 없을 시 신규 INSERT 정상 (이벤트 SMS / race / 외부 발송).
    cross-tenant 검증 포함.
    """
    sent_at = sent_at or datetime.now(timezone.utc)
    res_tid = _resolve_reservation_tenant(db, reservation_id)

    existing = (
        db.query(ReservationSmsAssignment)
        .filter(
            ReservationSmsAssignment.tenant_id == res_tid,
            ReservationSmsAssignment.reservation_id == reservation_id,
            ReservationSmsAssignment.template_key == template_key,
            ReservationSmsAssignment.date == date,
        )
        .first()
    )

    diag(
        "chip_store.record_sent",
        level="verbose",
        res_id=reservation_id,
        template_key=template_key,
        date=date,
        assigned_by=assigned_by,
        new_record=(existing is None),
    )

    if existing:
        existing.sent_at = sent_at
        existing.send_status = 'sent'
        existing.send_error = None
        return existing

    chip = ReservationSmsAssignment(
        reservation_id=reservation_id,
        template_key=template_key,
        date=date,
        assigned_by=assigned_by,
        schedule_id=schedule_id,
        sent_at=sent_at,
        send_status='sent',
        tenant_id=res_tid,
        **extra,
    )
    db.add(chip)
    return chip
```

#### `record_failed` ⚠️ **정책 변경 포함**

**Before** (PR2 직후):

```python
def record_failed(db, *, reservation_id, template_key, error=None, **extra):
    """발송 실패 기록 — assigned_by='failed' 칩 생성/갱신.
    OQ-5: 영구 보호. PR3 (#6) 에서 구현."""
    raise NotImplementedError("PR3 (#6) 에서 구현")
```

**After** (~40 lines):

```python
def record_failed(
    db: 'Session', *,
    reservation_id: int,
    template_key: str,
    error: Optional[str] = None,
    date: str = "",
    schedule_id: Optional[int] = None,
    **extra,
) -> ReservationSmsAssignment:
    """발송 실패 기록.

    OQ-5: assigned_by='failed' 강제 (기존 칩이 'auto' 등이어도 'failed' 로 승격)
         → 다음 reconcile 의 PROTECTED 가드가 보호.

    ⚠️ sms_tracking.record_sms_failed 와의 silent 차이:
        - 기존: existing.assigned_by 그대로 (예: 'auto' 유지)
        - 신규: existing.assigned_by = 'failed' 로 승격
        → 다음 자동 reconcile 가 '실패 흔적' 보호 (OQ-5 의도된 fix)

    cross-tenant 검증 포함.
    """
    error_str = (error or 'unknown')[:500]
    res_tid = _resolve_reservation_tenant(db, reservation_id)

    existing = (
        db.query(ReservationSmsAssignment)
        .filter(
            ReservationSmsAssignment.tenant_id == res_tid,
            ReservationSmsAssignment.reservation_id == reservation_id,
            ReservationSmsAssignment.template_key == template_key,
            ReservationSmsAssignment.date == date,
        )
        .first()
    )

    diag(
        "chip_store.record_failed",
        level="critical",
        res_id=reservation_id,
        template_key=template_key,
        date=date,
        error=error_str[:100],
        new_record=(existing is None),
        prior_assigned_by=(existing.assigned_by if existing else None),
    )

    if existing:
        existing.send_status = 'failed'
        existing.send_error = error_str
        existing.assigned_by = 'failed'  # ⚠️ OQ-5 fix (sms_tracking 기존 동작과 차이)
        return existing

    chip = ReservationSmsAssignment(
        reservation_id=reservation_id,
        template_key=template_key,
        date=date,
        assigned_by='failed',  # OQ-5
        schedule_id=schedule_id,
        send_status='failed',
        send_error=error_str,
        tenant_id=res_tid,
        **extra,
    )
    db.add(chip)
    return chip
```

### 2-2. `backend/tests/integration/test_chip_store.py` — 신규 테스트 클래스 2개

기존 29 케이스 + 약 12 케이스 추가 (총 ~41).

---

## 3. 동작 동등성 근거

본 PR3 자체는 caller 0 — 어떤 기존 흐름에도 영향 0. **모든 silent 변화는 PR4 의 sms_tracking 이주 시점에 발효**.

### 3-1. `record_sent` — `sms_tracking.record_sms_sent` 와 1:1 매핑

| 동작 | `sms_tracking` (현재) | `chip_store` (신규) | 동등 |
|---|---|---|---|
| tenant_id 조회 | `_resolve_reservation_tenant` (bypass 세션 + cross-tenant 검증) | `_resolve_reservation_tenant` (동일 로직 복제) | ✅ |
| diag 이벤트명 | `sms.sent_recorded` (verbose) | `chip_store.record_sent` (verbose) | 🔵 키 변경 (PR4 시 활성화) |
| diag 추가 필드 | (none) | `new_record` (existing 유무) | 🟢 가시화 강화 |
| existing 있을 때 | sent_at + send_status='sent' + send_error=None | 동일 | ✅ |
| existing 없을 때 INSERT | (tid, res, tk, assigned_by, sent_at, send_status='sent', date) | 동일 + `schedule_id` 추가 (optional) | ✅ schedule_id 는 caller 가 제공 시만 |
| 반환값 | `None` | `ReservationSmsAssignment` 객체 | 🟢 사용 가능성 ↑ (caller 가 무시해도 무해) |

**이벤트명 변경 (`sms.sent_recorded` → `chip_store.record_sent`)**: PR4 이주 시점에 변경 발효. 정답지 영향 — `sms.sent_recorded` 정답지가 있으면 PR4 후 PASS 안 함. state.json pending 등록 예정.

### 3-2. `record_failed` — ⚠️ Silent 정책 fix (OQ-5)

| 동작 | `sms_tracking` (현재) | `chip_store` (신규) | 차이 |
|---|---|---|---|
| tenant_id 조회 | `_resolve_reservation_tenant` | 동일 | ✅ |
| diag 이벤트명 | `sms.failed_recorded` (critical) | `chip_store.record_failed` (critical) | 🔵 키 변경 (PR4 시) |
| diag 추가 필드 | (none) | `new_record`, `prior_assigned_by` | 🟢 가시화 강화 |
| existing 있을 때 send_status | 'failed' | 동일 | ✅ |
| existing 있을 때 send_error | (error[:500]) | 동일 | ✅ |
| **existing 있을 때 assigned_by** | **변경 안 함 (예: 'auto' 유지)** | **'failed' 로 승격** | ⚠️ **silent fix** |
| existing 없을 때 INSERT — assigned_by | 'auto' | **'failed'** | ⚠️ **silent fix** |
| existing 없을 때 INSERT — schedule_id | (없음) | optional 받음 | 🟢 enrichment |
| 반환값 | `None` | `ReservationSmsAssignment` | 🟢 사용 가능성 ↑ |

**⚠️ Silent fix 정당화** (OQ-5):

현재 코드:
- `record_sms_failed` 는 send_status='failed', send_error 만 갱신
- assigned_by 안 만짐 → 'auto' 그대로
- 다음 reconcile (예: surcharge_batch) 가 가드 (sent_at NULL + manual/excluded 만 보호) 적용 → **failed 칩이 sent_at NULL, assigned_by='auto' 이므로 삭제 대상**
- 실제 sms.failed_recorded 다음날 자동 재시도되어 같은 phone 오류로 재실패 (운영 데이터에서 관찰됨, 5/10 res=5099 케이스)

신규 코드:
- assigned_by='failed' 강제 → PROTECTED_ASSIGNED_BY 가드에 걸려 보존
- 다음 reconcile 가 건드리지 않음
- 운영자가 phone 수정 후 명시적으로 재발송 처리 필요 (별도 UI — Non-goal)

→ **silent fix 는 OQ-5 결정의 직접 발효**. PR4 머지 후 5/10 res=5099 같은 케이스에서 무한 재시도 사라짐.

### 3-3. 본 PR3 (caller 0) 의 동작 동등성

| 시점 | record_sent/failed 호출 | 영향 |
|---|---|---|
| PR3 머지 후 ~ PR4 머지 전 | 0 (caller 0) | 0 |
| PR4 머지 후 | sms_tracking 이 호출 | §3-1, §3-2 변화 발효 |

**본 PR3 의 동작 동등성**: 미호출 ⇒ 자동 동등.

---

## 4. 시나리오별 결과 (단위 테스트)

`record_sent`:

| 시나리오 | 결과 |
|---|---|
| 칩 없는 res 에 record_sent | 신규 INSERT (sent_at + send_status='sent') |
| 기존 'auto' 칩에 record_sent | sent_at 갱신 + send_status='sent' + send_error=None |
| 기존 'manual' 칩에 record_sent | sent_at 갱신 (assigned_by 'manual' 유지) |
| 기존 'failed' 칩에 record_sent (운영자 fix 후) | sent_at 갱신 + send_status='sent' + send_error=None (assigned_by 'failed' 유지) |
| custom sent_at 지정 | 그 값 그대로 |
| schedule_id 지정 신규 INSERT | schedule_id 함께 저장 |
| cross-tenant 호출 | critical diag 발화 + 정상 처리 |

`record_failed`:

| 시나리오 | 결과 |
|---|---|
| 칩 없는 res 에 record_failed | 신규 INSERT (assigned_by='failed', send_status='failed', send_error) ⭐ OQ-5 |
| 기존 'auto' 칩에 record_failed | assigned_by 'auto'→'failed' 승격 + send_status='failed' ⭐ OQ-5 silent fix |
| 기존 'manual' 칩에 record_failed | assigned_by 'manual'→'failed' 승격 ⭐ 운영자 칩 발송 실패도 'failed' 로 마크 |
| 기존 'failed' 칩에 재시도 실패 | 동일하게 (assigned_by 'failed' 유지, error 갱신) |
| error=None | 'unknown' fallback |
| error=long (>500) | 500자로 truncate |

---

## 5. 영향받지 않음을 확인할 코드 경로

- `app/services/sms_tracking.py` — 변경 0 (PR4 에서 이주)
- `app/services/sms_sender.py` — 변경 0
- `app/scheduler/template_scheduler.py` — 변경 0
- 모든 기타 caller — 변경 0
- diag-golden 정답지 — 본 PR 영향 0 (PR4 시점에 `sms.sent_recorded` / `sms.failed_recorded` → `chip_store.record_*` 키 전환)

---

## 6. 검증 체크리스트

- [ ] **syntax**: `python -m py_compile app/services/chip_store.py` 통과
- [ ] **import**: 6 함수 + 1 헬퍼 import 성공
- [ ] **단위 테스트**: PR1/PR2 29 + PR3 신규 케이스 모두 PASS
- [ ] **외부 참조**: `grep -rn "from app.services.chip_store import.*record_" app/` → 0건 (caller 0)
- [ ] **diag-golden 영향**: 0 (`chip_store.record_*` 신규, 아직 발화 0. PR4 시 pending 등록)
- [ ] **회귀 비교**: 기존 sms_tracking 테스트 영향 0

---

## 7. 본 단계 이후의 후속 의존성

- **#7 (PR4)**: `sms_tracking.py` 이주 — `record_sms_sent` / `record_sms_failed` → `chip_store.record_*` 래퍼화 또는 caller 직접 호출. 본 PR3 의 silent fix 가 이때 발효.
- **#7 후 state.json pending 등록**: `sms.sent_recorded` / `sms.failed_recorded` 정답지가 있으면 `chip_store.record_sent` / `chip_store.record_failed` 로 키 갱신 필요.

---

## 8. 머지 후 다음 액션

`chip-store-step-07-sms-tracking-migration.md` 작성 (PR4):
- sms_tracking 의 두 함수를 chip_store 호출로 교체
- silent fix 발효 시 운영 영향 검증 (5/10 res=5099 케이스 재현)
- diag 이벤트명 전환 + state.json pending

---

## 9. 회귀 위험 평가

| 위험 카테고리 | 본 PR3 | PR4 머지 후 |
|---|---|---|
| 기존 기능 회귀 | **없음** (caller 0) | 🟢 **의도된 fix** (OQ-5 발효) — 자동 재시도 무한루프 제거 |
| 데이터 무결성 | 없음 | 일부 'auto' → 'failed' 승격 (의도) |
| 성능 영향 | 없음 | bypass 세션 1회 추가 (per 호출, 무시 가능) |
| 보안 영향 | 없음 | cross-tenant 검증 패턴 유지 |
| diag-golden 회귀 | 없음 | `sms.sent_recorded`/`sms.failed_recorded` → `chip_store.record_*` 키 변경 (정답지 갱신 필요) |

**본 PR3 판정**: ⚪ 인프라 단계, 회귀 위험 0.
**PR4 머지 후**: 🔵 의도된 silent fix (OQ-5 발효) + diag 키 전환.
