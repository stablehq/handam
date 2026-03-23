---
name: Dashboard LLM 카드 아카이브
description: 대시보드에서 제거한 LLM/자동응답 관련 카드 — 나중에 LLM 구현 시 복원
type: project
---

대시보드에서 LLM/자동응답 구현 전까지 제거할 카드 목록 (2026-03-20):

1. **"자동 응답률" 메트릭 카드** — 룰+LLM 자동 처리율 (autoRate)
2. **"응답 유형 분포" 파이차트** — 룰/LLM/수동 비율 (responseTypeData)
3. **"전체 메시지" 메트릭 카드** — 수신+발신 합계 (자동응답 SMS 데이터)
4. **"최근 SMS" 테이블** — 수신/발신 메시지 목록 (자동응답 시스템용)

**Why:** LLM 자동응답 미구현 상태에서 의미 없는 데이터 표시. 구현 후 복원.
**How to apply:** LLM 자동응답 구현 시 (RealLLMProvider + MessageRouter 연동) 이 카드들을 대시보드에 다시 추가.

관련 백엔드 데이터: `stats.auto_response`, `stats.totals.messages`, `stats.recent_messages`
