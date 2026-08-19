"""评估命令：对指定日期的日报，用其匿名 transcript 作为来源，跑 G-Eval（faithfulness + recall）。

来源是 generate 写出的 internal/transcripts/<date>.txt（即脱敏后喂给 LLM 的原始记录），
日报是 pages/data/reports/<date>.md。两者路径复用 file_utils.prepare_output_paths，与 generate 对齐。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, PAGES_DIR, resolve_path
from ..domain.file_utils import prepare_output_paths, validate_report_date
from ..eval.harness import EvalResult, format_eval_result, run_evaluation
from ..infra.openai_client import create_openai_client
from .generate import default_report_date


@dataclass(frozen=True)
class EvalOptions:
    date: str | None = None
    pages_dir: Path = PAGES_DIR
    model: str | None = OPENAI_MODEL
    base_url: str | None = OPENAI_BASE_URL
    api_key: str | None = OPENAI_API_KEY
    retries: int = 3
    temperature: float = 0.0
    timeout: float = 120.0
    out_path: Path | None = None


def run_eval(options: EvalOptions) -> EvalResult:
    report_date = validate_report_date(options.date) if options.date else default_report_date()
    pages_dir = resolve_path(options.pages_dir)
    _extracted_path, report_path, transcript_path = prepare_output_paths(pages_dir, report_date)

    if not report_path.exists():
        raise FileNotFoundError(f"未找到日报：{report_path}（先用 generate 生成该日期的日报）")
    if not transcript_path.exists():
        raise FileNotFoundError(f"未找到来源 transcript：{transcript_path}")

    report = report_path.read_text(encoding="utf-8")
    source = transcript_path.read_text(encoding="utf-8")
    client = create_openai_client(options.api_key, options.base_url, options.timeout)

    logging.info("G-Eval 评估日期 %s：报告=%s 来源=%s", report_date, report_path, transcript_path)
    result = run_evaluation(
        client, options.model or OPENAI_MODEL, source, report,
        retries=options.retries, temperature=options.temperature,
    )

    text = format_eval_result(result)
    print(text)
    if options.out_path is not None:
        out_path = resolve_path(options.out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        logging.info("评估结果已写出：%s", out_path)
    return result
