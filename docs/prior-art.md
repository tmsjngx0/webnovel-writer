# 참고한 다른 하네스

볼 때마다 손으로 갱신한다. 자동 수집기는 만들지 않는다.

## zenstory-ai/oh-story-claudecode (2026-09-20 조사)

중국 웹소설용 skill 13개 패키지. MIT. 673 파일, 156k 줄. 이 저장소의 `legacy/`가 같은 계열의 이전 버전(webnovel-writer v6.2.1, lingfengQAQ, GPL v3)이다.

훔친 것

- **복선 대장**. ID, 심은 회차, 회수 예정, 중요도, 상태를 구조로 추적한다. 폐기도 기록을 남긴다. 수백 화를 버티는 실제 이유가 skill 개수가 아니라 이것이다.
- **작가 진실과 독자 기지 분리**. 둘을 섞는 것이 "인물이 아직 모르는 걸 아는" 사고의 주원인이라고 본인들이 명시한다. 이 저장소의 `집필제외` 마커는 같은 문제의 조잡한 버전이다.
- **context card**. 다음 회차가 읽는 유일한 요약 파일. 고정 섹션 7개, 12KB 상한, 본문 프롬프트에는 안 들어간다.
- **파생 뷰 손편집 거부**. 상태에서 렌더한 파일을 손으로 고치면 `check`가 거부한다. 이 저장소의 `state/events.md` 규칙과 같은 사상인데 적용 범위가 더 넓다.
- **설계 없는 본문 차단**. `guard-outline-before-prose.sh`가 회차 설계 없는 초고를 막는다. 훅 8개 중 유일하게 실제로 막는 것이다.
- **관점별 적대적 심사**. agent 4개 병렬.
- **AI 티 린트**. 규칙명과 blocking/advisory 등급, `파일:줄:칸` 출력. 모델을 안 부른다. 검출기 점수가 아니라 읽는 경험이 목표라고 명시한다.

안 훔친 것

- 扫榜. 起点, 番茄, 晋江 전용이다. 한국 플랫폼으로 다시 만든다.
- 대시보드. 원고는 파일이고 에디터가 이미 있다.
- 표지 생성. 파이프라인이 다르다.
- `_tracking-state.json` 단일 JSON 권위. `events.md`가 이미 파싱 가능하고 사람이 읽을 수 있다.
- 어댑터 8종(Codex, Antigravity, OpenCode, ZCode, OpenClaw, Reasonix). 제품이라서 필요한 것이다.

없는 것

원고 hash에 승인을 묶는 장치가 없다. 규율이 전부 skill 지시문이라 모델이 안 지키면 그만이다. 이 저장소의 `wn.py`는 스크립트가 거부한다.

## danjdewhurst/story-skills (2026-09-20 조사)

`story` CLI가 결정론적 정합성 검사를, skill이 창작을 맡는 분업. 모델을 안 부르고 YAML frontmatter만 읽는다. "컴파일러가 타입 에러를 다루듯" 한다고 표현한다.

훔친 것

- 검사 목록 자체. 죽은 인물 재등장, 복선 회수 순서(설치가 회수보다 먼저), 질문 제기 전 해답, 장면 cast와 POV 일치, 회차 간 인물과 사물 상태 모순, 안 터진 체호프의 총.

안 훔친 것

- 파일당 YAML frontmatter 레이아웃. 이 저장소는 `events.md` 블록 하나로 같은 정보를 담는다. 파일을 인물별로 쪼개면 원고를 쓰다가 고칠 데가 늘어난다.

## MJbae/awesome-novel-studio (2026-09-20 조사)

한국어 웹소설용 Claude Code 플러그인. `design/`, `episode/`, `revision/`, `_workspace/` 레이아웃. `/propose`로 기획안 3개, `/design-big`이 자동 조사까지 한다. `continuity-bridge` agent가 직전 2회차의 타임라인, 복선, 인물 상태를 모은다.

훔친 것

- `/propose` 형태. 기획안 여러 개를 내고 차이를 드러내는 것. 이 설계의 `concept` 단계다.
- `design-big`의 자동 조사. 이 설계의 `scan`이 웹을 봐야 하는 근거.

안 훔친 것

- 직전 2회차만 보는 continuity-bridge. 2회차는 100화짜리에 부족하다. 복선은 20화 전에 심는다. 상태 전체에서 렌더한 context card 쪽이 맞다.
- 16축 polish. 축 개수가 아니라 검출 규칙이 결정론적이냐가 중요하다.

없는 것

hash 검증, 자동 테스트, CLI 검사가 문서상 없다. 규율이 `novel-config.md`의 guardrail 문장이다.

## 안 본 것

howells/fiction, forsonny/Claude-Code-Novel-Writer. 위 셋과 같은 범주로 보여 미뤘다.
