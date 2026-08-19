from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from csbaoyan_daily.domain.chat_processing import (
    AnonymizedMessage,
    clean_message_text,
    filter_noise_messages,
)


def _msg(text: str, speaker: str = "User_1", time: str = "10:00") -> AnonymizedMessage:
    return AnonymizedMessage(time=time, speaker=speaker, text=text)


class CleanMessageTextTests(unittest.TestCase):
    def test_strips_emoji(self) -> None:
        self.assertEqual(clean_message_text("你好🎉😀👍"), "你好")

    def test_nfkc_normalizes_fullwidth(self) -> None:
        self.assertEqual(clean_message_text("ＡＢ１２"), "AB12")

    def test_collapses_whitespace(self) -> None:
        self.assertEqual(clean_message_text("a   b\n  c"), "a b c")

    def test_keeps_chinese_digits_and_arrows(self) -> None:
        # 箭头（U+2190-21FF）不在剥离集合里，应保留；CJK 与 ASCII 数字保留。
        self.assertEqual(clean_message_text("夏令营6月30日截止"), "夏令营6月30日截止")
        self.assertEqual(clean_message_text("A→B"), "A→B")


class FilterNoiseMessagesTests(unittest.TestCase):
    def test_pure_emoji_dropped_as_emoji_only(self) -> None:
        messages = [_msg("🎉😀👍"), _msg("有内容的消息")]
        result, stats = filter_noise_messages(messages)
        self.assertEqual([m.text for m in result], ["有内容的消息"])
        self.assertEqual(stats.dropped_emoji_only, 1)
        self.assertEqual(stats.input_count, 2)
        self.assertEqual(stats.output_count, 1)

    def test_noise_token_dropped(self) -> None:
        messages = [_msg("嗯"), _msg("好的"), _msg("收到"), _msg("实质内容")]
        result, stats = filter_noise_messages(messages)
        self.assertEqual([m.text for m in result], ["实质内容"])
        self.assertEqual(stats.dropped_noise_token, 3)

    def test_substantive_message_keeps_and_cleans_inline_emoji(self) -> None:
        messages = [_msg("夏令营开始报名啦🎉🎉")]
        result, stats = filter_noise_messages(messages)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "夏令营开始报名啦")
        self.assertEqual(result[0].speaker, "User_1")
        self.assertEqual(stats.output_count, 1)

    def test_flood_dedup_same_speaker(self) -> None:
        messages = [_msg("某老师组很累", "User_1")] * 4
        result, stats = filter_noise_messages(messages)
        # threshold=3：保留前 2 条，从第 3 条起丢弃（允许误触的双发）。
        self.assertEqual(len(result), 2)
        self.assertEqual(stats.dropped_flood, 2)

    def test_flood_not_deduped_across_speakers(self) -> None:
        messages = [
            _msg("某老师组很累", "User_1"),
            _msg("某老师组很累", "User_2"),
            _msg("某老师组很累", "User_1"),
        ]
        result, stats = filter_noise_messages(messages)
        self.assertEqual(len(result), 3)
        self.assertEqual(stats.dropped_flood, 0)

    def test_two_identical_consecutive_kept(self) -> None:
        messages = [_msg("正常消息", "User_1")] * 2
        result, stats = filter_noise_messages(messages)
        self.assertEqual(len(result), 2)
        self.assertEqual(stats.dropped_flood, 0)

    def test_all_dropped_returns_empty(self) -> None:
        messages = [_msg("嗯"), _msg("哦")]
        result, stats = filter_noise_messages(messages)
        self.assertEqual(result, [])
        self.assertEqual(stats.output_count, 0)
        self.assertEqual(stats.dropped_noise_token, 2)

    def test_disable_noise_token_and_flood(self) -> None:
        messages = [_msg("嗯"), _msg("重复", "User_1"), _msg("重复", "User_1")]
        result, stats = filter_noise_messages(messages, drop_noise_tokens=False, drop_flood=False)
        self.assertEqual(len(result), 3)
        self.assertEqual(stats.dropped_noise_token, 0)
        self.assertEqual(stats.dropped_flood, 0)


if __name__ == "__main__":
    unittest.main()
