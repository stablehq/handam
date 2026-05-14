# 파이프라인 시각화

이 디렉터리는 SMS 예약 시스템의 핵심 비즈니스 흐름을 **함수 단위**로 시각화한 문서를 모아둔 곳입니다.

## 두 가지 시각화 방식

| 종류 | 위치 | 갱신 방식 | 용도 |
|------|------|-----------|------|
| **수기 Mermaid 다이어그램** | `0X-*.md` | 사람이 직접 수정 | 핵심 파이프라인의 정제된 흐름 |
| **자동 호출 그래프 (SVG)** | `_generated/*.svg` | `scripts/generate_callgraphs.sh` 재실행 | 전체 모듈 지도 (노이즈 포함) |

자동 생성 그래프는 SQLAlchemy/FastAPI 내부 호출까지 포함되어 읽기 어렵습니다. **핵심 흐름은 항상 수기 Mermaid를 우선 참고하세요.**

## 핵심 파이프라인 4종

1. [SMS Template Schedule](01-sms-template-schedule.md) — APScheduler 트리거로 예약 기반 SMS 자동 발송
2. [Room Assignment](02-room-assignment.md) — 수동/자동 객실 배정 + SMS 태그 동기화
3. [Multi-Tenant Filtering](03-multi-tenant.md) — ContextVar + SQLAlchemy 이벤트로 자동 테넌트 격리
4. [Naver Sync](04-naver-sync.md) — 네이버 스마트플레이스 예약 동기화 (5분 주기)

## 자동 호출 그래프 생성

```bash
# 사전 요건
pip install code2flow
brew install graphviz   # 또는 apt-get install graphviz

# 실행
bash scripts/generate_callgraphs.sh
```

결과물은 `docs/pipelines/_generated/` 하위에 저장됩니다 (gitignore 처리됨, 재생성 가능).

| 파일 | 범위 |
|------|------|
| `scheduler.svg` | `app/scheduler/` — APScheduler 잡 정의 + 템플릿 스케줄 실행기 |
| `services.svg`  | `app/services/` — SMS 발송, 객실 배정, 네이버 동기화 등 |
| `api.svg`       | `app/api/` — FastAPI 라우터 (19개) |
| `templates.svg` | `app/templates/` — SMS 템플릿 렌더링 / 변수 계산 |
| `all.svg`       | `app/` 전체 (매우 크고 노이즈 많음, 참고용) |

## Mermaid 렌더링

- **GitHub**: `.md` 파일을 열면 자동 렌더링
- **VS Code**: [Markdown Preview Mermaid Support](https://marketplace.visualstudio.com/items?itemName=bierner.markdown-mermaid) 확장 설치 후 미리보기

## 유지보수 안내

수기 Mermaid 다이어그램의 노드 라벨에는 `file.py:LINE` 형식으로 함수 위치가 적혀 있습니다. **코드 리팩터링 후 함수 위치/이름이 바뀌면 해당 다이어그램을 갱신해주세요.** Stale 다이어그램은 안 그린 것만 못합니다.
