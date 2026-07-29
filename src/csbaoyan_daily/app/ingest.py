"""ingest 应用层：编排「查库 → 解析 → 映射 → 写出 QCE JSON」。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import EXPORT_DIR, GROUP_CODE, NTQQ_DB_PATH, resolve_path
from ..domain.file_utils import validate_report_date
from ..ingest import ntqq_export
from ..ingest.ntqq_export import COL_BODY, COL_PEER, COL_TIME


@dataclass(frozen=True)
class IngestOptions:
    db_path: Path = NTQQ_DB_PATH
    export_dir: Path = EXPORT_DIR
    date: str | None = None
    group: str | None = GROUP_CODE
    table: str | None = None
    blob_column: str | None = None
    time_column: str | None = None
    group_column: str | None = None
    inspect: bool = False


def run_ingest(options: IngestOptions) -> str:
    """执行 ingest：体检模式返回报告文本；导出模式返回输出文件路径。"""
    if options.inspect:
        report = ntqq_export.inspect_db(resolve_path(options.db_path))
        print(report)
        return report

    report_date = validate_report_date(options.date) if options.date else _yesterday()
    db_path = resolve_path(options.db_path)
    export_dir = resolve_path(options.export_dir)
    table = options.table or "group_msg_table"

    logging.info("ingest：db=%s table=%s group=%s date=%s", db_path, table, options.group, report_date)

    # 有 40800 列 → 按列读取（group_msg_table 真实 schema）；否则回退 blob 模式
    conn = ntqq_export.connect(db_path)
    try:
        col_names = {c["name"] for c in ntqq_export.table_columns(conn, table)}
    finally:
        conn.close()

    if COL_BODY in col_names:
        parsed = ntqq_export.query_group_rows(
            db_path,
            table=table,
            group_code=options.group,
            report_date=report_date,
            group_column=options.group_column or COL_PEER,
            time_column=options.time_column or COL_TIME,
        )
    else:
        blobs = ntqq_export.query_messages(
            db_path,
            table=table,
            blob_column=options.blob_column,
            time_column=options.time_column,
            group_filter=options.group,
            group_column=options.group_column,
            report_date=report_date if options.time_column else None,
        )
        parsed = [ntqq_export.parse_record(blob) for blob in blobs]
        parsed = [m for m in parsed if not options.date or m.time_iso.startswith(report_date)]

    logging.info("日期 %s 过滤后消息：%d 条", report_date, len(parsed))

    if not parsed:
        raise RuntimeError(
            f"未在 {db_path}（{table}）中找到 {report_date} 的消息。"
            "请先用 `ingest --inspect` 确认表名/群过滤值（--group）是否正确。"
        )

    payload = ntqq_export.build_payload(parsed)
    out_path = ntqq_export.write_export(payload, export_dir, report_date)
    logging.info("已写出 QCE 导出文件：%s（%d 条消息）", out_path, len(parsed))
    return str(out_path)


def _yesterday() -> str:
    import datetime as dt

    return (dt.date.today() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
