# 단계 #22 사전조사 — CI lint 스크립트

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §E
> 분류: ⚪ 회귀 차단 도구 (런타임 동작 변화 0)
> 변경 규모: `backend/scripts/check_lifecycle_lint.sh` 신규

---

## 1. 목적

본 마이그레이션 후 신규 caller 가 RA 직접 조작 / private 함수 직접 호출 등으로 회귀하지 않도록 grep 기반 정적 검사. 사용자가 pre-commit / GitHub Actions / 수동으로 연결.

## 2. 검사 규칙

| 규칙 | 차단 대상 | 화이트리스트 |
|---|---|---|
| RA 직접 조작 | `db.delete(...RoomAssignment...)`, `db.query(RoomAssignment).*\.delete`, `RoomAssignment(...)` 인스턴스 | `app/services/room_assignment.py` (서비스 본인), `app/db/models.py` (모델 정의) |
| `shift_daily_records(` 직접 호출 (non-_) | 모든 외부 | `app/services/room_assignment.py` (정의), `app/services/reservation_lifecycle.py` (없음 — _shift_daily_records 호출) |
| `reconcile_dates(` 직접 호출 (non-_) | 모든 외부 | 동일 |

## 3. 동작 동등성

- 런타임 영향 0 — 스크립트는 정적 분석만
- 본 마이그레이션 결과 코드에서 통과 검증

## 4. 검증 체크리스트

- [ ] 스크립트 자체 실행 가능 (chmod +x)
- [ ] 본 마이그레이션 최종 상태에서 통과 (ERR=0)
- [ ] 시험 fail 케이스 (임시로 RA 직접 조작 추가) — fail 반환 확인

## 5. 머지 후 다음 액션

본 단계 머지 = **E 블록 완료 = lifecycle 마이그레이션 22단계 모두 완료**.
