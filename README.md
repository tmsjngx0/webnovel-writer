# 마환 무협 — 집필 저장소

한국어 무협 장편 웹소설 「마환」(가제 미정)의 기획·원고·집필 harness 저장소다. Claude Code가 진행하고, Codex CLI(`codex exec`)가 설계·초고·검수·추출을 실행하며, 사람이 판단하고 확정한다.

> 이 저장소는 원래 중국 웹소설용 Claude Code 플러그인(webnovel-writer v6)이었다. 이전 코드는 `legacy/`에 그대로 옮겨 두었고 사용하지 않는다. 필요 없으면 사람이 직접 지운다.

## 폴더

| 경로 | 개념 | 누가 쓰는가 |
|---|---|---|
| `plots/` | 기획 원본 v3~v6 | 사람 |
| `story/story-contract.md` | 핵심 재미와 독자와의 약속 | 사람 |
| `story/canon.md` | 설정. `[가정]`은 샘플용 빈칸, `집필제외`는 검수 전용 | 사람(승인) |
| `story/outline.md` | Arc·회차 계획, 독자 기대 목록 | 사람 (모델 제안은 초안 표시) |
| `story/style.md` | 승인 문체 예시와 수정 이유 | 사람 |
| `story/relations.md` | 관계 자유 서술 | 사람 |
| `story/ideas.md` | 미확정 제안 | 누구나 (`[제안]`) |
| `drafts/` | 원고 후보 | Codex 초고 → 사람 수정 |
| `chapters/` | 확정 원고 | `wn.py commit` |
| `state/events.md` | 확정 원고에서 추출해 승인한 사건·상태 | `wn.py commit` |
| `state/ledger.jsonl` | 반영 거래 기록(begin/done/rolled_back) | `wn.py commit/recover` |
| `runs/<run_id>/` | 실행별 프롬프트·입력 hash·출력·로그·승인 | `wn.py` |
| `prompts/` | 단계별 지시 | 사람 |
| `schemas/review.schema.json` | 검수 출력 형식 | 사람 |
| `harness/wn.py` | orchestration script (표준 라이브러리만) | – |
| `AGENTS.md` / `CLAUDE.md` | Codex 규칙 / Claude Code 진행 규칙 | 사람 |
| `.claude/skills/wn-chapter/` | 한 회차 진행 절차 (`/wn-chapter N`) | – |

## 한 회차의 흐름

```
status → run design → run draft → run review + check → 사람의 채택/기각 → drafts 수정
      → run extract(최종 원고) + check → [사람] approve → [사람] commit → [사람] git commit
```

```bash
python harness/wn.py status
python harness/wn.py run design 6
python harness/wn.py run draft 6 --from-run <design-run>
python harness/wn.py run review 6
python harness/wn.py check 6 --review-run <review-run>
python harness/wn.py run extract 6
python harness/wn.py check 6 --extract-run <extract-run>
python harness/wn.py approve 6 --run <extract-run>      # 사람만
python harness/wn.py commit 6 --run <extract-run>       # 사람만
python harness/wn.py recover                             # 반영 중단 시
```

`--dry-run`을 붙이면 프롬프트와 명령만 만들고 Codex는 부르지 않는다. 수동 실행 뒤 `finish <run_id>`로 기록한다.

## 무엇이 무엇을 보장하는가

| 층 | 범위 |
|---|---|
| 코드가 보장 | run별 입력 파일 목록·sha256·프롬프트·원본 출력 보존 / 인용 문자열의 원고 내 실존 / 승인 시점과 반영 시점의 원고·기록안 hash 일치 / 같은 회차·같은 원고·같은 기록안의 중복 반영 차단 / 반영 중단 식별과 백업 복구 / 집필제외 표지 짝 불일치 시 실행 중단 |
| 부분 검사 | canon 표기 표에 등록한 변형만 탐지(한국어 형태 변화·신규 이름은 놓침) / 공백 포함 글자수 참고 범위 / 오래된 사건 기록의 이름 부분 일치 선택 / `--json` 이벤트 로그로 실제 파일 접근을 사후 확인(이벤트에 안 잡히는 접근은 모름) |
| 모델 판단 | 인물 지식·시점, 시간선·소유·부상, 마환 규칙 위반, 신규 설정, 반복 해결, 문체·관계 의견 |
| 인간 판단 | 지적의 타당성(인용이 실존해도 지적이 옳다는 뜻은 아님), 설정 승인, 원고와 기록안의 승인, 재미 |

보장하지 않는 것: Codex가 저장소의 다른 파일을 읽지 않는 것. `codex exec`의 기본 sandbox `read-only`는 쓰기를 막을 뿐 읽기를 막지 않는다(공식 문서, 2026-09-15 확인). 미래 정보 노출은 context 구성과 검수로 다루는 서사 품질 문제로 취급한다.

## Codex CLI 사용 방식 (공식 문서 확인분)

- `codex exec --json --sandbox read-only -C <run폴더> -o <run폴더>/output.md --ephemeral -` 에 프롬프트를 stdin으로 넘긴다. 검수는 `--output-schema`를 추가한다.
- `--ephemeral`로 세션 파일을 남기지 않는다. 한 run은 한 번의 독립 호출이며 `codex exec resume --last`를 쓰지 않는다(`--last`는 현재 작업 폴더의 가장 최근 세션을 고른다). 파이프라인 재개는 `wn.py status` 기준이다.
- `AGENTS.md`는 Git 루트에서 작업 폴더까지 합쳐 읽히며 기본 한도는 32 KiB다.
- 이 PC에는 codex가 설치되어 있지 않아 실제 호출은 검증하지 않았다. 설치 후 `--dry-run`으로 명령을 확인하고 한 번 실행해 볼 것.

## 테스트

```bash
python -m unittest discover -s harness
```

## 라이선스

`LICENSE`(GPL-3.0)는 이전 저장소에서 물려받은 것이다. 새 원고와 harness의 라이선스는 사람이 정한다.
