"""管线付印统计：每期一份「付印工单」（只存计数，不存任何消息内容），供前端编辑部透明度展示。

写入 pages/data/stats/<date>.json —— 在 publish 的 pathspec（pages/data）内，随站点自动发布。
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class PipelineStats:
    raw_messages: int          # 导出的原始消息数
    kept_messages: int         # 去噪后实际进入 LLM 的消息数
    dropped_total: int         # 去噪丢弃总数（= raw - kept）
    dropped_emoji_only: int    # 纯 emoji
    dropped_noise_token: int   # 纯应答语气词
    dropped_flood: int         # 同人连续刷屏
    dropped_non_text: int      # 脱敏阶段丢弃（无正文/系统消息/撤回），不进噪声过滤
    speakers: int              # 发言者数（脱敏后去重）
    chunks: int                # 分块数
    items: int                 # 中间抽取要点条数
    quotes: int                # 抽取中保留的原话引用数
    structured: bool           # 是否引用式结构化抽取（1b）
    model: str
    generated_at: str
    eval: dict[str, Any] | None = None  # 可选：G-Eval {faithfulness, recall, average}


def count_extracted_items(extracted_text: str) -> tuple[int, int]:
    """从中间抽取 markdown 数要点条数与原话引用数。

    要点：列表行（结构化模式行首 `- [`，兼容普通 `- `），排除每块固有的「时间范围」头行。
    引用：「 与 “ 的出现次数（结构化用「」，成报引用用“”）。
    """
    items = sum(
        1
        for line in extracted_text.splitlines()
        if line.lstrip().startswith("- ") and not line.lstrip().startswith("- 时间范围")
    )
    quotes = extracted_text.count("「") + extracted_text.count("“")
    return items, quotes


def write_pipeline_stats(pages_dir: Path, report_date: str, stats: PipelineStats) -> Path:
    stats_dir = pages_dir / "data" / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    path = stats_dir / f"{report_date}.json"
    path.write_text(json.dumps(asdict(stats), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def attach_eval_to_stats(pages_dir: Path, report_date: str, eval_result) -> Path:
    """把 G-Eval 结果（EvalResult）写进该期 stats 的 eval 字段。"""
    stats_dir = pages_dir / "data" / "stats"
    path = stats_dir / f"{report_date}.json"
    if not path.exists():
        raise FileNotFoundError(f"未找到 {path}，无法附加评估结果（先生成日报）。")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["eval"] = {
        "faithfulness": eval_result.faithfulness.raw,
        "recall": eval_result.recall.raw,
        "average": round(eval_result.average, 4),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def rebuild_stats_summary(pages_dir: Path) -> Path:
    """聚合全部期数统计 → pages/data/stats/summary.json（首页/印房页一次拉取）。"""
    stats_dir = pages_dir / "data" / "stats"
    totals = dict.fromkeys(("raw_messages", "kept_messages", "dropped_total", "items", "quotes"), 0)
    editions = 0
    latest_eval: dict[str, Any] | None = None
    if stats_dir.is_dir():
        for path in sorted(stats_dir.glob("????-??-??.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            editions += 1
            for key in totals:
                totals[key] += int(data.get(key, 0) or 0)
            if isinstance(data.get("eval"), dict):
                latest_eval = {"date": path.stem, **data["eval"]}
    summary: dict[str, Any] = {
        "editions": editions,
        **{f"total_{key}": value for key, value in totals.items()},
        "latest_eval": latest_eval,
        "rebuilt_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    stats_dir.mkdir(parents=True, exist_ok=True)
    summary_path = stats_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary_path
