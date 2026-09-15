"""wn.py 단위 테스트. 실행: python -m unittest discover -s harness"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wn  # noqa: E402

CANON = """# 설정
## 표기
| 정식 | 금지 변형 |
|---|---|
| 벽라궁 | 벽라곡, 벽나궁 |

## 마환
공개 규칙.
<!-- 집필제외:시작 -->
비밀: 봉인은 삼십 년 시한이다.
<!-- 집필제외:끝 -->
"""

OUTLINE = """# 개요
## Arc 1: 변방
변방 Arc 소개.
### 1화 약상자
- 등장: 서준, 서윤
첫 화 계획.
### 2화 읽기
- 등장: 서준, 연
둘째 화 계획. 미래 비밀 없음.
## Arc 2: 남행
### 3화
셋째 화.
"""

DRAFT = "서준은 숙부의 약상자를 열었다.\n\"이건 팔 수 없어.\" 그가 말했다.\n벽라궁의 문양이 보였다.\n"

PATCH = """## 기록
- id: E0001-01 | 유형: 사건 | 장면: 1 | 내용: 서준이 약상자를 열었다 | 인용: "숙부의 약상자를 열었다"
- id: E0001-02 | 유형: 발언 | 주체: 서준 | 장면: 1 | 내용: 팔지 않겠다고 말함 | 인용: "이건 팔 수 없어."

## 설정 추가 의심
- 없음
"""


class HarnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        files = {
            "story/story-contract.md": "# 계약\n",
            "story/canon.md": CANON,
            "story/style.md": "# 문체\n",
            "story/outline.md": OUTLINE,
            "story/relations.md": "# 관계\n",
            "state/events.md": "# 사건·상태 기록\n",
            "prompts/design.md": "설계하라",
            "prompts/draft.md": "쓰라",
            "prompts/review.md": "검수하라",
            "prompts/extract.md": "추출하라",
            "drafts/ch0001.md": DRAFT,
        }
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        (root / "harness").mkdir()
        (root / "harness" / "config.json").write_text(
            json.dumps({"char_count_with_spaces": {"min": 1, "max": 100000}}), encoding="utf-8")
        self.project = wn.Project(root)

    def tearDown(self):
        self.tmp.cleanup()

    def extract_run(self, patch=PATCH):
        meta = wn.prepare_run(self.project, "extract", 1)
        (self.project.run_dir(meta["run_id"]) / "output.md").write_text(patch, encoding="utf-8")
        wn.finish_run(self.project, meta)
        return meta["run_id"]

    def test_strip_hidden_and_unbalanced(self):
        self.assertNotIn("삼십 년", wn.strip_hidden(CANON))
        with self.assertRaises(wn.HarnessError):
            wn.strip_hidden("a <!-- 집필제외:시작 --> b")

    def test_outline_only_current_chapter(self):
        arc, plan = wn.outline_for(OUTLINE, 1)
        self.assertIn("변방 Arc 소개", arc)
        self.assertIn("첫 화 계획", plan)
        self.assertNotIn("둘째 화", plan)
        self.assertEqual(wn.cast_of(plan), ["서준", "서윤"])
        self.assertIsNone(wn.outline_for(OUTLINE, 9))

    def test_draft_context_hides_review_context_shows(self):
        draft_prompt = (self.project.run_dir(wn.prepare_run(self.project, "draft", 1)["run_id"]) / "prompt.md").read_text(encoding="utf-8")
        review_prompt = (self.project.run_dir(wn.prepare_run(self.project, "review", 1)["run_id"]) / "prompt.md").read_text(encoding="utf-8")
        self.assertNotIn("삼십 년", draft_prompt)
        self.assertNotIn("둘째 화 계획", draft_prompt)
        self.assertIn("삼십 년", review_prompt)

    def test_quote_in(self):
        self.assertTrue(wn.quote_in("“이건 팔 수 없어.”", DRAFT))
        self.assertTrue(wn.quote_in("서준은 … 열었다", DRAFT))
        self.assertFalse(wn.quote_in("반지를 끼었다", DRAFT))

    def test_check_detects_missing_quote_variant_and_bad_id(self):
        bad = PATCH.replace("숙부의 약상자를 열었다", "반지를 끼었다").replace("E0001-02", "E0001-01")
        (self.project.draft_path(1)).write_text(DRAFT + "벽라곡으로 간다.\n", encoding="utf-8")
        run_id = self.extract_run(bad)
        codes = {i["code"] for i in wn.check(self.project, 1, extract_run=run_id) if i["level"] == "error"}
        self.assertIn("quote-missing", codes)
        self.assertIn("name-variant", codes)
        self.assertIn("patch-id", codes)

    def test_commit_flow_is_idempotent(self):
        run_id = self.extract_run()
        wn.approve(self.project, 1, run_id, "ch0001 승인")
        self.assertEqual(wn.commit(self.project, 1, run_id), "committed")
        self.assertEqual(wn.commit(self.project, 1, run_id), "noop")
        events = self.project.events_path.read_text(encoding="utf-8")
        self.assertEqual(events.count("<!-- BEGIN ch=1 "), 1)
        self.assertTrue(self.project.chapter_path(1).exists())

    def test_wrong_confirm_rejected(self):
        run_id = self.extract_run()
        with self.assertRaises(wn.HarnessError):
            wn.approve(self.project, 1, run_id, "승인")

    def test_manuscript_change_invalidates_approval(self):
        run_id = self.extract_run()
        wn.approve(self.project, 1, run_id, "ch0001 승인")
        self.project.draft_path(1).write_text(DRAFT + "추가 문장.\n", encoding="utf-8")
        with self.assertRaises(wn.HarnessError):
            wn.commit(self.project, 1, run_id)

    def test_stale_extract_cannot_be_approved(self):
        run_id = self.extract_run()
        self.project.draft_path(1).write_text(DRAFT + "수정.\n", encoding="utf-8")
        with self.assertRaises(wn.HarnessError):
            wn.approve(self.project, 1, run_id, "ch0001 승인")

    def test_revision_requires_flag(self):
        run_id = self.extract_run()
        wn.approve(self.project, 1, run_id, "ch0001 승인")
        wn.commit(self.project, 1, run_id)
        self.project.draft_path(1).write_text(DRAFT + "수정.\n", encoding="utf-8")
        run2 = self.extract_run()
        wn.approve(self.project, 1, run2, "ch0001 승인")
        with self.assertRaises(wn.HarnessError):
            wn.commit(self.project, 1, run2)
        self.assertEqual(wn.commit(self.project, 1, run2, revise=True), "revised")
        events = self.project.events_path.read_text(encoding="utf-8")
        self.assertEqual(events.count("<!-- BEGIN ch=1 "), 1)
        self.assertIn(run2, events)

    def test_interrupted_commit_is_detected_and_recovered(self):
        run_id = self.extract_run()
        wn.approve(self.project, 1, run_id, "ch0001 승인")
        original_events = self.project.events_path.read_text(encoding="utf-8")
        real_write = wn._atomic_write

        def failing_write(path, text):
            if path.name == "events.md":
                raise OSError("디스크 오류 시뮬레이션")
            real_write(path, text)

        wn._atomic_write = failing_write
        try:
            with self.assertRaises(OSError):
                wn.commit(self.project, 1, run_id)
        finally:
            wn._atomic_write = real_write
        self.assertTrue(self.project.chapter_path(1).exists())
        self.assertTrue(any("중단된 반영" in line for line in wn.status(self.project)))
        with self.assertRaises(wn.HarnessError):
            wn.commit(self.project, 1, run_id)
        self.assertEqual(len(wn.recover(self.project)), 1)
        self.assertFalse(self.project.chapter_path(1).exists())
        self.assertEqual(self.project.events_path.read_text(encoding="utf-8"), original_events)
        self.assertEqual(wn.commit(self.project, 1, run_id), "committed")

    def test_text_outside_blocks_blocks_commit(self):
        run_id = self.extract_run()
        wn.approve(self.project, 1, run_id, "ch0001 승인")
        wn.commit(self.project, 1, run_id)
        with open(self.project.events_path, "a", encoding="utf-8") as f:
            f.write("손으로 적은 메모\n")
        self.project.draft_path(1).write_text(DRAFT + "수정.\n", encoding="utf-8")
        run2 = self.extract_run()
        wn.approve(self.project, 1, run2, "ch0001 승인")
        with self.assertRaises(wn.HarnessError):
            wn.commit(self.project, 1, run2, revise=True)


if __name__ == "__main__":
    unittest.main()
