---
name: wn-chapter
description: 무협 장편의 한 회차를 설계→초고→검수→사람 수정→추출→사람 승인·반영 순서로 진행한다. Codex CLI는 harness/wn.py를 통해 호출한다.
argument-hint: "<회차 번호>"
---

# 회차 진행

인자: 회차 번호 N. 모든 명령은 저장소 루트에서 실행한다.

## 0. 상태 확인

```bash
python harness/wn.py status
```

- `[중단된 반영]`이 있으면 멈추고 사람에게 `! python harness/wn.py recover` 실행을 안내한다.
- `story/outline.md`에 `### N화` 계획이 없으면 멈추고, 계획을 사람과 먼저 쓴다(모델 제안은 초안으로 표시).

## 1. 회차 설계

```bash
python harness/wn.py run design N
```

`runs/<id>/output.md`를 요약해 보여주고 사람의 수정 의견을 받는다. "설정 추가 필요" 항목은 승인 전 쓰지 않는다. 설계를 고쳐야 하면 `output.md`를 사람 지시대로 고친다(`output.orig.md`에 원본이 남는다).

## 2. 초고

```bash
python harness/wn.py run draft N --from-run <design-run-id>
```

`drafts/chNNNN.md`가 이미 있으면 덮어쓰지 않는다. 그 경우 사람에게 어느 것을 쓸지 묻는다.

## 3. 검수

```bash
python harness/wn.py run review N
python harness/wn.py check N --review-run <review-run-id>
```

지적을 심각도별로 표로 보여준다. 각 지적에 인용 실존 여부를 붙이되, 실존이 정당성을 뜻하지 않음을 명시한다. 사람이 채택/보류/기각을 정한다. 결정과 이유를 `runs/<review-run-id>/decisions.md`에 적는다.

## 4. 수정

사람이 채택한 지적만 `drafts/chNNNN.md`에 반영한다. 사람이 직접 고칠 수도 있다. 큰 수정 뒤에는 3을 다시 할지 사람에게 묻는다.

## 5. 추출 (최종 원고 기준)

```bash
python harness/wn.py run extract N
python harness/wn.py check N --extract-run <extract-run-id>
```

기록안의 `## 기록`, `## 설정 추가 의심`, `## 관계 메모`를 보여준다.
- 설정 추가 의심 또는 관계 메모가 있으면 `python harness/wn.py file-review N --run <extract-run-id>`로 GitHub 이슈를 만든다. 사람이 이슈에서 체크박스로 판단한다. 채택하면 사람이 canon/`story/relations.md`에 반영, 아니면 원고 수정.
- 기록 항목의 수정은 `runs/<id>/output.md`를 직접 고친 뒤 check를 다시 돌린다.

## 6. 승인·반영 (사람이 실행)

Claude는 실행하지 않는다. 사람에게 다음을 안내한다.

```
! python harness/wn.py approve N --run <extract-run-id>
! python harness/wn.py commit N --run <extract-run-id>
```

원고가 승인 뒤 바뀌면 commit이 거부되므로 5부터 다시 한다. 반영 후 Git 커밋 여부를 사람에게 묻는다.
