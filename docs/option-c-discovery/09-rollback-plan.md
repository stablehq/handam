# Phase 0 산출물 #9: 단계별 롤백 계획

> 각 Phase 진입 후 위험 신호 감지 시 즉시 롤백 절차.

## 롤백 일반 원칙

1. **각 Phase 는 독립 commit** — Phase 단위 revert 로 1 commit 롤백 가능
2. **feature flag 우선 사용** — 코드 변경 없이 환경변수 toggle 로 즉시 비활성
3. **운영 데이터 변경 없음** — 옵션 C 마이그레이션은 코드만, 스키마 변경 0
4. **단계별 staging 검증** — staging 에서 24시간 안정 후 운영 배포

## Phase 별 롤백 트리거 (알람 임계)

### Phase 1 (호환 shim 도입)

**롤백 트리거**:
- 5xx 에러율 > 평소 baseline 의 1.5배 (5분 평균)
- diag log 의 `tenant_context.mismatch` critical 로그 발화 (예상 0건)
- pytest 통합 테스트 실패
- API endpoint 응답 시간 > baseline 의 2배 (성능 회귀)

**롤백 절차**:
1. 환경변수 `OPTION_C_PHASE=0` 으로 변경 → fallback 만 활성 (shim 효과 무력화)
2. 그래도 회귀 발생 시 commit revert
   ```bash
   git revert <phase1_commit_hash>
   git push
   ```
3. 자동 배포 트리거 → 운영 복원
4. 사고 분석 후 재시도

**예상 시간**: 환경변수 변경 < 1분, commit revert < 5분.

### Phase 2 (API layer 전환)

**롤백 트리거**:
- API endpoint 응답 200 → 5xx 비율 > 1%
- 테스트 시나리오 회귀 (특히 cross-tenant 격리)
- 사용자 보고 (잘못된 tenant 데이터 노출)

**롤백 절차**:
1. `get_tenant_scoped_db` 의 변경 부분만 revert (1 commit)
2. ContextVar set/reset 패턴 복원
3. 자동 배포

**위험**: Phase 2 부분 적용 (일부 endpoint 변경, 다른 endpoint 미변경) 시 일관성 이슈. 가능한 한 atomic deploy.

### Phase 3 (스케줄러 전환)

**롤백 트리거**:
- 스케줄러 잡 발화 실패 (cron 시간에 잡 실행 안 됨)
- 잘못된 tenant 로 SMS 발송 (이번 사고 재발)
- 잡 실행 후 RuntimeError 빈도 > 1건/시간

**롤백 절차**:
1. 잡별 변경 commit 단위로 revert
2. 6 진입점 (`_for_each_tenant`, `execute_job`, sync 잡 4개) 중 문제 잡만 revert
3. 자동 재시작 (APScheduler 재로드)

**예상 시간**: 잡당 < 10분.

### Phase 4 (service layer 전환)

**롤백 트리거**:
- 특정 함수 호출 후 데이터 정합성 깨짐
- 활동 로그 누락 또는 중복
- 호출자 시그니처 불일치 에러

**롤백 절차**:
1. 함수별 commit 단위 revert
2. 시그니처 변경된 함수의 모든 호출자 동시 복원

**위험**: service 함수 시그니처 변경이 호출자 영향 큼. 부분 롤백 어려움.

### Phase 5 (보강 + 더티 데이터 정리)

**롤백 트리거**:
- 더티 데이터 정리 SQL 실행 후 운영 화면 이상
- flush invariant log-only 가 false positive 다수 발화

**롤백 절차**:
1. 더티 데이터 정리는 백업 후 수행 (`reservation_sms_assignments_leaked_archive` 테이블)
2. 백업 → 원본 복원 SQL 으로 즉시 복구 가능
3. flush invariant 핸들러는 log-only 라 코드 변경만 revert (영향 없음)

### Phase 6 (ContextVar 제거)

**롤백 트리거**:
- ContextVar fallback 의존 코드 발견 → ImportError / NameError
- 마이그레이션 잔재 코드의 silent 누수

**롤백 절차**:
1. ContextVar 정의 + 핸들러의 fallback 분기 복원 (1 commit)
2. 자동 배포

**예상 위험**: Phase 6 까지 가려면 1~5 가 완벽 검증되어야 함. 롤백 가능성 매우 낮음.

## 데이터 변경 롤백

### 더티 데이터 정리 SQL 롤백

```sql
-- 백업 테이블에서 복원
INSERT INTO reservation_sms_assignments
SELECT id, reservation_id, template_key, assigned_at, sent_at, assigned_by, date,
       tenant_id, schedule_id, send_status, send_error
FROM reservation_sms_assignments_leaked_archive
WHERE archived_at >= '...';
```

### `record_sms_failed` sent_at 정합성 수정 롤백

코드 변경만, DB 영향 없음. revert 1 commit.

### 적용된 6 패치 + 4곳 누락분 보강 롤백

코드 변경만, DB 영향 없음. revert 가능.

## staging 검증 체크리스트

각 Phase 운영 배포 전 staging 에서:
- [ ] 모든 통합 테스트 통과
- [ ] 24시간 운영 시뮬레이션 (실제 트래픽 패턴 reproduction)
- [ ] diag log 의 mismatch 발화 0건
- [ ] 모니터링 대시보드 baseline 대비 정상
- [ ] cross-tenant 누수 시뮬레이션 → 차단 확인

## 운영 배포 체크리스트

- [ ] staging 검증 완료
- [ ] 모니터링 알람 임계 설정
- [ ] 롤백 절차 문서 readiness
- [ ] 사용자 알림 (대시보드 점검 시간)
- [ ] 배포 시간 (사용자 트래픽 적은 시간 권장)
- [ ] 24~72시간 close monitoring

## 롤백 후 재시도

각 Phase 롤백 후:
1. 사고 분석 (diag log, 에러 메시지, 사용자 영향)
2. 수정안 작성 + 테스트 보강
3. staging 재검증
4. 다음 시도 시점 결정

## 비상 contact

- 운영자 알림: SMS / Slack / email
- 데이터 손상 발견 시: 즉시 모든 잡 정지 (`scheduler.shutdown()`) + 백업 검증

## 결론

각 Phase 가 독립 commit 으로 분리되고 feature flag 로 즉시 비활성 가능 → **롤백 시간 5분 이내**.

가장 큰 위험은 Phase 4 (service 시그니처 변경) — 호출자 동시 복원 필요. 이 Phase 는 함수별 atomic commit 으로 분리해 부분 롤백 가능하게 설계.
