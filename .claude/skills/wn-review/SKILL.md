---
name: wn-review
description: 리뷰 이슈를 반영해 한 회차를 고치고 PR까지 올린다. 한 세션에 한 회차만 처리한다.
argument-hint: "<회차 번호>"
---

# 이슈 반영 회차 작업

인자: 회차 번호 N. 자세한 배경은 `docs/workflow-issues.md`.

## 0. 세션 시작 점검

이 저장소는 여러 세션이 공유하는 메인 체크아웃이다. 아직 전용 워크트리에서 시작한 게 아니면(`git worktree list`로 확인), 이 회차를 반영할 이슈 번호로 `wf start <이슈번호>`를 열어 그 워크트리에서 이어간다 — 공유 체크아웃에서 직접 브랜치를 만들지 않는다(전역 규칙, 2026-08-13 사고 참고). 이슈가 여러 개면 대표 이슈 하나로 연다.

```bash
python harness/wn.py status
python harness/wn.py issues --chapter N
```

- `[중단된 반영]`이 있으면 멈추고 사람에게 `! python harness/wn.py recover`를 안내한다.
- 이슈 목록에 `[warn] 원고에서 찾지 못한 인용`이 있으면 **사람에게만** 보고한다. 이슈 작성자에게 되돌리지 않는다. 회차 본문을 읽어 해당 대목을 찾아본다.
- 이슈가 없으면 사람에게 알리고 멈춘다.

## 1. 이슈 정리

각 이슈를 표로 보여준다: 번호, 인용, 지적, 인용 실존 여부, 내가 본 원인. 라벨이 없는 이슈는 사람에게 라벨을 물어본다(`정합성` / `설정` / `문장` / `재미`). 라벨 붙이기는 사람이 하거나, 사람이 지시하면 `gh issue edit <번호> --repo tmsjngx0/mahwan-muhyup --add-label <라벨>`로 실행한다.

## 2. Codex 검수(선택)

이슈만으로 충분하면 건너뛴다.

```bash
python harness/wn.py run review N
python harness/wn.py check N --review-run <id>
```

## 3. 사람의 결정

이슈 지적과 검수 지적을 함께 놓고 채택/보류/기각을 사람이 정한다. **인용이 존재한다는 것이 지적이 옳다는 뜻은 아니다.** 결정과 이유를 `runs/<review-run>/decisions.md`에 적는다. 검수를 건너뛰었으면 `runs/` 안에 `issues-chNNNN-decisions.md`로 적는다.

## 4. 수정

채택한 것만 `drafts/chNNNN.md`에 반영한다. canon 변경이 필요하면 `story/ideas.md`에 `[제안]`으로 적고 사람의 승인을 받는다. 승인 없이 `story/canon.md`를 고치지 않는다.

## 5. 사건 추출

```bash
python harness/wn.py run extract N
python harness/wn.py check N --extract-run <id>
```

설정 추가 의심 또는 관계 메모가 있으면 `python harness/wn.py file-review N --run <id>`로 GitHub 이슈를 만든다. 사람이 이슈에서 체크박스로 판단한다.

## 6. 승인·반영 (사람이 실행)

```
! python harness/wn.py approve N --run <extract-run-id>
! python harness/wn.py commit N --run <extract-run-id>
```

## 7. PR

0에서 `wf start`로 워크트리를 열었으면 브랜치는 이미 있다 — `git switch -c` 없이 그 워크트리에서 커밋한다. `wt step diff`로 브랜치를 딴 뒤 바뀐 것 전체를 한 번 확인하고 커밋한다.

```bash
wt step diff
git add drafts/chNNNN.md chapters state runs
git commit   # 본문 끝에 Closes #<이슈번호> 를 반영한 이슈마다 적는다
git push private HEAD
gh pr create --repo tmsjngx0/mahwan-muhyup --base main --head <워크트리 브랜치>
```

merge는 `wt merge`(자동 병합)가 아니라 GitHub PR로 사람이 한다 — 이 저장소는 원고 리뷰를 PR 화면에서 사람이 읽는 걸 전제로 한다. merge 뒤 `wf done --close`로 워크트리를 정리한다.

merge는 사람이 한다. merge되면 이슈가 닫힌다.

## 8. 세션 마무리

반영한 이슈 번호, 남은 이슈, 다음 회차를 사람에게 요약한다. receipt가 있으면 remaining을 갱신한다.
