from __future__ import annotations

import datetime as dt
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain.file_utils import load_chat_export
from .generate import GenerateArtifacts


SCHEMA_VERSION = "csbaoyan-xhs-export/v1"
DISCLAIMER_TEXT = "内容为群聊历史复盘，非实时招生通知；具体安排请以院校最新官方信息为准。"
PROHIBITED_CONTENT = [
    "external_links",
    "qr_codes",
    "watermarks",
    "personal_contact",
    "raw_user_identifiers",
]


@dataclass(frozen=True)
class XhsExportOptions:
    artifacts: GenerateArtifacts
    pages_dir: Path
    repo_root: Path
    enabled: bool


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _extract_group_display(payload: dict[str, Any]) -> str:
    for key in ("group_display", "groupDisplay"):
        value = _text(payload.get(key))
        if value and not re.search(r"\d{5,}", value):
            return value
    return ""


def _extract_time_range(payload: dict[str, Any]) -> dict[str, str]:
    statistics = _mapping(payload.get("statistics"))
    time_range = _mapping(statistics.get("timeRange"))
    return {
        "start": _text(time_range.get("start")),
        "end": _text(time_range.get("end")),
    }


def _resolve_from_repo(path: Path, repo_root: Path) -> Path:
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


def run_xhs_export(options: XhsExportOptions) -> Path | None:
    if not options.enabled:
        return None

    repo_root = options.repo_root.resolve()
    pages_dir = _resolve_from_repo(options.pages_dir, repo_root)
    report_path = _resolve_from_repo(options.artifacts.report_path, repo_root)
    export_file = _resolve_from_repo(options.artifacts.export_file, repo_root)

    report_markdown = report_path.read_text(encoding="utf-8")
    if not report_markdown.strip():
        raise ValueError(f"日报正文为空，无法生成小红书导出：{report_path}")

    payload = load_chat_export(export_file)
    relative_report_path = report_path.relative_to(repo_root).as_posix()
    envelope = {
        "schema": SCHEMA_VERSION,
        "date": options.artifacts.report_date,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": {
            "group_display": _extract_group_display(payload),
            "message_count": options.artifacts.message_count,
            "chunk_count": options.artifacts.chunk_count,
            "time_range": _extract_time_range(payload),
        },
        "report_markdown": report_markdown,
        "report_path": relative_report_path,
        "compliance": {
            "must_include_disclaimer": True,
            "disclaimer_text": DISCLAIMER_TEXT,
            "prohibited": PROHIBITED_CONTENT,
        },
    }

    output_dir = pages_dir / "data" / "xhs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{options.artifacts.report_date}.json"
    output_path.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logging.info("小红书导出 JSON 已写入：%s", output_path)
    return output_path
