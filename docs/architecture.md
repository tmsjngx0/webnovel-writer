# 아키텍처 v2 — 다작품 집필 하네스

한 저장소, 여러 작품. 하네스는 공개하지 않는다. 이 문서는 현재 구조(작품 한 편 전용)를 다작품 하네스로 다시 짠 설계다.

## 왜 지금인가

1화도 아직 `chapters/`에 없고 run은 4개다. 원고 자산이 사실상 없으므로 재구성 비용이 거의 0이다. `Project` 클래스는 이미 모든 경로를 `self.path()` 경유로 만들기 때문에 다작품화에 필요한 코드 변경은 루트 해석 한 군데다.

100화쯤에서 깨지는 것(복선 유실, 인물이 아직 모르는 걸 아는 것)은 그때 고치면 이전 회차를 전부 다시 읽어야 한다. 지금 자리를 잡아 둔다.

## 레이아웃

```
webnovel-writer/
  harness/
    wn.py              orchestration
    lint.py            한국어 AI 티 린터 (결정론적, 모델 없음)
    continuity.py      결정론적 정합성 검사
    config.json        전 작품 공통 기본값
  prompts/             단계별 지시 기본값
  schemas/
  library/             拆文 결과. 작품 공용 자산
    <작품명>/
      source/          남의 원고. gitignore
      분석.md
      모듈.md          재사용 가능한 플롯 단위
  research/            시장 조사 결과. 작품 공용
    2026-09-문피아-무협.md
  spikes/
    <날짜>-<슬러그>/README.md
  runs/<run_id>/       모든 실행 기록. 작품 구분은 meta.json의 work 필드
  docs/
    architecture.md    이 문서
    prior-art.md       참고한 다른 하네스와 훔친 것
    workflow-issues.md
  works/
    mahwan-muhyup/
      work.json        작품별 설정. harness/config.json을 덮어씀
      prompts/         있으면 기본 prompts/를 덮어씀
      plots/           기획 원본
      story/           contract, canon, outline, style, relations, ideas
      drafts/
      chapters/
      state/           events.md, context-card.md, ledger.jsonl
```

작품 추가는 `works/<slug>/work.json` 하나 만드는 것이다. 하네스는 `works/*/work.json`을 스캔해서 목록을 만든다. 등록 파일을 따로 두지 않는다. 드리프트할 것이 없다.

## 루트 두 개

지금 `Project.root` 하나가 전부를 가리킨다. 두 개로 나눈다.

| | 무엇 | 누가 공유하나 |
|---|---|---|
| `Project.home` | harness, prompts, schemas, library, research, runs | 전 작품 |
| `Project.work` | story, drafts, chapters, state | 한 작품 |

작품 선택 순서: `--work <slug>` 플래그, 없으면 cwd가 `works/<slug>/` 아래면 그 작품, 없으면 작품이 하나뿐일 때 그것, 아니면 에러.

설정은 `harness/config.json`을 `works/<slug>/work.json`이 덮어쓴다. 프롬프트는 `works/<slug>/prompts/<stage>.md`가 있으면 그것, 없으면 `prompts/<stage>.md`.

## 단계 두 층

현재 `STAGES = (design, draft, review, extract)`는 전부 회차 단위다. 작품 단위 단계를 위에 얹는다.

**작품 이전 / 작품 단위 (회차 번호 없음)**

| 단계 | 하는 일 | 산출 | 실행기 |
|---|---|---|---|
| `scan` | 문피아, 카카오페이지, 네이버시리즈, 리디 랭킹을 교차해 장르 수요와 위험을 뽑는다 | `research/<날짜>-<플랫폼>-<장르>.md` | claude (웹 필요) |
| `deconstruct` | 남의 작품을 해체해 재사용 모듈로 만든다 | `library/<작품>/분석.md`, `모듈.md` | codex |
| `concept` | 기획안 여러 개를 내고 차이를 드러낸다 | `works/<slug>/plots/` | claude |
| `bible` | contract와 canon 초안 | `works/<slug>/story/` 초안 | codex |

지금 claude.ai와 ChatGPT에서 하시는 일이 `scan`과 `concept`이다. 기록이 안 남는 것이 문제다. 하네스로 들어오면 입력 hash와 출력이 `runs/`에 남는다.

**회차 단위 (기존 유지)**

`design`, `draft`, `review`, `extract`.

**모델 없이 도는 검사**

`lint`, `continuity`, `check`(기존), `render`.

## 실행기를 단계별로 고른다

Codex는 read-only sandbox라 웹을 못 본다. `scan`과 `concept`은 웹이 필요하다. config에 단계별 실행기를 둔다.

```json
"runner": {
  "scan": "claude",
  "concept": "claude",
  "deconstruct": "codex",
  "design": "codex", "draft": "codex", "review": "codex", "extract": "codex"
}
```

`claude` 실행기는 `claude -p` 헤드리스다. 조사 결과는 사람이 승인하기 전까지 자료일 뿐이다. 기존 승인 규칙이 그대로 걸린다.

## 상태 모델: 복선과 지식

여기가 이번 설계의 핵심이다. oh-story가 수백 화를 버티는 이유는 skill 개수가 아니라 이 두 가지를 분리해서 추적하기 때문이다.

### 복선 대장

현재 `EVENT_TYPES`는 사건, 발언, 믿음, 공개, 상태, 마환이다. 심어 놓고 안 터진 것을 추적할 자리가 없다. `복선` 유형을 추가하고 필수 키를 넓힌다.

```
- id: F0007-01
  유형: 복선
  심은회차: 7
  회수예정: 22
  중요도: 높음
  상태: 미회수
  내용: 종가가 평범한 수습이 아니다
  인용: "그 여자가 칼을 잡는 손이 너무 곱다"
```

`상태`는 미회수, 회수됨, 폐기 셋이다. 폐기는 흔적을 남긴다. 조용히 사라지지 않는다.

### 작가 진실과 독자 기지

지금 `집필제외` 마커가 canon.md에서 미래 정보를 가리는 것이 이 구분의 조잡한 버전이다. 가려지는 대상이 문서 구간이지 사실이 아니라서, "인물 A는 알지만 독자는 모른다"를 표현할 수 없다.

`믿음` 유형이 인물 지식을, `공개` 유형이 독자 인지 시점을 맡는다. 둘 다 이미 있다. 규칙만 박으면 된다.

- 인물이 아는 것은 `믿음` 이벤트가 있을 때만이다.
- 독자가 아는 것은 `공개` 이벤트가 있을 때만이다.
- canon에 적혀 있다는 것은 작가가 정했다는 뜻일 뿐, 둘 중 어느 것도 아니다.

### context-card.md

다음 회차 프롬프트에 들어가는 유일한 요약 파일이다. `state/events.md`에서 **렌더**한다. 손으로 고칠 수 없고, `wn.py render`가 다시 그려서 byte 단위로 같지 않으면 거부한다. 상한 12KB.

고정 섹션은 여섯 개다. 현재 위치, 상시 제약, 살아 있는 복선, 다음 회차 약속, 인물 지식 상태, 정합성 위험.

지금은 `events_context()`가 매번 메모리에서 같은 일을 하고 파일로 안 남는다. 파일로 내리면 사람이 프롬프트에 뭐가 들어가는지 보고 검수할 수 있다.

## 결정론적 검사 둘

### lint — 한국어 AI 티

규칙은 이미 전부 정해져 있다. `~/.config/ai/AGENTS.md`의 한국어 산문 규칙과 `story/style.md`다. 코드로 옮긴다.

| 규칙 | 등급 |
|---|---|
| 번역투 (`~에 있어서`, `~를 통해` 남발) | blocking |
| 이중 피동 (`판단되어진다`) | blocking |
| 대구 반복 (`A가 아니라 B`가 한 회차에 3회 이상) | blocking |
| 줄표, 화살표, 쌍반점 | blocking |
| 상투어 밀도 (`문득`, `천천히`, `깊게 숨을`) | advisory |
| 기계적 나열 (불릿 3연속, 첫째/둘째) | blocking |

출력은 `파일:줄:칸 [등급] 규칙명 (해당 구간)`이다. 모델을 안 부른다. `wn-humanize` skill은 이 린트가 잡은 뒤 남는 판단 영역을 맡는다.

### continuity — 결정론적 정합성

`state/events.md`만 읽고 돈다.

- 사망 상태 이벤트 이후 회차에 그 인물이 장면에 있다
- 회수예정 회차를 지났는데 상태가 미회수다
- 회수가 심은 회차보다 앞선다
- 심은 지 N회차가 지나도록 미회수다 (경고)
- 공개 이벤트 없이 원고가 독자에게 그 사실을 전제한다 (인용 대조)

## 게이트 하나 추가

`draft`는 `--from-run <design run>` 없이 돌지 않는다. 설계 없는 초고를 막는다. 지금은 선택 인자라 그냥 돈다.

## 리뷰를 관점별로 쪼갠다

현재 `review`는 codex 한 번 호출이다. 관점 네 개로 나눠 병렬로 돌리고 합친다. 구조, 인물, 문체, 설정. 스키마는 지금 `schemas/review.schema.json`을 그대로 쓴다. 인용 실존 확인(`check`)은 합친 뒤에 한 번 돈다.

한 시선이 놓치는 것을 다른 시선이 잡는다. 같은 모델을 네 번 부르는 것으로도 효과가 난다.

## 다른 하네스를 계속 참고한다

`docs/prior-art.md` 한 파일에 조사한 레포, 훔친 것, 안 훔친 이유를 적는다. 자동 수집기는 만들지 않는다. 볼 때 손으로 갱신한다.

## 단계별 이행

| 단계 | 내용 | 막는 것 |
|---|---|---|
| 1 | 레이아웃 이동, `Project` 루트 분리, `--work` | 이후 작업이 전부 여기 얹힘 |
| 2 | `복선` 유형, `context-card.md` 렌더, `continuity` | 100화에서의 복선 유실 |
| 3 | `lint` | 문체 리뷰를 사람이 매번 손으로 하는 것 |
| 4 | `draft` 게이트, 관점별 review | 설계 없는 초고, 한쪽 눈 검수 |
| 5 | `scan`, `concept`, `deconstruct`와 claude 실행기 | 기획 단계가 기록 없이 채팅에서 증발하는 것 |

1단계를 먼저 하는 이유는 나머지가 전부 경로에 의존하기 때문이다. 5단계가 마지막인 이유는 지금 claude.ai에서 해도 당장 안 깨지기 때문이다.

## 안 하기로 한 것

- **git submodule**. 단일 레포로 간다. 하네스를 공개하지 않으므로 분리 이유가 없다.
- **대시보드**. oh-story에 있지만 원고는 파일이고 에디터가 이미 있다.
- **표지 생성**. 집필과 파이프라인이 다르다. 필요하면 그때 따로 만든다.
- **`_tracking-state.json` 같은 단일 JSON 권위**. `events.md`가 이미 파싱 가능한 블록 구조이고 사람이 읽을 수 있다. 뷰를 두 가지 방식으로 파생시켜야 할 일이 생기기 전까지는 JSON을 두지 않는다.
- **중국 플랫폼 扫榜**. 한국 무협에 안 맞는다. `scan`은 한국 플랫폼으로 다시 만든다.
