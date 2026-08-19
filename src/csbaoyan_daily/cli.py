from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .app.broadcast import broadcast_report
from .app.eval import EvalOptions, run_eval
from .app.factcheck import FactcheckOptions, run_factcheck
from .app.generate import GenerateOptions, run_generate_report
from .app.ingest import IngestOptions, run_ingest
from .app.pipeline import PipelineOptions, run_pipeline
from .app.publish import PublishOptions, run_publish
from .app.verify import format_release_issues, run_release_check
from .config import (
    EXPORT_DIR,
    GROUP_CODE,
    NTQQ_DB_PATH,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    PAGES_DIR,
    XHS_EXPORT,
)
from .domain.file_utils import validate_report_date


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout,
    )


def add_generate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--export-dir", type=Path, default=EXPORT_DIR, help="Directory containing exported QQ chat JSON files.")
    parser.add_argument("--pages-dir", type=Path, default=PAGES_DIR, help="Pages directory that stores site data.")
    parser.add_argument("--date", "--report-date", dest="date", type=validate_report_date, help="Target report date in YYYY-MM-DD format.")
    parser.add_argument("--model", default=OPENAI_MODEL, help="OpenAI-compatible model name.")
    parser.add_argument("--chunk-max-chars", type=int, default=30000, help="Maximum character count per chunk.")
    parser.add_argument("--chunk-max-messages", type=int, default=600, help="Maximum message count per chunk.")
    parser.add_argument("--chunk-overlap-messages", type=int, default=30, help="Number of overlapping messages between adjacent chunks.")
    parser.add_argument("--retries", type=int, default=3, help="Maximum retry count for failed LLM calls.")
    parser.add_argument("--timeout", type=float, default=120.0, help="LLM request timeout in seconds.")
    parser.add_argument("--final-timeout", type=float, default=300.0, help="Timeout in seconds for the final aggregation request.")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature for the LLM.")
    parser.add_argument("--max-workers", type=int, default=4, help="Worker count for chunk extraction.")
    parser.add_argument("--base-url", default=OPENAI_BASE_URL, help="Optional custom base URL for an OpenAI-compatible API.")
    parser.add_argument("--api-key", default=OPENAI_API_KEY, help="Optional API key for the OpenAI-compatible API.")
    parser.add_argument(
        "--noise-filter",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="启用规则噪声预过滤（默认开启，仅丢弃纯emoji/应答语气词/同人刷屏；用 --no-noise-filter 关闭）。",
    )
    parser.add_argument(
        "--structured-extraction",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="启用引用式结构化抽取（quote+speaker+time+category+confidence，JSON 输出 + 温度降温重试）。默认开启（已真实验证），--no-structured-extraction 可退回纯文本模式。",
    )


def add_ingest_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db-path", type=Path, default=NTQQ_DB_PATH, help="已解密的 NTQQ 明文 SQLite 数据库路径（qq_dump_db 输出）。")
    parser.add_argument("--export-dir", type=Path, default=EXPORT_DIR, help="导出 QCE JSON 的输出目录（与 generate 的 --export-dir 一致）。")
    parser.add_argument("--date", "--report-date", dest="date", type=validate_report_date, help="目标日期 YYYY-MM-DD，默认昨天。")
    parser.add_argument("--group", default=GROUP_CODE, help="目标群过滤值（群号/群名片段，按库实际列校准）。")
    parser.add_argument("--table", help="消息表名（留空自动发现；用 --inspect 校准）。")
    parser.add_argument("--blob-column", help="存 protobuf blob 的列名（留空自动发现）。")
    parser.add_argument("--time-column", help="存时间戳的列名（用于库内日期过滤）。")
    parser.add_argument("--group-column", help="存群标识的列名（用于库内群过滤）。")
    parser.add_argument("--inspect", action="store_true", help="体检模式：只打印库结构 + 样本消息解码，不导出。用于一次性字段校准。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CS Baoyan chat daily report tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate", help="Generate a daily report from a chat export.")
    add_generate_arguments(generate_parser)

    eval_parser = subparsers.add_parser("eval", help="G-Eval 评估：对日报打 faithfulness + recall 分（裁判模型宜与生成模型不同厂商）。")
    eval_parser.add_argument("--date", "--report-date", dest="date", type=validate_report_date, help="Target report date in YYYY-MM-DD format. Defaults to yesterday.")
    eval_parser.add_argument("--pages-dir", type=Path, default=PAGES_DIR, help="Pages directory that stores site data.")
    eval_parser.add_argument("--model", default=OPENAI_MODEL, help="OpenAI-compatible model name for the judge.")
    eval_parser.add_argument("--base-url", default=OPENAI_BASE_URL, help="Optional custom base URL for the judge API.")
    eval_parser.add_argument("--api-key", default=OPENAI_API_KEY, help="Optional API key for the judge API.")
    eval_parser.add_argument("--retries", type=int, default=3, help="Maximum retry count for failed judge calls.")
    eval_parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature for the judge (0 = reproducible).")
    eval_parser.add_argument("--timeout", type=float, default=120.0, help="Judge request timeout in seconds.")
    eval_parser.add_argument("--out", type=Path, help="Optional path to write the evaluation result markdown.")

    factcheck_parser = subparsers.add_parser("factcheck", help="事实核查：NLI 预过滤（可选）+ 非生成器 LLM 裁判，逐条核验日报声明。")
    factcheck_parser.add_argument("--date", "--report-date", dest="date", type=validate_report_date, help="Target report date in YYYY-MM-DD format. Defaults to yesterday.")
    factcheck_parser.add_argument("--pages-dir", type=Path, default=PAGES_DIR, help="Pages directory that stores site data.")
    factcheck_parser.add_argument("--model", default=OPENAI_MODEL, help="OpenAI-compatible model name for the judge.")
    factcheck_parser.add_argument("--base-url", default=OPENAI_BASE_URL, help="Optional custom base URL for the judge API.")
    factcheck_parser.add_argument("--api-key", default=OPENAI_API_KEY, help="Optional API key for the judge API.")
    factcheck_parser.add_argument("--retries", type=int, default=3, help="Maximum retry count for failed judge calls.")
    factcheck_parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature for the judge (0 = reproducible).")
    factcheck_parser.add_argument("--timeout", type=float, default=120.0, help="Judge request timeout in seconds.")
    factcheck_parser.add_argument("--nli", action=argparse.BooleanOptionalAction, default=True, help="启用本地 NLI 预过滤（需 torch/transformers，未装则自动降级）。")
    factcheck_parser.add_argument("--confidence-threshold", type=float, default=0.7, help="NLI 高置信短路判定阈值。")
    factcheck_parser.add_argument("--out", type=Path, help="Optional path to write the factcheck result markdown.")

    verify_parser = subparsers.add_parser("verify", help="Run release checks against generated reports.")
    verify_parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Repository root path.")
    verify_parser.add_argument("--pages-dir", type=Path, default=PAGES_DIR, help="Pages directory that stores site data.")

    broadcast_parser = subparsers.add_parser("broadcast", help="Send the latest report overview to Telegram.")
    broadcast_parser.add_argument("--date", "--report-date", dest="date", type=validate_report_date, help="Report date in YYYY-MM-DD format.")
    broadcast_parser.add_argument("--pages-dir", type=Path, default=PAGES_DIR, help="Pages directory that stores site data.")

    publish_parser = subparsers.add_parser("publish", help="Commit and optionally push pages/data changes.")
    publish_parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Repository root path.")
    publish_parser.add_argument("--skip-push", action="store_true", help="Commit locally without pushing.")

    ingest_parser = subparsers.add_parser("ingest", help="从本地 NTQQ 明文数据库导出 QCE JSON（路线 B，不封号）。")
    add_ingest_arguments(ingest_parser)

    pipeline_parser = subparsers.add_parser("pipeline", help="Run generate, verify and publish in order.")
    pipeline_parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Repository root path.")
    add_generate_arguments(pipeline_parser)
    pipeline_parser.add_argument("--skip-generate", action="store_true", help="Skip report generation.")
    pipeline_parser.add_argument("--skip-release-check", action="store_true", help="Skip release checks.")
    pipeline_parser.add_argument("--skip-commit", action="store_true", help="Skip all git operations and Telegram broadcast.")
    pipeline_parser.add_argument("--skip-push", action="store_true", help="Commit locally without pushing or broadcasting.")
    pipeline_parser.add_argument("--skip-telegram", action="store_true", help="Skip Telegram broadcast after a successful push.")
    pipeline_parser.add_argument(
        "--xhs-export",
        action="store_true",
        help="Generate a structured Xiaohongshu source JSON after report generation.",
    )
    pipeline_parser.add_argument(
        "--with-eval",
        action="store_true",
        help="出报后自动跑 G-Eval（faithfulness + recall，每期 2 次 LLM 调用），结果写入该期付印工单 stats JSON。",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "generate":
            run_generate_report(
                GenerateOptions(
                    export_dir=args.export_dir,
                    pages_dir=args.pages_dir,
                    date=args.date,
                    model=args.model,
                    chunk_max_chars=args.chunk_max_chars,
                    chunk_max_messages=args.chunk_max_messages,
                    chunk_overlap_messages=args.chunk_overlap_messages,
                    retries=args.retries,
                    timeout=args.timeout,
                    final_timeout=args.final_timeout,
                    temperature=args.temperature,
                    max_workers=args.max_workers,
                    base_url=args.base_url,
                    api_key=args.api_key,
                    noise_filter=args.noise_filter,
                    structured_extraction=args.structured_extraction,
                )
            )
            return 0

        if args.command == "eval":
            run_eval(
                EvalOptions(
                    date=args.date,
                    pages_dir=args.pages_dir,
                    model=args.model,
                    base_url=args.base_url,
                    api_key=args.api_key,
                    retries=args.retries,
                    temperature=args.temperature,
                    timeout=args.timeout,
                    out_path=args.out,
                )
            )
            return 0

        if args.command == "factcheck":
            run_factcheck(
                FactcheckOptions(
                    date=args.date,
                    pages_dir=args.pages_dir,
                    model=args.model,
                    base_url=args.base_url,
                    api_key=args.api_key,
                    retries=args.retries,
                    temperature=args.temperature,
                    timeout=args.timeout,
                    use_nli=args.nli,
                    confidence_threshold=args.confidence_threshold,
                    out_path=args.out,
                )
            )
            return 0

        if args.command == "verify":
            issues = run_release_check(repo_root=args.repo_root, pages_dir=args.pages_dir)
            if issues:
                print(format_release_issues(issues))
                return 1
            print("Release check passed.")
            return 0

        if args.command == "broadcast":
            broadcast_report(report_date=args.date, pages_dir=args.pages_dir)
            return 0

        if args.command == "publish":
            run_publish(PublishOptions(repo_root=args.repo_root, push=not args.skip_push))
            return 0

        if args.command == "ingest":
            run_ingest(
                IngestOptions(
                    db_path=args.db_path,
                    export_dir=args.export_dir,
                    date=args.date,
                    group=args.group,
                    table=args.table,
                    blob_column=args.blob_column,
                    time_column=args.time_column,
                    group_column=args.group_column,
                    inspect=args.inspect,
                )
            )
            return 0

        if args.command == "pipeline":
            run_pipeline(
                PipelineOptions(
                    repo_root=args.repo_root,
                    export_dir=args.export_dir,
                    pages_dir=args.pages_dir,
                    date=args.date,
                    model=args.model,
                    chunk_max_chars=args.chunk_max_chars,
                    chunk_max_messages=args.chunk_max_messages,
                    chunk_overlap_messages=args.chunk_overlap_messages,
                    retries=args.retries,
                    timeout=args.timeout,
                    final_timeout=args.final_timeout,
                    temperature=args.temperature,
                    max_workers=args.max_workers,
                    base_url=args.base_url,
                    api_key=args.api_key,
                    noise_filter=args.noise_filter,
                    structured_extraction=args.structured_extraction,
                    skip_generate=args.skip_generate,
                    skip_release_check=args.skip_release_check,
                    skip_commit=args.skip_commit,
                    skip_push=args.skip_push,
                    skip_telegram=args.skip_telegram,
                    xhs_export=args.xhs_export or XHS_EXPORT,
                    with_eval=args.with_eval,
                )
            )
            return 0
    except Exception as exc:
        logging.exception("%s failed: %s", args.command, exc)
        return 1

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
