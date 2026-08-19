from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from csbaoyan_daily.domain.chat_processing import AnonymizedMessage, ChatChunk
from csbaoyan_daily.domain.report_generation import (
    _cooled_temperature,
    _render_structured_items,
    call_llm_structured,
    extract_all_chunks_structured,
    generate_final_report,
    parse_structured_payload,
)


class _FakeClient:
    """模拟 OpenAI 客户端：按顺序返回预设内容，异常对象也会被抛出。"""

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



def _build_fake_client(contents: list[object]) -> _FakeClient:
    client = _FakeClient(contents)
    client.chat = SimpleNamespace(completions=SimpleNamespace(create=client._create))
    return client


class ParseStructuredPayloadTests(unittest.TestCase):
    def test_plain_json(self) -> None:
        items = parse_structured_payload('{"items": [{"summary": "x"}]}')
        self.assertEqual(items, [{"summary": "x"}])

    def test_fenced_json(self) -> None:
        payload = "好的，结果如下：\n```json\n{\"items\": []}\n```\n谢谢"
        self.assertEqual(parse_structured_payload(payload), [])

    def test_prose_wrapped_json(self) -> None:
        self.assertEqual(parse_structured_payload('结果：{"items": [{"a": 1}]} 完毕'), [{"a": 1}])

    def test_missing_items_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_structured_payload('{"data": []}')


class CooledTemperatureTests(unittest.TestCase):
    def test_schedule(self) -> None:
        self.assertEqual(_cooled_temperature(0.2, 1), 0.2)
        self.assertEqual(_cooled_temperature(0.2, 2), 0.1)
        self.assertEqual(_cooled_temperature(0.2, 3), 0.0)
        self.assertEqual(_cooled_temperature(0.2, 4), 0.0)


class RenderStructuredItemsTests(unittest.TestCase):
    def test_empty_items(self) -> None:
        rendered = _render_structured_items("09:00", "10:00", [])
        self.assertIn("（本段无可提取信息）", rendered)

    def test_with_items(self) -> None:
        rendered = _render_structured_items("09:00", "10:00", [
            {"category": "夏令营", "confidence": "高", "summary": "A营报名开启",
             "quote": "夏令营A开始报名了", "speaker": "User_1", "time": "09:00"},
        ])
        self.assertIn("[夏令营|高]", rendered)
        self.assertIn("A营报名开启", rendered)
        self.assertIn("「夏令营A开始报名了」（User_1 @ 09:00）", rendered)


class CallLlmStructuredTests(unittest.TestCase):
    @patch("csbaoyan_daily.domain.report_generation.time.sleep", lambda _s: None)
    def test_success_first_try(self) -> None:
        client = _build_fake_client(['{"items": [{"summary": "ok"}]}'])
        items = call_llm_structured(client, "m", "sys", "usr", retries=3, temperature=0.2)
        self.assertEqual(items, [{"summary": "ok"}])
        self.assertEqual(len(client.calls), 1)

    @patch("csbaoyan_daily.domain.report_generation.time.sleep", lambda _s: None)
    def test_retries_with_cooling_until_success(self) -> None:
        client = _build_fake_client([
            RuntimeError("boom"),
            RuntimeError("boom"),
            '{"items": []}',
        ])
        items = call_llm_structured(client, "m", "sys", "usr", retries=3, temperature=0.2)
        self.assertEqual(items, [])
        self.assertEqual(len(client.calls), 3)
        temps = [call["temperature"] for call in client.calls]
        self.assertEqual(temps, [0.2, 0.1, 0.0])  # 温度降温：0.2 → 0.1 → 0.0

    @patch("csbaoyan_daily.domain.report_generation.time.sleep", lambda _s: None)
    def test_exhausts_retries_raises(self) -> None:
        client = _build_fake_client([RuntimeError("boom")] * 3)
        with self.assertRaises(RuntimeError):
            call_llm_structured(client, "m", "sys", "usr", retries=3, temperature=0.2)


class ExtractAllChunksStructuredTests(unittest.TestCase):
    def _chunk(self) -> ChatChunk:
        msgs = [AnonymizedMessage(time="09:00", speaker="User_1", text="夏令营A开始报名了")]
        return ChatChunk(index=1, messages=msgs)

    def test_writes_quote_grounded_markdown(self) -> None:
        payload = json.dumps({"items": [{
            "category": "夏令营", "confidence": "高", "summary": "A营报名开启",
            "quote": "夏令营A开始报名了", "speaker": "User_1", "time": "09:00",
        }]})
        client = _build_fake_client([payload])
        with tempfile.TemporaryDirectory() as tmpdir:
            extracted_path = Path(tmpdir) / "extracted.md"
            extract_all_chunks_structured(
                chunks=[self._chunk()],
                extracted_path=extracted_path,
                client=client,
                model="m",
                retries=1,
                temperature=0.2,
                max_workers=1,
            )
            content = extracted_path.read_text(encoding="utf-8")
        self.assertIn("# Chunk 1", content)
        self.assertIn("[夏令营|高]", content)
        self.assertIn("「夏令营A开始报名了」（User_1 @ 09:00）", content)


class GenerateFinalReportConsumesStructuredTests(unittest.TestCase):
    def test_final_report_reads_structured_extracted(self) -> None:
        client = _build_fake_client(["# CS保研信息日报\n\n## 今日概览\n\n结构化输入的概览。\n"])
        with tempfile.TemporaryDirectory() as tmpdir:
            extracted_path = Path(tmpdir) / "extracted.md"
            report_path = Path(tmpdir) / "report.md"
            extracted_path.write_text(
                "# Chunk 1\n\n- 时间范围：09:00 - 10:00\n- [夏令营|高] A营报名开启 ——「夏令营A开始报名了」（User_1 @ 09:00）\n",
                encoding="utf-8",
            )
            generate_final_report(
                extracted_path=extracted_path,
                final_report_path=report_path,
                client=client,
                model="m",
                retries=1,
                temperature=0.2,
            )
            report = report_path.read_text(encoding="utf-8")
        self.assertIn("结构化输入的概览", report)


if __name__ == "__main__":
    unittest.main()
