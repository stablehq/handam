# 운영자 수정 영구 보호 — 단계 분해 계획

> 작성일: 2026-05-15
> 상태: OQ 확정 — PR1 진입 가능
> 부모 마이그레이션: ded670f (Mutator + Lifecycle), [chip-store-migration-plan.md](./chip-store-migration-plan.md), [sync-sms-tags-consolidation-plan.md](./sync-sms-tags-consolidation-plan.md)
> 사상: 운영자가 수정한 모든 필드를 "방명록" (JSON dict) 으로 추적 → 다음 naver sync 가 덮어쓰기 차단

---

## 원칙 (이전 마이그레이션과 동일)

1. 기존 기능 변화 금지 — 의도된 변화 (운영자 수정 보호) 만 허용
2. 각 단계는 별도 PR + 사전조사 문서
3. 각 단계는 직전과 독립 — 롤백 가능
4. diag emit 으로 보호 작동 가시화 (`mutator.skipped(reason=pinned)`)
5. 운영 데이터 검증 후 다음 단계 진입

---

## 1. 현황 진단

### 문제
`naver_sync._update_reservation` (line 662~715) 가 가드 없이 직접 setattr — 운영자가 수정한 값이 다음 5분 sync 에서 silent 원복.

```python
existing.customer_name    = res_data.get("customer_name",    existing.customer_name)   # ❌ 가드 없음
existing.phone            = res_data.get("phone",            existing.phone)           # ❌
existing.visitor_name     = res_data.get("visitor_name",     existing.visitor_name)    # ❌
existing.visitor_phone    = res_data.get("visitor_phone",    existing.visitor_phone)   # ❌
existing.special_requests = res_data.get("custom_form_input", existing.special_requests) # ❌
```

`real/reservation.py:387~389` 검증: 네이버 응답에는 customer_name/phone 키가 **항상 존재** → fallback 안 타고 항상 덮어씀.

### 기존 보호 (ded670f, 일부만)
- `check_in_pinned` / `check_out_pinned` (날짜 보호) — Mutator pin
- `gender_manual` (성별/인원 보호) — caller 측 flag
- `is_split_managed` (booking_count/total_price 보호) — caller 측 flag

→ **이름/전화/특이사항 등 5+ 필드 미보호**.

---

## 2. 해결 패턴 — 방명록 (`manually_edited_fields` JSON dict)

### 컬럼 설계
```python
manually_edited_fields = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
```

### 저장 형태
```json
{
  "phone": "2026-05-15T10:30:00Z",
  "customer_name": "2026-05-15T11:00:00Z"
}
```

### 작동
1. **운영자 수정 (MANUAL source)**: Mutator 가 setattr 한 필드를 방명록에 timestamp 와 함께 추가
2. **네이버 sync (NAVER source)**: Mutator 가 필드별로 방명록 체크 → 있으면 skip + `mutator.skipped(reason=pinned)` critical diag

### 장점
- 새 보호 필드 추가 시 **DB 마이그레이션 불필요** (코드만 수정)
- 수정 시각 추적 가능 (운영 디버깅용)
- 컬럼 1개로 모든 필드 보호

---

## 3. Non-goals

- 운영자 명시적 "보호 해제" UI 기능 (별도 작업)
- 기존 `check_in_pinned` / `check_out_pinned` 의 즉시 통합 — **PR2 에서 점진 이주**
- `gender_manual` / `is_split_managed` flag 통합 — **PR3 이후 검토** (방명록 사상이 잘 작동 확인 후)

---

## 4. 확정된 OQ

| OQ | 결정 |
|----|------|
| 보호 메커니즘 | JSON dict (방명록) — 컬럼 1개 통합 |
| 진행 방식 | 점진 (옵션 C) — 우선 신규 5 필드 보호 후 검증, 운영 데이터 OK 면 다음 단계 |
| 보호 해제 | 영구 (한번 수정하면 보호 유지) — 운영자가 다시 변경하면 새 값 + 보호 유지 |
| 신규 보호 필드 (PR1) | customer_name, phone, visitor_name, visitor_phone, special_requests |
| 기존 pin 컬럼 통합 | PR2~PR3 에서 (방명록 작동 확인 후) |
| 검증 방법 | diag `mutator.skipped(reason=pinned)` 발화 빈도 |

---

## 5. 단계 분해 (3~4 PR)

### PR1 — 인프라 + 신규 5 필드 보호 (의도된 변화)
- alembic: `manually_edited_fields` JSON 컬럼 추가
- `Reservation` 모델 컬럼 정의
- Mutator: 방명록 기반 가드 로직 (기존 `_PIN_ATTR_FOR` 와 병행 가능)
- `FIELD_PERMISSIONS`: 5 필드를 `NAVER=guarded` 로 변경
- naver_sync `_update_reservation`: 5 필드 setattr → Mutator 호출로 통합
- 단위 테스트 + diag 검증

### PR2 (검증 후) — 기존 dates 보호도 방명록으로 이주
- `check_in_pinned=True` row 들을 방명록 dict 로 데이터 마이그레이션
- Mutator 가 dict 기준으로 가드 (pin 컬럼 참조 제거)
- naver_sync 의 `manually_extended_until` / `check_out_pinned` 호환 로직 정리
- 단위 테스트

### PR3 (선택) — pin 컬럼 제거
- `check_in_pinned`, `check_out_pinned` 컬럼 삭제 (alembic down 가능)
- `_PIN_ATTR_FOR` 매핑 제거
- Mutator 완전 단일화

---

## 6. 검증 방법 (PR1 후 운영 데이터 검토)

| 신호 | 의미 |
|------|------|
| `mutator.skipped(reason=pinned, field=customer_name)` 발화 | 운영자가 customer_name 수정 후 naver 가 덮어쓰려다 차단됨 ✅ |
| 동일 critical diag 의 일일 발화 빈도 | 운영자 편집 패턴 자체 |
| `mutator.skipped(reason=pinned)` 0건 | 운영자가 해당 필드 수정 안 함 (정상) |
| diag 0건인데 운영 사고 발생 | 보호 작동 안 함 (조사 필요) |

운영 며칠 후 PR2 진입 결정.

---

## 7. 진행 체크리스트

- [x] OQ 결정 (방명록 / 옵션 C / 5필드 / 영구 보호)
- [ ] PR1 사전조사 doc
- [ ] PR1 alembic migration
- [ ] PR1 Mutator 일반화
- [ ] PR1 FIELD_PERMISSIONS 갱신
- [ ] PR1 naver_sync 이주
- [ ] PR1 단위 테스트
- [ ] PR1 commit + push
- [ ] 운영 며칠 검증
- [ ] PR2 (날짜 pin 이주)
- [ ] PR3 (pin 컬럼 제거, 선택)
