from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from csbaoyan_daily.factcheck.claims import extract_claims
from csbaoyan_daily.factcheck.judge import parse_judge
from csbaoyan_daily.factcheck.nli import NliResult
from csbaoyan_daily.factcheck.pipeline import format_factcheck_result, run_factcheck


class _FakeClient:
    def __init__(self, contents: list[object]) -> None:
        self._contents = list(contents)
        self.calls: list[dict[str, object]] = []

    def _create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if not self._contents:
            raise AssertionError("预设内容已耗尽")
        content = self._contents.pop(0)
        if isinstance(content, Exception):
            raise content
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _client(contents: list[object]) -> _FakeClient:
    c = _FakeClient(contents)
    c.chat = SimpleNamespace(completions=SimpleNamespace(create=c._create))
    return c


class _MockNli:
    def __init__(self, mapping: dict[str, NliResult]) -> None:
        self._mapping = mapping

    def available(self) -> bool:
        return True

    def score(self, premise: str, hypothesis: str) -> NliResult:
        return self._mapping.get(hypothesis, NliResult("neutral", 0.5))


_REPORT = "- 导师提名无实际作用。\n- 北大夏令营 8 月 15 日截止。\n"


class ClaimsTests(unittest.TestCase):
    def test_extracts_claims(self) -> None:
        claims = extract_claims(_REPORT)
        texts = [c.text for c in claims]
        self.assertIn("导师提名无实际作用", texts)
        self.assertIn("北大夏令营 8 月 15 日截止", texts)
        self.assertFalse(any(c.text.startswith("#") for c in claims))


class ParseJudgeTests(unittest.TestCase):
    def test_supported_with_conf(self) -> None:
        v = parse_judge("supported\n0.9\n来源提到")
        self.assertEqual(v.label, "supported")
        self.assertAlmostEqual(v.confidence, 0.9)

    def test_contradicted_no_conf_defaults_to_one(self) -> None:
        v = parse_judge("contradicted\n理由")
        self.assertEqual(v.label, "contradicted")
        self.assertAlmostEqual(v.confidence, 1.0)

    def test_unknown_defaults(self) -> None:
        v = parse_judge("无法判断")
        self.assertEqual(v.label, "not_enough_info")

    def test_does_not_eat_date_integers(self) -> None:
        v = parse_judge("not_enough_info\n北大夏令营 8 月 15 日截止，找不到")
        self.assertEqual(v.label, "not_enough_info")
        self.assertAlmostEqual(v.confidence, 1.0)  # 不应把 15 当置信度


class PipelineTests(unittest.TestCase):
    def test_all_judged_without_nli(self) -> None:
        c = _client(["not_enough_info\n0.6\n找不到", "supported\n0.9\n来源有"])
        r = run_factcheck(c, "m", "源", _REPORT)
        self.assertEqual(len(r.verdicts), 2)
        self.assertTrue(all(v.source == "judge" for v in r.verdicts))
        self.assertEqual(r.counts["not_enough_info"], 1)
        self.assertEqual(r.counts["supported"], 1)
        self.assertAlmostEqual(r.support_rate, 0.5)

    def test_nli_short_circuits_entailment(self) -> None:
        nli = _MockNli({"导师提名无实际作用": NliResult("entailment", 0.95)})
        c = _client(["supported\n0.9\n来源有"])  # 只有第二条走裁判
        r = run_factcheck(c, "m", "源", _REPORT, nli=nli)
        first = r.verdicts[0]
        self.assertEqual(first.source, "nli")
        self.assertEqual(first.label, "supported")
        self.assertEqual(len(c.calls), 1)  # 第二条才调裁判

    def test_nli_unavailable_skips_nli(self) -> None:
        class _Off:
            def available(self) -> bool:
                return False

            def score(self, premise: str, hypothesis: str) -> NliResult:
                raise AssertionError("available 为 False 时不应调用 score")

        c = _client(["supported\n0.9\nx", "supported\n0.9\ny"])
        r = run_factcheck(c, "m", "源", _REPORT, nli=_Off())
        self.assertEqual(len(r.verdicts), 2)
        self.assertTrue(all(v.source == "judge" for v in r.verdicts))

    def test_nli_contradiction_maps_to_contradicted(self) -> None:
        nli = _MockNli({"导师提名无实际作用": NliResult("contradiction", 0.9)})
        c = _client(["supported\n0.9\n来源有"])
        r = run_factcheck(c, "m", "源", _REPORT, nli=nli)
        self.assertEqual(r.verdicts[0].label, "contradicted")
        self.assertEqual(r.verdicts[0].source, "nli")

    def test_format_contains_summary(self) -> None:
        c = _client(["supported\n0.9\nx", "contradicted\n0.8\ny"])
        r = run_factcheck(c, "m", "源", _REPORT)
        txt = format_factcheck_result(r)
        self.assertIn("声明总数", txt)
        self.assertIn("支持率", txt)
        self.assertIn("逐条核验", txt)


if __name__ == "__main__":
    unittest.main()
