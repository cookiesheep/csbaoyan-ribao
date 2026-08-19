from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from csbaoyan_daily.eval.geval import GEVAL_FAITHFULNESS_PROMPT, geval_score, parse_score
from csbaoyan_daily.eval.harness import format_eval_result, run_evaluation


class _FakeClient:
    """按顺序返回预设内容；Exception 会被抛出。"""

    def __init__(self, contents: list[object]) -> None:
        self._contents = list(contents)
        self.calls: list[dict[str, object]] = []

    def _create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if not self._contents:
            raise AssertionError("FakeClient 预设内容已耗尽")
        content = self._contents.pop(0)
        if isinstance(content, Exception):
            raise content
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _client(contents: list[object]) -> _FakeClient:
    c = _FakeClient(contents)
    c.chat = SimpleNamespace(completions=SimpleNamespace(create=c._create))
    return c


class ParseScoreTests(unittest.TestCase):
    def test_last_integer(self) -> None:
        self.assertEqual(parse_score("理由：覆盖较好\n4"), (4, "理由：覆盖较好\n4"))

    def test_picks_last_when_multiple(self) -> None:
        # 「1-5」里的 1/5 不应干扰，取最后一个独立整数
        self.assertEqual(parse_score("按 1-5 打分，最终给 3"), (3, "按 1-5 打分，最终给 3"))

    def test_no_integer_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_score("没有给出分数")


class GevalScoreTests(unittest.TestCase):
    def test_score_and_normalize(self) -> None:
        c = _client(["覆盖全面\n5"])
        s = geval_score(c, "m", GEVAL_FAITHFULNESS_PROMPT, "源", "报", criterion_name="faithfulness")
        self.assertEqual(s.raw, 5)
        self.assertAlmostEqual(s.normalized, 1.0)
        self.assertEqual(s.criterion, "faithfulness")

    def test_retries_then_success(self) -> None:
        c = _client([RuntimeError("x"), RuntimeError("y"), "4"])
        s = geval_score(c, "m", GEVAL_FAITHFULNESS_PROMPT, "s", "r", retries=3)
        self.assertEqual(s.raw, 4)
        self.assertEqual(len(c.calls), 3)

    def test_all_fail_raises(self) -> None:
        c = _client([RuntimeError("x")] * 3)
        with self.assertRaises(RuntimeError):
            geval_score(c, "m", GEVAL_FAITHFULNESS_PROMPT, "s", "r", retries=3)

    def test_temperature_is_zero(self) -> None:
        c = _client(["5"])
        geval_score(c, "m", GEVAL_FAITHFULNESS_PROMPT, "s", "r")
        self.assertEqual(c.calls[0]["temperature"], 0.0)


class HarnessTests(unittest.TestCase):
    def test_run_evaluation_two_criteria(self) -> None:
        # 顺序：先 faithfulness 后 recall
        c = _client(["5", "3"])
        r = run_evaluation(c, "m", "源", "报")
        self.assertEqual(r.faithfulness.raw, 5)
        self.assertEqual(r.recall.raw, 3)
        self.assertAlmostEqual(r.average, (1.0 + 0.6) / 2)

    def test_format_contains_scores(self) -> None:
        c = _client(["5", "4"])
        r = run_evaluation(c, "m", "s", "r")
        text = format_eval_result(r)
        self.assertIn("faithfulness", text)
        self.assertIn("5/5", text)
        self.assertIn("recall", text)
        self.assertIn("average", text)


if __name__ == "__main__":
    unittest.main()
