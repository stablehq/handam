# PR1 사전조사 — 인프라 + 신규 5 필드 보호

> 부모 계획: [manual-edit-protection-plan.md](./manual-edit-protection-plan.md) §5 PR1
> 분류: 🔵 의도된 변화 — 운영자 수정 보호 활성화
> 변경 규모: alembic + 모델 + Mutator + naver_sync + 단위 테스트

---

## 1. 목적

운영자가 객실배정 UI 에서 정정한 `customer_name`, `phone`, `visitor_name`,
`visitor_phone`, `special_requests` 5 필드가 5분마다 naver_sync 에 의해 silent
원복되는 문제 해결. `manually_edited_fields` JSON dict (방명록) 가 운영자
수정을 추적, Mutator 가 NAVER source 의 덮어쓰기를 차단.

---

## 2. 변경 대상 코드

### 2-1. 신규 alembic migration (021)
`backend/alembic/versions/021_add_manually_edited_fields.py`:
```python
op.add_column('reservations', sa.Column('manually_edited_fields',
    sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
```
- 기존 row 는 `'{}'` 로 초기화 — 영향 0.
- Postgres JSONB / SQLite TEXT 자동 매핑.

### 2-2. `Reservation` 모델
```python
manually_edited_fields = Column(JSON, nullable=False, server_default='{}', default=dict)
```

### 2-3. `FIELD_PERMISSIONS` 갱신
5 필드의 NAVER 권한 `always` → `guarded`:
- `customer_name`, `phone`, `visitor_name`, `visitor_phone`, `special_requests`

기타 필드 변경 0 (date 는 이미 guarded, gender/status/booking_options 는 그대로 always).

### 2-4. `Mutator.apply_changes` 일반화
- **2 메커니즘 병행 가드** (PR1 점진):
  - 기존 pin 컬럼 (`check_in_pinned`, `check_out_pinned`) — date 만
  - 신규 방명록 (`manually_edited_fields`) — 모든 guarded 필드
- MANUAL 시 applied 필드 + timestamp 를 방명록에 추가
- pin_source 정보 (column / dict) diag 에 emit

### 2-5. `naver_sync._update_reservation`
5 필드 직접 setattr → `Mutator.apply_changes(NAVER)` 단일 호출:
```python
ReservationMutator.apply_changes(db, existing, ChangeSource.NAVER, {
    "customer_name":    res_data.get("customer_name", existing.customer_name),
    "phone":            res_data.get("phone", existing.phone),
    "visitor_name":     res_data.get("visitor_name", existing.visitor_name),
    "visitor_phone":    res_data.get("visitor_phone", existing.visitor_phone),
    "special_requests": res_data.get("custom_form_input", existing.special_requests),
})
```
기존 `special_requests` 의 line 723 중복 setattr 도 제거.

---

## 3. 동작 동등성 근거

### 3-1. 운영자 수정 적 없는 신규 예약
- `manually_edited_fields = {}` (default)
- naver sync → Mutator 평가: `field in edits` → False → setattr 통과
- ✅ 정상 갱신 (회귀 0)

### 3-2. 운영자가 phone 수정한 후 sync
- MANUAL 수정 → `edits["phone"] = "2026-05-15T..."` 자동 등록
- 다음 sync → NAVER + guarded + `"phone" in edits` → skip
- ✅ 보호 활성

### 3-3. 운영자가 수정 안 한 필드는 정상 갱신
- 5 필드 중 1개만 수정 → 나머지 4개는 `edits` 에 없음
- naver 갱신 통과
- ✅ 부분 보호

### 3-4. diag 발화
- `mutator.skipped(reason=pinned, pin_source=dict/column)` critical
- 운영 데이터에서 발화 빈도 = 운영자 편집 횟수

---

## 4. 시나리오별 결과 (단위 테스트 검증)

| 시나리오 | 결과 | 테스트 |
|---------|------|--------|
| MANUAL phone 수정 → 방명록 등록 | ✅ | test_phone_edit_logs_in_dict |
| 같은 값 setattr → 방명록 미등록 | ✅ | test_no_change_no_log |
| MANUAL 후 NAVER phone 차단 | ✅ | test_naver_blocked_when_phone_edited |
| NAVER 가 미수정 필드 갱신 | ✅ | test_naver_unblocked_for_non_edited_field |
| 기존 date pin 호환 | ✅ | test_date_uses_pin_column_only |
| SYSTEM source 방명록 미등록 | ✅ | test_system_source_no_log |
| NAVER source 방명록 미등록 | ✅ | test_naver_source_no_log |
| 같은 필드 재수정 timestamp 갱신 | ✅ | test_dict_persists_across_multiple_edits |

총 12 케이스 PASS.

---

## 5. 영향받지 않음을 확인할 코드 경로

- `reservations.py PUT update_reservation` — Mutator 호출 그대로 (line 336~337)
- `reservations_stay.py` extend/reduce — Mutator 호출 그대로
- `chip-store` 마이그레이션 결과 — 변경 0
- `sync-sms-tags` 마이그레이션 결과 — 변경 0
- 기존 `check_in/out_pinned` 컬럼 — PR2 까지 그대로 사용

---

## 6. 검증 체크리스트

- [x] alembic 021 작성 + py_compile
- [x] Reservation 모델 컬럼 추가
- [x] Mutator 일반화 (병행 가드)
- [x] FIELD_PERMISSIONS 5 필드 변경
- [x] naver_sync 직접 setattr → Mutator 호출 교체
- [x] 단위 테스트 12 PASS (mutator_manually_edited)
- [x] 회귀 0 — chip_store 46/46 + 신규 12 = 58 PASS

---

## 7. 운영 검증 (배포 후)

`diag-golden` 검증 회차에서 확인할 신호:
- `mutator.skipped(reason=pinned, pin_source=dict, field=*)` — 운영자 편집 보호 발화
- 발화 빈도 = 정상 운영자 편집 패턴
- 0건이면 운영자가 해당 필드 수정 안 함 (정상)
- 폭증 시 운영자 편집 패턴 분석 + 보호 효과 확인

---

## 8. 후속 PR

- **PR2**: `check_in_pinned` / `check_out_pinned` 데이터를 방명록으로 이주 (data migration)
- **PR3 (선택)**: pin 컬럼 2개 제거 — 완전 통합

PR2 진입 조건: 운영 며칠 검증 후 `mutator.skipped(pin_source=dict)` 발화가
예상 패턴과 일치하면 진입.

---

## 9. 회귀 위험 평가

| 위험 | 평가 |
|---|---|
| 신규 예약 영향 | 없음 (default `{}` → 가드 무력) |
| 기존 예약 영향 | 없음 (모든 row `'{}'` 로 초기화 — naver 가 자유롭게 갱신) |
| 운영자 수정 보호 | 🟢 활성 |
| 기존 date pin | 🟢 호환 유지 (2 메커니즘 병행) |
| 성능 | 미미 (dict 한 번 더 조회) |
| diag-golden 정답지 | mutator.skipped 신규 발화 — pending 등록 가능 |
