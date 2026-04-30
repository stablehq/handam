# Phase 0 산출물 #15: canary 배포 계획

> 각 Phase 점진 배포 전략 + 롤백 결정 기준

## 배포 환경 가정

- **운영**: Supabase (Vercel/Cloudflare 백엔드 추정)
- **staging**: 별도 Supabase 인스턴스 또는 동일 DB + 다른 백엔드
- **테넌트**: 2개 (HANDAM, STABLE)

## 점진 배포 전략

### 전제: 단일 백엔드 인스턴스 (현재 구조)
대규모 SaaS 와 달리 백엔드 인스턴스가 1개 → 코드 변경 = 즉시 100% 배포. **canary by feature flag** 가 핵심.

### Strategy: feature flag 기반 점진 활성

```python
# 환경변수
OPTION_C_PHASE=0  # 비활성 (모두 ContextVar)
OPTION_C_PHASE=1  # shim 활성 (session.info 우선, ContextVar fallback)
OPTION_C_PHASE=2  # API endpoint 만 신규 패턴
OPTION_C_PHASE=3  # API + 스케줄러 신규 패턴
OPTION_C_PHASE=4  # 모든 service 신규 패턴
OPTION_C_PHASE=5  # ContextVar 사용 0건 검증 모드
OPTION_C_PHASE=6  # ContextVar 정의 자체 제거
```

## Phase 별 배포 일정

### Phase 1 (shim 추가) — 운영 영향 0

**시점**: 평일 오후 (사용자 트래픽 보통)

**배포 절차**:
1. PR 머지 → 자동 배포 트리거
2. 배포 완료 확인 (헬스체크)
3. `OPTION_C_PHASE=0` 유지 (shim 비활성, 새 factory 만 추가)
4. 24시간 모니터링 — 회귀 0건 확인
5. `OPTION_C_PHASE=1` 변경 → shim 활성
6. 추가 24시간 모니터링

**모니터링 지표**:
- diag log 의 `tenant_context.mismatch` 발화 = 0
- API 응답 시간 baseline ±5%
- 5xx 에러율 baseline 유지
- 통합 테스트 100% 통과

**롤백 트리거**:
- mismatch 발화 1건 이상 → 즉시 `OPTION_C_PHASE=0` 으로 복구
- 응답 시간 +20% 회귀 → 동일

### Phase 2 (API layer) — 핵심 동작 변경

**시점**: 주말 또는 사용자 트래픽 적은 시간 (오전 5~7시)

**배포 절차**:
1. `get_tenant_scoped_db` 변경 PR 머지
2. `OPTION_C_PHASE=2` 환경변수 변경
3. 배포 + 헬스체크
4. 첫 1시간 close monitoring

**점진 옵션** (가능하다면):
- 일부 endpoint 만 새 dependency 사용 → A/B 비교
- 현재 백엔드 단일 인스턴스라 전체 동시 변경 불가피

**모니터링 지표**:
- API 5xx 에러율 < 0.5%
- 모든 endpoint 응답 스펙 baseline 일치
- 활동 로그 패턴 일관

**롤백 트리거**:
- 5xx 에러율 > 1%
- API 응답 스펙 차이 발견
- 사용자 보고 (잘못된 데이터 노출)

### Phase 3 (스케줄러) — 가장 위험

**시점**: 일요일 오전 (스케줄러 잡 부하 가장 적음)

**배포 절차**:
1. 사전 준비:
   - 스케줄러 잡 모두 발화 시간 매핑 (배포 직전 실행 잡 없는지 확인)
   - 배포 시 손실 가능 잡 식별 (interval 잡은 다음 트리거에 자동 catchup)
2. PR 머지 → 배포
3. `OPTION_C_PHASE=3` 변경
4. 다음 잡 발화 시점까지 대기 → 정상 발화 확인
5. 24시간 close monitoring

**점진 옵션**:
- 6 진입점 (`_for_each_tenant`, `execute_job`, sync 잡 4개) 중 1~2 개 먼저 변환 → 나머지 다음 배포에
- 단, feature flag 가 모든 6곳 동시 영향이라 atomic 변경 권장

**모니터링 지표**:
- 잡별 발화 빈도 baseline ±10%
- SMS 발송량 baseline ±10%
- cross-tenant 누수 검증 쿼리 0건
- 활동 로그 type 별 빈도 일관

**롤백 트리거**:
- 잡 발화 실패 (예상 시간에 미발화)
- 잘못된 tenant 로 SMS 발송 1건 이상 (즉시 알람)
- 잡 실행 후 RuntimeError > 1건/시간

### Phase 4 (service layer) — 시그니처 변경

**시점**: 평일 오후 (롤백 용이성)

**배포 절차**:
1. service 함수별로 atomic commit (각 함수 독립 PR)
2. 함수당 staging 검증 → 운영 배포
3. 호출자 영향 큰 함수 (log_activity 등) 는 별도 일정

**점진 옵션**:
- 함수별로 feature flag 또는 dual-implementation (구버전 + 신버전 병행)
- 위험 함수는 dual 로 운영하며 정합성 비교

**모니터링 지표**:
- 함수 호출 후 데이터 정합성 검증
- 활동 로그 누락/중복 0
- service 함수 호출 응답 시간 baseline

**롤백 트리거**:
- 데이터 정합성 깨짐
- 호출자 시그니처 불일치 에러

### Phase 5 (보강 + 더티 데이터 정리) — 데이터 변경

**시점**: 평일 새벽 2~4시 (사용자 트래픽 최저)

**배포 절차**:
1. **사전 백업**: cross-tenant chip 25 sent 행 → archive 테이블
2. 코드 변경 (4 patches + sent_at 정합성) 배포
3. 더티 데이터 정리 SQL 단계별 실행:
   - 미발송 누수 칩 29건 DELETE
   - sent 누수 칩 25건 archive 후 DELETE (또는 leaked_legacy 마킹만)
4. flush invariant log-only 핸들러 활성

**모니터링 지표**:
- DELETE 후 row count 일치
- archive 테이블 25행 보존
- flush invariant warning 발화 (0건 기대)

**롤백 트리거**:
- DELETE 후 row count 불일치 → archive 에서 복원
- flush invariant 가 false positive 다수 발화 → 핸들러 비활성

### Phase 6 (ContextVar 제거) — 최종 cleanup

**시점**: 평일 오후 (롤백 용이성)

**배포 절차**:
1. 사전 검증: `grep current_tenant_id\|bypass_tenant_filter` = 0건 (단, diag_logger 제외)
2. ContextVar 정의 + fallback 분기 제거 PR
3. 배포 → 24시간 monitoring
4. feature flag 제거

**모니터링 지표**:
- ImportError 0
- NameError 0
- 모든 기능 정상

**롤백 트리거**:
- ImportError 발생 → 즉시 revert

## 사용자 영향 최소화

### 트래픽 패턴 (추정)
- 운영자 작업 시간: 평일 오전 9시 ~ 오후 7시
- 게스트 체크인: 오후 5시 ~ 오후 11시
- 스케줄러 잡 부하: 03:00, 07:00, 09:50 (오늘 사고 시간)

### 배포 권장 시간
- **Phase 1, 2, 4, 6**: 평일 오후 2~4시 (운영자 활동 중, 즉시 피드백 + 빠른 롤백)
- **Phase 3 (스케줄러)**: 일요일 오전 6시 (잡 부하 최저)
- **Phase 5 (데이터 변경)**: 평일 새벽 2~4시

## 모니터링 대시보드

### 자동 알람 항목
1. 5xx 에러율 > 1%
2. diag mismatch critical 발화
3. cross-tenant 누수 검증 쿼리 1건 이상
4. 잡 발화 누락 (예상 시간에 ActivityLog 없음)
5. 응답 시간 baseline +50%

### 수동 모니터링
1. 운영자 화면 정상 동작
2. SMS 발송 양상 baseline 비교
3. 활동 로그 type 분포

## 점진 활성 (feature flag 단계 전환)

```bash
# Phase 1 → 0 롤백 (shim 비활성)
OPTION_C_PHASE=0

# Phase 1 진입
OPTION_C_PHASE=1

# Phase 2 진입 (이전 단계 안정 확인 후)
OPTION_C_PHASE=2
```

각 단계 사이 최소 24시간 안정 확인.

## 롤백 시간 SLA

| 트리거 | 발견 → 결정 → 롤백 완료 |
|--|--|
| 자동 알람 | 5분 이내 |
| 수동 발견 | 15분 이내 |
| 데이터 변경 롤백 | 30분 이내 (백업 복원 포함) |

## 통신 계획

- **사전 공지**: Phase 2/3/5 배포 전 운영자에게 점검 시간 알림
- **실시간 상태**: 배포 진행 중 Slack/이메일 업데이트
- **사후 보고**: 각 Phase 완료 후 baseline 비교 결과 공유

## 결론

**핵심**: feature flag 기반 점진 활성 + 단계별 24시간 monitoring + 5분 이내 롤백 SLA. canary 단일 인스턴스 환경 한계 안에서 최대 안전 마진.
