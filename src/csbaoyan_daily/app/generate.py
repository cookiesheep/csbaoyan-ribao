from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import EXPORT_DIR, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, PAGES_DIR, resolve_path
from ..domain.chat_processing import anonymize_messages, chunk_messages, filter_noise_messages, write_anonymized_transcript
from ..domain.file_utils import (
    extract_messages,
    get_json_file_by_date,
    infer_report_date,
    load_chat_export,
    prepare_output_paths,
    validate_report_date,
    write_reports_manifest,
)
from ..domain.report_generation import extract_all_chunks, extract_all_chunks_structured, generate_final_report
from ..domain.stats import (
    PipelineStats,
    count_extracted_items,
    rebuild_stats_summary,
    write_pipeline_stats,
)
from ..infra.openai_client import create_openai_client


@dataclass(frozen=True)
class GenerateOptions:
    export_dir: Path = EXPORT_DIR
    pages_dir: Path = PAGES_DIR
    date: str | None = None
    model: str | None = OPENAI_MODEL
    chunk_max_chars: int = 30000
    chunk_max_messages: int = 600
    chunk_overlap_messages: int = 30
    retries: int = 3
    timeout: float = 120.0
    final_timeout: float = 300.0
    temperature: float = 0.2
    max_workers: int = 4
    base_url: str | None = OPENAI_BASE_URL
    api_key: str | None = OPENAI_API_KEY
    noise_filter: bool = True
    structured_extraction: bool = True


@dataclass(frozen=True)
class GenerateArtifacts:
    report_date: str
    export_file: Path
    extracted_path: Path
    report_path: Path
    transcript_path: Path
    manifest_count: int
    message_count: int
    chunk_count: int
    stats_path: Path | None = None  # 付印工单路径（generate 正常流程总会写出）


def default_report_date() -> str:
    return (dt.date.today() - dt.timedelta(days=1)).strftime("%Y-%m-%d")


def run_generate_report(options: GenerateOptions) -> GenerateArtifacts:
    target_date = validate_report_date(options.date) if options.date else default_report_date()
    export_dir = resolve_path(options.export_dir)
    pages_dir = resolve_path(options.pages_dir)

    export_file = get_json_file_by_date(export_dir, target_date)
    payload = load_chat_export(export_file)
    messages = extract_messages(payload)
    raw_message_count = len(messages)
    anonymized_messages = anonymize_messages(messages)
    dropped_non_text = raw_message_count - len(anonymized_messages)  # 无正文/系统/撤回，未进噪声过滤
    dropped_emoji_only = dropped_noise_token = dropped_flood = 0
    if options.noise_filter:
        filtered_messages, noise_stats = filter_noise_messages(anonymized_messages)
        logging.info(
            "规则噪声过滤：%s → %s 条（丢弃：纯emoji %s / 噪声词 %s / 刷屏 %s）",
            noise_stats.input_count,
            noise_stats.output_count,
            noise_stats.dropped_emoji_only,
            noise_stats.dropped_noise_token,
            noise_stats.dropped_flood,
        )
        if filtered_messages:
            anonymized_messages = filtered_messages
        else:
            logging.warning("规则过滤后剩余 0 条消息，回退到过滤前列表以避免空报告。")
        dropped_emoji_only, dropped_noise_token, dropped_flood = (
            noise_stats.dropped_emoji_only, noise_stats.dropped_noise_token, noise_stats.dropped_flood,
        )
    chunks = chunk_messages(
        anonymized_messages,
        max_chars=options.chunk_max_chars,
        max_messages=options.chunk_max_messages,
        overlap_messages=options.chunk_overlap_messages,
    )

    inferred_report_date = infer_report_date(payload, export_file)
    report_date = validate_report_date(options.date) if options.date else inferred_report_date
    extracted_path, report_path, transcript_path = prepare_output_paths(pages_dir, report_date)
    write_anonymized_transcript(anonymized_messages, transcript_path)

    extraction_client = create_openai_client(options.api_key, options.base_url, options.timeout)
    final_client = create_openai_client(options.api_key, options.base_url, options.final_timeout)

    logging.info("使用日期 %s 的导出文件：%s", target_date, export_file)
    if inferred_report_date != target_date:
        logging.warning("目标日期为 %s，但导出内容推断日期为 %s，将按目标日期输出。", target_date, inferred_report_date)
    logging.info("脱敏后消息数：%s，Chunk 数：%s", len(anonymized_messages), len(chunks))
    logging.info("LLM 超时设置：分块提取 %ss，最终汇总 %ss", options.timeout, options.final_timeout)

    if options.structured_extraction:
        extract_all_chunks_structured(
            chunks=chunks,
            extracted_path=extracted_path,
            client=extraction_client,
            model=options.model or OPENAI_MODEL,
            retries=options.retries,
            temperature=options.temperature,
            max_workers=options.max_workers,
        )
    else:
        extract_all_chunks(
            chunks=chunks,
            extracted_path=extracted_path,
            client=extraction_client,
            model=options.model or OPENAI_MODEL,
            retries=options.retries,
            temperature=options.temperature,
            max_workers=options.max_workers,
        )

    generate_final_report(
        extracted_path=extracted_path,
        final_report_path=report_path,
        client=final_client,
        model=options.model or OPENAI_MODEL,
        retries=options.retries,
        temperature=options.temperature,
    )

    manifest = write_reports_manifest(pages_dir)

    extracted_text = extracted_path.read_text(encoding="utf-8")
    item_count, quote_count = count_extracted_items(extracted_text)
    stats = PipelineStats(
        raw_messages=raw_message_count,
        kept_messages=len(anonymized_messages),
        dropped_total=raw_message_count - len(anonymized_messages),
        dropped_emoji_only=dropped_emoji_only,
        dropped_noise_token=dropped_noise_token,
        dropped_flood=dropped_flood,
        dropped_non_text=dropped_non_text,
        speakers=len({m.speaker for m in anonymized_messages}),
        chunks=len(chunks),
        items=item_count,
        quotes=quote_count,
        structured=options.structured_extraction,
        model=options.model or OPENAI_MODEL,
        generated_at=dt.datetime.now().isoformat(timespec="seconds"),
    )
    stats_path = write_pipeline_stats(pages_dir, report_date, stats)
    rebuild_stats_summary(pages_dir)
    logging.info("付印工单已写出：%s（去噪 −%s / 要点 %s / 引用 %s）", stats_path, stats.dropped_total, stats.items, stats.quotes)

    logging.info("中间提取结果：%s", extracted_path)
    logging.info("脱敏聊天记录：%s", transcript_path)
    logging.info("最终日报：%s", report_path)
    logging.info("站点索引已刷新，共 %s 篇日报", len(manifest))

    return GenerateArtifacts(
        report_date=report_date,
        export_file=export_file,
        extracted_path=extracted_path,
        report_path=report_path,
        transcript_path=transcript_path,
        manifest_count=len(manifest),
        message_count=len(anonymized_messages),
        chunk_count=len(chunks),
        stats_path=stats_path,
    )

