import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from csbaoyan_daily.app.generate import GenerateOptions, run_generate_report
from csbaoyan_daily.domain.report_generation import STRUCTURED_EXTRACTION_PROMPT
from csbaoyan_daily.domain.stats import (
    PipelineStats,
    attach_eval_to_stats,
    count_extracted_items,
    rebuild_stats_summary,
    write_pipeline_stats,
)


def _make_stats(**overrides) -> PipelineStats:
    fields = dict(
        raw_messages=100,
        kept_messages=80,
        dropped_total=20,
        dropped_emoji_only=12,
        dropped_noise_token=4,
        dropped_flood=4,
        dropped_non_text=0,
        speakers=23,
        chunks=2,
        items=21,
        quotes=18,
        structured=True,
        model="test-model",
        generated_at="2026-08-19T12:00:00",
    )
    fields.update(overrides)
    return PipelineStats(**fields)


class CountExtractedItemsTests(unittest.TestCase):
    def test_counts_items_and_quotes(self) -> None:
        text = (
            "# Chunk 1\n\n"
            "- 时间范围：09:00:00 - 12:00:00\n"
            "- [推免|high] 摘要一 ——「原话一」（User_1 @ 09:10:00）\n"
            "- [答疑|mid] 摘要二\n"
            "# Chunk 2\n\n"
            "- 时间范围：13:00:00 - 18:00:00\n"
            "- [闲聊] 摘要三 ——「原话三」（User_2 @ 14:00:00）\n"
            "普通段落，含成报式引用“弯引号”。\n"
        )
        items, quotes = count_extracted_items(text)
        self.assertEqual(items, 3)
        self.assertEqual(quotes, 3)  # 「×2 + “×1，时间范围头行不计入要点

    def test_empty_text(self) -> None:
        self.assertEqual(count_extracted_items(""), (0, 0))


class WritePipelineStatsTests(unittest.TestCase):
    def test_writes_json_with_all_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pages_dir = Path(tmpdir)
            stats = _make_stats()
            path = write_pipeline_stats(pages_dir, "2026-05-18", stats)

            self.assertEqual(path, pages_dir / "data" / "stats" / "2026-05-18.json")
            data = json.loads(path.read_text(encoding="utf-8"))
            for field, value in {
                "raw_messages": 100,
                "kept_messages": 80,
                "dropped_total": 20,
                "dropped_emoji_only": 12,
                "dropped_noise_token": 4,
                "dropped_flood": 4,
                "dropped_non_text": 0,
                "speakers": 23,
                "chunks": 2,
                "items": 21,
                "quotes": 18,
                "structured": True,
                "model": "test-model",
                "generated_at": "2026-08-19T12:00:00",
                "eval": None,
            }.items():
                self.assertEqual(data[field], value, field)

    def test_eval_field_serializes_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pages_dir = Path(tmpdir)
            path = write_pipeline_stats(
                pages_dir, "2026-05-18", _make_stats(eval={"faithfulness": 5, "recall": 4, "average": 0.9})
            )
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["eval"], {"faithfulness": 5, "recall": 4, "average": 0.9})


class AttachEvalTests(unittest.TestCase):
    def test_attach_eval_updates_existing_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pages_dir = Path(tmpdir)
            write_pipeline_stats(pages_dir, "2026-05-18", _make_stats())
            result = SimpleNamespace(
                faithfulness=SimpleNamespace(raw=5, normalized=1.0),
                recall=SimpleNamespace(raw=4, normalized=0.8),
                average=0.9,
            )

            path = attach_eval_to_stats(pages_dir, "2026-05-18", result)

            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["eval"], {"faithfulness": 5, "recall": 4, "average": 0.9})
            self.assertEqual(data["raw_messages"], 100)  # 其余字段不被破坏

    def test_attach_eval_requires_existing_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(FileNotFoundError):
                attach_eval_to_stats(Path(tmpdir), "2026-05-18", SimpleNamespace())


class RebuildStatsSummaryTests(unittest.TestCase):
    def test_aggregates_multiple_editions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pages_dir = Path(tmpdir)
            write_pipeline_stats(pages_dir, "2026-05-17", _make_stats(raw_messages=90, items=10, quotes=8))
            write_pipeline_stats(
                pages_dir, "2026-05-18", _make_stats(raw_messages=110, items=11, quotes=10, eval={"faithfulness": 5, "recall": 4, "average": 0.9})
            )
            (pages_dir / "data" / "stats" / "broken.json").write_text("not-json", encoding="utf-8")

            summary_path = rebuild_stats_summary(pages_dir)

            self.assertEqual(summary_path, pages_dir / "data" / "stats" / "summary.json")
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["editions"], 2)  # 坏文件不计数
            self.assertEqual(summary["total_raw_messages"], 200)
            self.assertEqual(summary["total_kept_messages"], 160)
            self.assertEqual(summary["total_dropped_total"], 40)
            self.assertEqual(summary["total_items"], 21)
            self.assertEqual(summary["total_quotes"], 18)
            self.assertEqual(
                summary["latest_eval"],
                {"date": "2026-05-18", "faithfulness": 5, "recall": 4, "average": 0.9},
            )

    def test_latest_eval_prefers_latest_date_with_eval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pages_dir = Path(tmpdir)
            write_pipeline_stats(
                pages_dir, "2026-05-17", _make_stats(eval={"faithfulness": 3, "recall": 3, "average": 0.6})
            )
            write_pipeline_stats(pages_dir, "2026-05-18", _make_stats())  # 无 eval

            summary = json.loads(rebuild_stats_summary(pages_dir).read_text(encoding="utf-8"))

            self.assertEqual(summary["latest_eval"]["date"], "2026-05-17")

    def test_empty_pages_dir_produces_zero_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pages_dir = Path(tmpdir) / "pages"
            summary = json.loads(rebuild_stats_summary(pages_dir).read_text(encoding="utf-8"))
            self.assertEqual(summary["editions"], 0)
            self.assertEqual(summary["total_raw_messages"], 0)
            self.assertIsNone(summary["latest_eval"])


@dataclass
class _FakeCompletion:
    content: str

    @property
    def choices(self):
        return [SimpleNamespace(message=SimpleNamespace(content=self.content))]


class _FakeChatCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        system = kwargs["messages"][0]["content"]
        if system == STRUCTURED_EXTRACTION_PROMPT:
            payload = {
                "items": [
                    {
                        "category": "推免",
                        "confidence": "high",
                        "summary": "有人询问预推免系统的开放时间。",
                        "quote": "预推免系统什么时候开",
                        "speaker": "User_1",
                        "time": "09:10:00",
                    }
                ]
            }
            return _FakeCompletion("```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```")
        return _FakeCompletion("# 2026-05-18 保研日报\n\n## 今日概览\n\n群里提到“预推免系统什么时候开”。\n")


class _FakeClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=_FakeChatCompletions())


class GenerateStatsIntegrationTests(unittest.TestCase):
    """mock LLM 客户端跑完整 run_generate_report，断言付印工单随产物落盘。"""

    def _write_export(self, export_dir: Path) -> None:
        messages = [
            {
                "id": "m1",
                "time": "2026-05-18 09:10:00",
                "sender": {"uid": "u1", "name": "同学甲"},
                "content": {"text": "预推免系统什么时候开"},
            },
            {
                "id": "m2",
                "time": "2026-05-18 09:11:00",
                "sender": {"uid": "u2", "name": "同学乙"},
                "content": {"text": "去年是九月初开，今年估计差不多"},
            },
            {
                "id": "m3",
                "time": "2026-05-18 09:12:00",
                "sender": {"uid": "u1", "name": "同学甲"},
                "content": {"text": "😂😂"},
            },
            {
                "id": "m4",
                "time": "2026-05-18 09:13:00",
                "sender": {"uid": "u2", "name": "同学乙"},
                "content": {"text": "建议每天都刷一下官网"},
            },
        ]
        payload = {
            "messages": messages,
            "statistics": {"timeRange": {"end": "2026-05-18 23:59:00"}},
        }
        (export_dir / "2026-05-18.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def test_generate_writes_stats_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            export_dir = root / "chat_exports"
            pages_dir = root / "pages"
            export_dir.mkdir()
            self._write_export(export_dir)
            fake_client = _FakeClient()

            with patch("csbaoyan_daily.app.generate.create_openai_client", return_value=fake_client):
                artifacts = run_generate_report(
                    GenerateOptions(
                        export_dir=export_dir,
                        pages_dir=pages_dir,
                        date="2026-05-18",
                        model="test-model",
                        api_key="test-key",
                        max_workers=1,
                    )
                )

            self.assertEqual(artifacts.report_date, "2026-05-18")
            self.assertIsNotNone(artifacts.stats_path)
            assert artifacts.stats_path is not None

            stats = json.loads(artifacts.stats_path.read_text(encoding="utf-8"))
            self.assertEqual(stats["raw_messages"], 4)
            self.assertEqual(stats["kept_messages"], 3)      # 纯 emoji 被滤除
            self.assertEqual(stats["dropped_total"], 1)
            self.assertEqual(stats["dropped_emoji_only"], 1)
            self.assertEqual(stats["dropped_non_text"], 0)  # 4 条导出消息都有正文
            self.assertEqual(stats["speakers"], 2)
            self.assertEqual(stats["chunks"], 1)
            self.assertEqual(stats["items"], 1)              # 时间范围头行不计
            self.assertEqual(stats["quotes"], 1)             # 「预推免系统什么时候开」
            self.assertTrue(stats["structured"])
            self.assertEqual(stats["model"], "test-model")
            self.assertEqual(stats["eval"], None)

            summary_path = pages_dir / "data" / "stats" / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["editions"], 1)
            self.assertEqual(summary["total_raw_messages"], 4)
            self.assertEqual(summary["total_dropped_total"], 1)


if __name__ == "__main__":
    unittest.main()
