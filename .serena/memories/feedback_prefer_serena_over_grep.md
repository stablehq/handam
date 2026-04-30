# Feedback: Serena 도구를 grep/Bash 보다 우선 사용

코드 파일을 대상으로 한 **content 검색은 항상 `mcp__serena__search_for_pattern` 을 먼저** 사용할 것. `Bash grep`/`rg` 는 Serena 룰상 "discovery 한정 허용" 이지만, 사용자는 Serena 도구를 명확히 선호함.

## Why
- 사용자가 직접 "왜 세레나 안 썼어?" 라고 지적한 사례 발생 (DB 파일 자동 재생성 여부 조사 중 grep 두 번 사용).
- 프로젝트 가이드 (root CLAUDE.md / Serena 매뉴얼) 의 spirit 은 "코드 파일에는 Serena 우선" 이며, 단순히 "허용된다" 가 아님.
- Serena 의 도구는 토큰 효율적이고 심볼릭 컨텍스트를 제공.

## How to apply
- 코드 파일(`*.py`, `*.ts`, `*.tsx` 등) 안의 문자열·패턴 검색 → `mcp__serena__search_for_pattern` (필요 시 `relative_path` 로 좁히기).
- 파일 구조 파악 → `get_symbols_overview`.
- 특정 심볼 본문 → `find_symbol(include_body=true)`.
- 참조/호출자 → `find_referencing_symbols`.
- Bash grep/rg 는 다음 경우에만 사용:
  - 비코드 파일(`.env`, `.md`, `.json`, `.yml`, lockfile 등)
  - Serena 가 파싱 못 하는 파일/생성물
  - 파일명 패턴(`find`/`ls`)
- 편집은 절대 Bash 없이: `replace_symbol_body` / `insert_*_symbol` / `replace_content` / 기본 Edit (비코드 파일).

## Self-check rule
모든 Read/Grep/Edit 호출 직전에 자문: "이게 코드 파일을 대상으로 하는가? Serena 매핑 표에 동일 작업이 있는가?" 있으면 Serena 로 전환.
