"""事实核查命令：对指定日期日报做两层核验（NLI 预过滤可选 + LLM 裁判）。

裁判宜用与生成模型不同的厂商（通过 --base-url/--api-key/--model 覆盖）以规避自偏好。
NLI 预过滤需 torch/transformers，未安装则自动降级为全量 LLM 裁判。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, PAGES_DIR, resolve_path
from ..domain.file_utils import prepare_output_paths, validate_report_date
from ..factcheck.nli import ErlangshenNliScorer
from ..factcheck.pipeline import FactcheckResult, format_factcheck_result
from ..factcheck.pipeline import run_factcheck as run_factcheck_pipeline
from ..infra.openai_client import create_openai_client
from .generate import default_report_date


@dataclass(frozen=True)
class FactcheckOptions:
    date: str | None = None
    pages_dir: Path = PAGES_DIR
    model: str | None = OPENAI_MODEL
    base_url: str | None = OPENAI_BASE_URL
    api_key: str | None = OPENAI_API_KEY
    retries: int = 3
    temperature: float = 0.0
    timeout: float = 120.0
    use_nli: bool = True
    confidence_threshold: float = 0.7
    out_path: Path | None = None


def run_factcheck(options: FactcheckOptions) -> FactcheckResult:
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

    nli = ErlangshenNliScorer() if options.use_nli else None
    if nli is not None and not nli.available():
        logging.warning(
            "NLI 预过滤不可用（未安装 torch/transformers），全部声明交给 LLM 裁判。"
            "安装可启用本地预过滤：pip install torch transformers"
        )
        nli = None  # 优雅降级

    logging.info("事实核查日期 %s：报告=%s 来源=%s NLI=%s", report_date, report_path, transcript_path, "on" if nli else "off")
    result = run_factcheck_pipeline(
        client, options.model or OPENAI_MODEL, source, report,
        nli=nli, retries=options.retries, temperature=options.temperature,
        confidence_threshold=options.confidence_threshold,
    )

    text = format_factcheck_result(result)
    print(text)
    if options.out_path is not None:
        out_path = resolve_path(options.out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        logging.info("核查结果已写出：%s", out_path)
    return result
