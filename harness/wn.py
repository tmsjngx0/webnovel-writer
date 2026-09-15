#!/usr/bin/env python3
"""무협 장편 집필 harness (MVP). 표준 라이브러리만 사용한다.

코드가 보장하는 것
- run마다 실제 입력 파일 목록과 sha256, 프롬프트, 원본 출력을 보존한다.
- 인용 문자열이 원고에 실제로 존재하는지 확인한다(공백 무시 부분 문자열 일치).
- 승인 시점의 원고·기록안 hash와 반영 시점의 hash가 같을 때만 반영한다.
- 같은 회차·같은 원고·같은 기록안의 중복 반영을 막는다.
- 반영 중단(begin만 있고 done이 없는 거래)을 식별하고 백업으로 되돌린다.

코드가 보장하지 않는 것
- 설정·시간선·인물 지식 모순의 탐지 (모델 검수 + 사람 판단)
- 문체와 재미 (사람 판단)
- Codex가 저장소의 다른 파일을 읽지 않는 것 (read-only sandbox는 쓰기만 막는다)
- 한국어 본문에서 고유명사·사건의 완전한 추출
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
STAGES = ("design", "draft", "review", "extract")
HIDE_START = "<!-- 집필제외:시작 -->"
HIDE_END = "<!-- 집필제외:끝 -->"
EVENT_TYPES = {"사건", "발언", "믿음", "공개", "상태", "마환"}
REQUIRED_KEYS = ("id", "유형", "장면", "내용", "인용")
BLOCK_RE = re.compile(
    r"<!-- BEGIN ch=(\d+) sha=([0-9a-f]+) run=(\S+) -->\n(.*?)<!-- END ch=\1 -->\n?", re.S
)
CH_HEAD_RE = re.compile(r"^###\s+(\d+)화(?:[\s:：]|$)")
EVENT_ID_RE = re.compile(r"E\d{4}-\d{2}")

DEFAULT_CONFIG = {
    "char_count_with_spaces": {"min": 4500, "max": 7000},
    "previous_chapter_max_chars": 8000,
    "events_max_chars": 30000,
    "recent_event_chapters": 5,
    "codex": {
        "binary": "codex",
        "sandbox": "read-only",
        "ephemeral": True,
        "model": None,
        "extra_args": [],
    },
}


class HarnessError(Exception):
    pass


# ---------------------------------------------------------------- 공용 함수

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def ch_name(ch: int) -> str:
    return f"ch{ch:04d}"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def strip_hidden(text: str) -> str:
    """집필 context에서 작가 전용 구간을 지운다. 표지가 짝이 맞지 않으면 누출 대신 실패한다."""
    if text.count(HIDE_START) != text.count(HIDE_END):
        raise HarnessError("집필제외 표지의 시작/끝 개수가 다르다. 미래 정보 누출을 막기 위해 중단한다.")
    return re.sub(re.escape(HIDE_START) + r".*?" + re.escape(HIDE_END), "", text, flags=re.S)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _strip_quote_marks(text: str) -> str:
    return text.strip().strip("\"'“”‘’「」『』").strip()


def quote_in(quote: str, text: str) -> bool:
    """인용이 원고에 있는지. 말줄임표(… 또는 ...)로 나뉜 조각은 순서대로 모두 있어야 한다."""
    pieces = [_normalize(p) for p in re.split(r"…|\.\.\.", _strip_quote_marks(quote))]
    pieces = [p for p in pieces if p]
    if not pieces:
        return False
    haystack = _normalize(text)
    pos = 0
    for piece in pieces:
        idx = haystack.find(piece, pos)
        if idx < 0:
            return False
        pos = idx + len(piece)
    return True


def load_config(root: Path) -> dict:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    path = root / "harness" / "config.json"
    if path.exists():
        user = json.loads(read_text(path))
        codex = {**config["codex"], **user.get("codex", {})}
        config.update(user)
        config["codex"] = codex
    return config


# ---------------------------------------------------------------- 프로젝트

class Project:
    def __init__(self, root: Path | str = DEFAULT_ROOT):
        self.root = Path(root).resolve()
        self.config = load_config(self.root)

    def path(self, rel: str) -> Path:
        return self.root.joinpath(*rel.split("/"))

    def draft_path(self, ch: int) -> Path:
        return self.path(f"drafts/{ch_name(ch)}.md")

    def chapter_path(self, ch: int) -> Path:
        return self.path(f"chapters/{ch_name(ch)}.md")

    @property
    def events_path(self) -> Path:
        return self.path("state/events.md")

    @property
    def ledger_path(self) -> Path:
        return self.path("state/ledger.jsonl")

    def run_dir(self, run_id: str) -> Path:
        return self.path(f"runs/{run_id}")

    def load_meta(self, run_id: str) -> dict:
        path = self.run_dir(run_id) / "meta.json"
        if not path.exists():
            raise HarnessError(f"run이 없다: {run_id}")
        return json.loads(read_text(path))

    def save_meta(self, meta: dict) -> None:
        _atomic_write(self.run_dir(meta["run_id"]) / "meta.json",
                      json.dumps(meta, ensure_ascii=False, indent=2) + "\n")

    def read_ledger(self) -> list[dict]:
        if not self.ledger_path.exists():
            return []
        return [json.loads(line) for line in read_text(self.ledger_path).splitlines() if line.strip()]

    def append_ledger(self, entry: dict) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())


# ---------------------------------------------------------------- 개요·설정 파싱

def outline_for(text: str, ch: int) -> tuple[str, str] | None:
    """(현재 Arc 머리말, 해당 회차 계획)을 돌려준다. 미래 회차 계획은 포함하지 않는다."""
    arc_lines: list[str] = []
    chapter_lines: list[str] | None = None
    in_arc_intro = False
    for line in text.splitlines():
        if line.startswith("# ") or line.startswith("## "):
            if chapter_lines is not None:
                break
            arc_lines = [line] if line.startswith("## ") else []
            in_arc_intro = line.startswith("## ")
            continue
        if line.startswith("### "):
            if chapter_lines is not None:
                break
            in_arc_intro = False
            m = CH_HEAD_RE.match(line)
            if m and int(m.group(1)) == ch:
                chapter_lines = [line]
            continue
        if chapter_lines is not None:
            chapter_lines.append(line)
        elif in_arc_intro:
            arc_lines.append(line)
    if chapter_lines is None:
        return None
    return "\n".join(arc_lines).strip(), "\n".join(chapter_lines).strip()


def cast_of(chapter_plan: str) -> list[str]:
    for line in chapter_plan.splitlines():
        m = re.match(r"^\s*-?\s*등장\s*[:：]\s*(.+)$", line)
        if m:
            names = re.split(r"[,、·]", m.group(1))
            return [re.sub(r"\(.*?\)", "", n).strip() for n in names if n.strip()]
    return []


def name_variants(canon_text: str) -> list[tuple[str, list[str]]]:
    """canon.md의 '## 표기' 표에서 (정식 표기, 금지 변형들)을 읽는다."""
    rows = []
    in_section = False
    for line in canon_text.splitlines():
        if line.startswith("## "):
            in_section = line[3:].strip() == "표기"
            continue
        if not in_section or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0] in ("정식", "") or set(cells[0]) <= set("-: "):
            continue
        variants = [v.strip() for v in cells[1].split(",") if v.strip() and v.strip() != "없음"]
        if variants:
            rows.append((cells[0], variants))
    return rows


# ---------------------------------------------------------------- 사건 기록

def parse_events(text: str) -> tuple[str, dict[int, str], list[str]]:
    """(머리말, 회차별 블록, 블록 밖에 있는 문제 텍스트)."""
    blocks: dict[int, str] = {}
    residue: list[str] = []
    matches = list(BLOCK_RE.finditer(text))
    if not matches:
        return text, blocks, residue
    preamble = text[: matches[0].start()]
    pos = matches[0].start()
    for m in matches:
        gap = text[pos: m.start()]
        if gap.strip():
            residue.append(gap.strip()[:80])
        ch = int(m.group(1))
        if ch in blocks:
            residue.append(f"{ch}화 블록 중복")
        blocks[ch] = m.group(0) if m.group(0).endswith("\n") else m.group(0) + "\n"
        pos = m.end()
    if text[pos:].strip():
        residue.append(text[pos:].strip()[:80])
    return preamble, blocks, residue


def render_events(preamble: str, blocks: dict[int, str]) -> str:
    head = preamble.rstrip("\n") + "\n\n" if preamble.strip() else ""
    return head + "".join(blocks[k] for k in sorted(blocks))


def make_block(ch: int, manuscript_sha: str, run_id: str, body: str) -> str:
    return (f"<!-- BEGIN ch={ch} sha={manuscript_sha[:12]} run={run_id} -->\n"
            f"### {ch}화\n{body.strip()}\n<!-- END ch={ch} -->\n")


def parse_patch(text: str) -> tuple[list[tuple[int, str, dict]], list[str]]:
    """extract 출력의 '## 기록' 섹션 항목. '인용'은 마지막 필드이며 나머지 전부를 값으로 가진다."""
    entries, errors = [], []
    in_record = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            in_record = line[3:].strip() == "기록"
            continue
        stripped = line.strip()
        if not in_record or not stripped.startswith("- "):
            continue
        raw = stripped[2:]
        head, quote = raw, None
        if "| 인용:" in raw:
            head, quote = raw.split("| 인용:", 1)
        fields = {}
        for part in head.split("|"):
            if not part.strip():
                continue
            if ":" not in part:
                errors.append(f"{lineno}행: '키: 값' 형식이 아님 → {part.strip()[:30]}")
                continue
            key, value = part.split(":", 1)
            fields[key.strip()] = value.strip()
        if quote is not None:
            fields["인용"] = quote.strip()
        entries.append((lineno, raw, fields))
    return entries, errors


def patch_body(output_text: str) -> str:
    entries, _ = parse_patch(output_text)
    return "\n".join("- " + raw for _, raw, _ in entries)


def events_context(project: Project, ch: int, cast: list[str]) -> tuple[str, str]:
    path = project.events_path
    if not path.exists():
        return "(기록 없음)", "없음"
    _, blocks, _ = parse_events(read_text(path))
    prior = [blocks[k] for k in sorted(blocks) if k < ch]
    full = "".join(prior)
    if len(full) <= project.config["events_max_chars"]:
        return (full or "(이전 회차 기록 없음)"), f"{ch}화 이전 블록 전체"
    n = project.config["recent_event_chapters"]
    recent, older = prior[-n:], prior[:-n]
    picked = [line for block in older for line in block.splitlines()
              if line.startswith("- ") and any(name in line for name in cast)]
    text = ("### 오래된 기록 중 등장인물 이름이 포함된 항목 (이름 부분 일치 — 누락 가능)\n"
            + "\n".join(picked) + "\n\n" + "".join(recent))
    return text, f"최근 {n}화 전체 + 이전 기록 이름 부분 일치(부분 선택)"


# ---------------------------------------------------------------- context

def build_context(project: Project, stage: str, ch: int, from_run: str | None = None) -> tuple[str, list[dict]]:
    parts: list[str] = []
    inputs: list[dict] = []
    hide = stage != "review"

    def add_file(label: str, rel: str, transform=None, tname=None, required=True) -> str | None:
        path = project.path(rel)
        if not path.exists():
            if required:
                raise HarnessError(f"필수 자료가 없다: {rel}")
            return None
        text = read_text(path)
        if transform:
            text = transform(text)
        inputs.append({"path": rel, "sha256": sha256_file(path), "transform": tname})
        parts.append(f"## [{label}]\n\n{text.strip()}\n")
        return text

    def outline_transform(raw: str) -> str:
        if hide:
            raw = strip_hidden(raw)
        found = outline_for(raw, ch)
        if found is None:
            raise HarnessError(f"story/outline.md에 '### {ch}화' 계획이 없다.")
        return f"{found[0]}\n\n{found[1]}"

    if stage != "extract":
        add_file("작품 계약", "story/story-contract.md")
    add_file("설정" + (" (집필 제외 구간 삭제됨)" if hide else " (전체)"), "story/canon.md",
             strip_hidden if hide else None, "strip_hidden" if hide else None)

    cast: list[str] = []
    if stage in ("design", "draft", "review"):
        add_file("문체", "story/style.md")
        outline = add_file("현재 Arc와 이번 회차 계획", "story/outline.md",
                           outline_transform, f"outline_for({ch})")
        cast = cast_of(outline or "")
        add_file("관계 서술", "story/relations.md", required=False)

    events_text, events_note = events_context(project, ch, cast)
    if project.events_path.exists():
        inputs.append({"path": "state/events.md", "sha256": sha256_file(project.events_path),
                       "transform": events_note})
    parts.append(f"## [이전 회차까지의 사건·상태 기록 — {events_note}]\n\n{events_text.strip()}\n")

    if stage in ("design", "draft", "review") and ch > 1:
        prev = project.chapter_path(ch - 1)
        if prev.exists():
            limit = project.config["previous_chapter_max_chars"]
            text = read_text(prev)
            if len(text) > limit:
                text = "…(앞부분 생략)\n" + text[-limit:]
            inputs.append({"path": f"chapters/{ch_name(ch - 1)}.md", "sha256": sha256_file(prev),
                           "transform": f"tail({limit})"})
            parts.append(f"## [직전 확정 원고 {ch - 1}화]\n\n{text.strip()}\n")

    if from_run:
        out = project.run_dir(from_run) / "output.md"
        if not out.exists():
            raise HarnessError(f"참조 run의 출력이 없다: {from_run}")
        inputs.append({"path": f"runs/{from_run}/output.md", "sha256": sha256_file(out), "transform": None})
        parts.append(f"## [회차 설계 (run {from_run})]\n\n{read_text(out).strip()}\n")

    if stage in ("review", "extract"):
        add_file("대상 원고", f"drafts/{ch_name(ch)}.md")

    return "\n".join(parts), inputs


# ---------------------------------------------------------------- run

def prepare_run(project: Project, stage: str, ch: int, from_run: str | None = None) -> dict:
    if stage not in STAGES:
        raise HarnessError(f"알 수 없는 단계: {stage}")
    template = project.path(f"prompts/{stage}.md")
    if not template.exists():
        raise HarnessError(f"프롬프트가 없다: prompts/{stage}.md")
    context, inputs = build_context(project, stage, ch, from_run)
    inputs.insert(0, {"path": f"prompts/{stage}.md", "sha256": sha256_file(template), "transform": None})

    base = f"{dt.datetime.now():%Y%m%d-%H%M%S}-{ch_name(ch)}-{stage}"
    run_id, n = base, 2
    while project.run_dir(run_id).exists():
        run_id, n = f"{base}-{n}", n + 1
    rd = project.run_dir(run_id)
    rd.mkdir(parents=True)

    prompt = read_text(template).rstrip() + "\n\n---\n\n# 자료\n\n" + context
    _atomic_write(rd / "prompt.md", prompt)
    meta = {
        "run_id": run_id, "stage": stage, "chapter": ch, "created_at": now_iso(),
        "status": "prepared", "from_run": from_run, "inputs": inputs,
        "prompt_sha256": sha256_text(prompt),
    }
    if stage in ("review", "extract"):
        meta["manuscript_sha256"] = sha256_file(project.draft_path(ch))
    meta["codex_command"] = codex_command(project, stage, rd)
    project.save_meta(meta)
    return meta


def codex_command(project: Project, stage: str, rd: Path) -> list[str]:
    cfg = project.config["codex"]
    # --json: codex.log에 이벤트(JSONL)를 남겨 실제 파일 접근을 사후 확인한다(부분 검사).
    cmd = [cfg["binary"], "exec", "--json", "--sandbox", cfg["sandbox"], "-C", str(rd), "-o", str(rd / "output.md")]
    if cfg.get("ephemeral"):
        cmd.append("--ephemeral")
    if cfg.get("model"):
        cmd += ["-m", cfg["model"]]
    if stage == "review":
        cmd += ["--output-schema", str(project.path("schemas/review.schema.json"))]
    cmd += list(cfg.get("extra_args", []))
    cmd.append("-")  # 프롬프트는 stdin으로 전달
    return cmd


def execute_run(project: Project, meta: dict) -> dict:
    rd = project.run_dir(meta["run_id"])
    cmd = list(meta["codex_command"])
    exe = shutil.which(cmd[0])
    if not exe:
        raise HarnessError(f"'{cmd[0]}' 실행 파일을 찾지 못했다. --dry-run 후 수동 실행하고 finish를 쓸 수 있다.")
    meta["started_at"] = now_iso()
    with open(rd / "codex.log", "wb") as log:
        proc = subprocess.run([exe] + cmd[1:], input=(rd / "prompt.md").read_bytes(),
                              stdout=log, stderr=subprocess.STDOUT, cwd=rd)
    meta["returncode"] = proc.returncode
    if proc.returncode != 0 or not (rd / "output.md").exists():
        meta["status"] = "failed"
        meta["finished_at"] = now_iso()
        project.save_meta(meta)
        return meta
    return finish_run(project, meta)


def finish_run(project: Project, meta: dict) -> dict:
    rd = project.run_dir(meta["run_id"])
    out = rd / "output.md"
    if not out.exists():
        raise HarnessError(f"출력이 없다: runs/{meta['run_id']}/output.md")
    if not (rd / "output.orig.md").exists():
        shutil.copyfile(out, rd / "output.orig.md")
    meta["status"] = "completed"
    meta["finished_at"] = now_iso()
    meta["output_sha256"] = sha256_file(out)
    if meta["stage"] == "draft":
        draft = project.draft_path(meta["chapter"])
        if draft.exists():
            meta["draft_promoted"] = False
        else:
            _atomic_write(draft, read_text(out))
            meta["draft_promoted"] = True
    project.save_meta(meta)
    return meta


# ---------------------------------------------------------------- 자동 검사

def load_review_output(path: Path) -> dict:
    text = read_text(path).strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    try:
        return json.loads(fence.group(1) if fence else text)
    except json.JSONDecodeError as e:
        raise HarnessError(f"검수 출력이 JSON이 아니다: {e}")


def check(project: Project, ch: int, review_run: str | None = None, extract_run: str | None = None) -> list[dict]:
    issues: list[dict] = []

    def add(level: str, code: str, msg: str) -> None:
        issues.append({"level": level, "code": code, "msg": msg})

    draft = project.draft_path(ch)
    if not draft.exists():
        add("error", "draft-missing", f"원고 후보가 없다: drafts/{ch_name(ch)}.md")
        return issues
    text = read_text(draft)
    current_sha = sha256_file(draft)

    count = len(text.replace("\r", "").replace("\n", ""))
    lo, hi = project.config["char_count_with_spaces"]["min"], project.config["char_count_with_spaces"]["max"]
    if not lo <= count <= hi:
        add("warn", "length", f"공백 포함 {count}자 (참고 범위 {lo}~{hi}자)")

    outline = project.path("story/outline.md")
    if not outline.exists() or outline_for(read_text(outline), ch) is None:
        add("warn", "outline-missing", f"outline.md에 {ch}화 계획이 없다")

    canon = project.path("story/canon.md")
    if canon.exists():
        for canonical, variants in name_variants(read_text(canon)):
            for variant in variants:
                lines = [i for i, line in enumerate(text.splitlines(), 1)
                         if variant in line.replace(canonical, "\0")]
                if lines:
                    add("error", "name-variant", f"'{variant}' → 정식 표기 '{canonical}' ({', '.join(map(str, lines[:5]))}행)")

    events_text = read_text(project.events_path) if project.events_path.exists() else ""

    if review_run:
        meta = project.load_meta(review_run)
        if meta["stage"] != "review" or meta["chapter"] != ch:
            add("error", "run-mismatch", f"{review_run}은 {ch}화 review run이 아니다")
        else:
            if meta.get("manuscript_sha256") != current_sha:
                add("warn", "review-stale", "검수 이후 원고가 바뀌었다. 인용 위치와 지적이 달라졌을 수 있다")
            known_ids = set(EVENT_ID_RE.findall(events_text))
            data = load_review_output(project.run_dir(review_run) / "output.md")
            for i, finding in enumerate(data.get("findings", []), 1):
                quote = finding.get("quote", "")
                if quote and not quote_in(quote, text):
                    add("error", "quote-missing", f"검수 {i}번 인용이 원고에 없다: {quote[:40]}")
                for eid in EVENT_ID_RE.findall(finding.get("basis", "")):
                    if eid not in known_ids:
                        add("warn", "basis-missing", f"검수 {i}번 근거 {eid}가 events.md에 없다")

    if extract_run:
        meta = project.load_meta(extract_run)
        if meta["stage"] != "extract" or meta["chapter"] != ch:
            add("error", "run-mismatch", f"{extract_run}은 {ch}화 extract run이 아니다")
            return issues
        if meta.get("manuscript_sha256") != current_sha:
            add("error", "extract-stale", "추출 이후 원고가 바뀌었다. 최종 원고로 extract를 다시 실행하라")
        out = project.run_dir(extract_run) / "output.md"
        if not out.exists():
            add("error", "extract-output-missing", "extract 출력이 없다")
            return issues
        entries, errors = parse_patch(read_text(out))
        for err in errors:
            add("error", "patch-format", err)
        if not entries:
            add("warn", "patch-empty", "'## 기록' 항목이 없다")
        _, blocks, _ = parse_events(events_text)
        other_ids = {eid for k, b in blocks.items() if k != ch for eid in EVENT_ID_RE.findall(b)}
        seen: set[str] = set()
        for lineno, _, fields in entries:
            missing = [k for k in REQUIRED_KEYS if not fields.get(k)]
            if missing:
                add("error", "patch-field", f"{lineno}행: 필수 필드 없음 {missing}")
            kind = fields.get("유형")
            if kind and kind not in EVENT_TYPES:
                add("error", "patch-type", f"{lineno}행: 알 수 없는 유형 '{kind}'")
            if kind in ("발언", "믿음") and not fields.get("주체"):
                add("error", "patch-field", f"{lineno}행: 발언·믿음에는 '주체'가 필요하다")
            eid = fields.get("id", "")
            if eid and not re.fullmatch(rf"E{ch:04d}-\d{{2}}", eid):
                add("error", "patch-id", f"{lineno}행: id는 E{ch:04d}-NN 형식이어야 한다 ({eid})")
            if eid in seen or eid in other_ids:
                add("error", "patch-id", f"{lineno}행: id 중복 {eid}")
            seen.add(eid)
            quote = fields.get("인용", "")
            if quote and not quote_in(quote, text):
                add("error", "quote-missing", f"{lineno}행: 인용이 원고에 없다: {quote[:40]}")
    return issues


# ---------------------------------------------------------------- 승인·반영·복구

def approve(project: Project, ch: int, run_id: str, confirm: str) -> dict:
    meta = project.load_meta(run_id)
    if meta["stage"] != "extract" or meta["chapter"] != ch:
        raise HarnessError(f"{run_id}은 {ch}화 extract run이 아니다")
    errors = [i for i in check(project, ch, extract_run=run_id) if i["level"] == "error"]
    if errors:
        raise HarnessError("자동 검사 오류가 있어 승인할 수 없다:\n" + "\n".join(f"- {e['msg']}" for e in errors))
    expected = f"{ch_name(ch)} 승인"
    if confirm != expected:
        raise HarnessError(f"확인 문구가 다르다. 사람이 직접 '{expected}'를 입력해야 한다.")
    body = patch_body(read_text(project.run_dir(run_id) / "output.md"))
    approval = {
        "chapter": ch, "run_id": run_id, "approved_at": now_iso(),
        "manuscript_sha256": sha256_file(project.draft_path(ch)),
        "patch_sha256": sha256_text(body),
    }
    _atomic_write(project.run_dir(run_id) / "approval.json",
                  json.dumps(approval, ensure_ascii=False, indent=2) + "\n")
    return approval


def pending_transactions(ledger: list[dict]) -> list[dict]:
    last: dict[str, dict] = {}
    begins: dict[str, dict] = {}
    for entry in ledger:
        last[entry["txn"]] = entry
        if entry["op"] == "begin":
            begins[entry["txn"]] = entry
    return [begins[t] for t, e in last.items() if e["op"] == "begin"]


def committed_state(ledger: list[dict]) -> dict[int, dict]:
    state: dict[int, dict] = {}
    for entry in ledger:
        if entry["op"] == "done":
            state[entry["chapter"]] = entry
    return state


def commit(project: Project, ch: int, run_id: str, revise: bool = False) -> str:
    rd = project.run_dir(run_id)
    approval_path = rd / "approval.json"
    if not approval_path.exists():
        raise HarnessError("승인 기록이 없다. 먼저 사람이 approve를 실행해야 한다.")
    approval = json.loads(read_text(approval_path))
    if approval["chapter"] != ch:
        raise HarnessError("승인 기록의 회차가 다르다")
    draft = project.draft_path(ch)
    manuscript_sha = sha256_file(draft)
    if manuscript_sha != approval["manuscript_sha256"]:
        raise HarnessError("승인 이후 원고가 바뀌었다. 기존 승인은 무효다. extract → approve를 다시 하라.")
    body = patch_body(read_text(rd / "output.md"))
    patch_sha = sha256_text(body)
    if patch_sha != approval["patch_sha256"]:
        raise HarnessError("승인 이후 기록안이 바뀌었다. 다시 승인하라.")

    ledger = project.read_ledger()
    if pending_transactions(ledger):
        raise HarnessError("중단된 반영이 있다. `wn.py recover`로 먼저 복구하라.")
    state = committed_state(ledger)
    previous = state.get(ch)
    if previous and previous["manuscript_sha256"] == manuscript_sha and previous["patch_sha256"] == patch_sha:
        return "noop"
    if previous and not revise:
        raise HarnessError(f"{ch}화는 이미 다른 원고/기록으로 반영됐다. 수정 반영이면 --revise를 붙여라.")
    later = sorted(k for k in state if k > ch)

    events_text = read_text(project.events_path) if project.events_path.exists() else "# 사건·상태 기록\n"
    preamble, blocks, residue = parse_events(events_text)
    if residue:
        raise HarnessError("events.md 블록 밖에 텍스트가 있다(머리말 제외). 정리 후 다시 실행하라: " + "; ".join(residue))

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    txn = f"{run_id}@{stamp}"
    backup = rd / "backup" / stamp
    backup.mkdir(parents=True)
    chapter_path = project.chapter_path(ch)
    chapter_existed = chapter_path.exists()
    events_existed = project.events_path.exists()
    if chapter_existed:
        shutil.copyfile(chapter_path, backup / chapter_path.name)
    if events_existed:
        shutil.copyfile(project.events_path, backup / "events.md")

    common = {"txn": txn, "chapter": ch, "run_id": run_id,
              "manuscript_sha256": manuscript_sha, "patch_sha256": patch_sha}
    project.append_ledger({**common, "op": "begin", "at": now_iso(), "backup": backup.relative_to(project.root).as_posix(),
                           "chapter_existed": chapter_existed, "events_existed": events_existed,
                           "revise": bool(previous), "later_chapters": later})
    _atomic_write(chapter_path, read_text(draft))
    blocks[ch] = make_block(ch, manuscript_sha, run_id, body)
    _atomic_write(project.events_path, render_events(preamble, blocks))
    project.append_ledger({**common, "op": "done", "at": now_iso()})
    return "revised" if previous else "committed"


def recover(project: Project) -> list[str]:
    restored = []
    for begin in pending_transactions(project.read_ledger()):
        backup = project.path(begin["backup"])
        chapter_path = project.chapter_path(begin["chapter"])
        if begin["chapter_existed"]:
            shutil.copyfile(backup / chapter_path.name, chapter_path)
        elif chapter_path.exists():
            chapter_path.unlink()
        if begin["events_existed"]:
            shutil.copyfile(backup / "events.md", project.events_path)
        elif project.events_path.exists():
            project.events_path.unlink()
        project.append_ledger({"txn": begin["txn"], "op": "rolled_back", "chapter": begin["chapter"], "at": now_iso()})
        restored.append(begin["txn"])
    return restored


def status(project: Project) -> list[str]:
    ledger = project.read_ledger()
    state = committed_state(ledger)
    lines = []
    for begin in pending_transactions(ledger):
        lines.append(f"[중단된 반영] {begin['chapter']}화 txn={begin['txn']} → wn.py recover")
    chapters = set(state)
    for folder in ("drafts", "chapters"):
        for p in project.path(folder).glob("ch*.md") if project.path(folder).exists() else []:
            m = re.fullmatch(r"ch(\d{4})\.md", p.name)
            if m:
                chapters.add(int(m.group(1)))
    for ch in sorted(chapters):
        draft = project.draft_path(ch)
        draft_sha = sha256_file(draft) if draft.exists() else None
        done = state.get(ch)
        if done is None:
            label = "미반영"
        elif draft_sha == done["manuscript_sha256"]:
            label = "반영됨(원고 동일)"
        else:
            label = "반영 후 원고 변경됨 → 재추출·재승인 필요"
        lines.append(f"{ch}화: draft={draft_sha[:12] if draft_sha else '-'} {label}")
    return lines or ["기록 없음"]


# ---------------------------------------------------------------- CLI

def _print_issues(issues: list[dict]) -> int:
    for issue in issues:
        print(f"[{issue['level']}] {issue['code']}: {issue['msg']}")
    if not issues:
        print("자동 검사 통과 (자동 검사는 설정 모순·문장 품질을 판단하지 않는다)")
    return 1 if any(i["level"] == "error" for i in issues) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="무협 장편 집필 harness")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("context", help="단계별 context를 출력한다(실행 없음)")
    p.add_argument("stage", choices=STAGES)
    p.add_argument("chapter", type=int)
    p.add_argument("--from-run")

    p = sub.add_parser("run", help="run 폴더를 만들고 codex exec를 호출한다")
    p.add_argument("stage", choices=STAGES)
    p.add_argument("chapter", type=int)
    p.add_argument("--from-run", help="draft 단계에서 참조할 design run")
    p.add_argument("--dry-run", action="store_true", help="프롬프트와 명령만 만들고 codex는 호출하지 않는다")

    p = sub.add_parser("finish", help="수동 실행한 run의 output.md를 기록한다")
    p.add_argument("run_id")

    p = sub.add_parser("check", help="자동 검사")
    p.add_argument("chapter", type=int)
    p.add_argument("--review-run")
    p.add_argument("--extract-run")

    p = sub.add_parser("approve", help="[사람 전용] 원고와 기록안을 함께 승인한다")
    p.add_argument("chapter", type=int)
    p.add_argument("--run", required=True, help="extract run id")
    p.add_argument("--confirm", help="'chNNNN 승인'")

    p = sub.add_parser("commit", help="[사람 전용] 승인된 원고와 기록안을 반영한다")
    p.add_argument("chapter", type=int)
    p.add_argument("--run", required=True)
    p.add_argument("--revise", action="store_true")

    sub.add_parser("recover", help="중단된 반영을 백업으로 되돌린다")
    sub.add_parser("status", help="회차별 반영 상태")

    args = parser.parse_args(argv)
    project = Project(args.root)
    try:
        if args.cmd == "context":
            text, inputs = build_context(project, args.stage, args.chapter, args.from_run)
            print(text)
            print("\n<!-- inputs: " + json.dumps(inputs, ensure_ascii=False) + " -->")
        elif args.cmd == "run":
            meta = prepare_run(project, args.stage, args.chapter, args.from_run)
            print(f"run: {meta['run_id']}")
            if args.dry_run:
                print("dry-run. 수동 실행 명령 (프롬프트는 stdin):")
                print(" ".join(meta["codex_command"]) + f" < runs/{meta['run_id']}/prompt.md")
                print(f"실행 후: python harness/wn.py finish {meta['run_id']}")
            else:
                meta = execute_run(project, meta)
                print(f"status: {meta['status']} (log: runs/{meta['run_id']}/codex.log)")
                if meta.get("draft_promoted") is False:
                    print(f"drafts/{ch_name(args.chapter)}.md가 이미 있어 덮어쓰지 않았다. 출력: runs/{meta['run_id']}/output.md")
                return 0 if meta["status"] == "completed" else 1
        elif args.cmd == "finish":
            meta = finish_run(project, project.load_meta(args.run_id))
            print(f"status: {meta['status']}")
        elif args.cmd == "check":
            return _print_issues(check(project, args.chapter, args.review_run, args.extract_run))
        elif args.cmd == "approve":
            confirm = args.confirm
            if confirm is None and sys.stdin.isatty():
                confirm = input(f"원고와 기록안을 읽었다면 '{ch_name(args.chapter)} 승인'을 입력: ").strip()
            approval = approve(project, args.chapter, args.run, confirm or "")
            print(f"승인 기록: manuscript={approval['manuscript_sha256'][:12]} patch={approval['patch_sha256'][:12]}")
        elif args.cmd == "commit":
            result = commit(project, args.chapter, args.run, args.revise)
            later = [k for k in committed_state(project.read_ledger()) if k > args.chapter]
            print({"noop": "이미 같은 원고·기록으로 반영돼 있다. 변경 없음.",
                   "committed": "반영 완료.", "revised": "수정 반영 완료."}[result])
            if result == "revised" and later:
                print(f"주의: 이후 회차 {later}의 기록은 수정 전 원고를 전제로 했을 수 있다. 검수가 필요하다.")
            if result != "noop":
                print("wn 반영은 Git 커밋이 아니다. 확인 후 직접: git add chapters state runs && git commit")
        elif args.cmd == "recover":
            restored = recover(project)
            print("복구: " + (", ".join(restored) if restored else "중단된 반영 없음"))
        elif args.cmd == "status":
            print("\n".join(status(project)))
    except HarnessError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
