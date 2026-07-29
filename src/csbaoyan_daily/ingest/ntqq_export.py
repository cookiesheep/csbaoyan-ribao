"""NTQQ 本地数据库 → 项目 QCE JSON 导出核心。

数据流：
    已解密的明文 nt_msg.db  ──SQL 查询──▶  原始消息行（含 protobuf blob）
        ──blackboxprotobuf 解析──▶  字段抽取（发送者/时间/正文/@/引用）
        ──映射──▶  QCE schema dict
        ──组装──▶  statistics + messages  ──写文件──▶  <date>T<time>.json

字段号来自 QQBackup/qq-win-db-key#83 对 130 万条真实消息的逆向研究。
跨 NTQQ 版本字段可能微调，见模块底部 CALIBRATION 注释与 ``inspect_db``。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

# ────────────────────────────────────────────────────────────────────────────
# NTQQ protobuf 字段号（顶层，置信度高；来源：QQBackup issue #83）
# ────────────────────────────────────────────────────────────────────────────
F_MSG_ID = "40001"        # varint   消息唯一 ID
F_SENDER_UID = "40020"    # bytes    发送者 NT UID（如 u_xxxxxxxx）
F_PEER_UID = "40021"      # bytes    会话对象 NT UID
F_SENDER_UIN = "40033"    # varint   发送者 QQ 号
F_TIME = "40050"          # varint   发送时间戳（epoch 秒）
F_SENDER_NICK = "40093"   # bytes    发送者昵称
F_BODY = "40800"          # message  MsgBody（内含 repeated MsgContent，字段号同为 40800）
F_REPLY = "40900"         # message  引用消息快照

# NT UID 形如 u_ 后跟 base64-ish 串
UID_RE = re.compile(r"^u_[A-Za-z0-9_-]{6,}$")
# 纯噪声串过滤
_NOISE_RE = re.compile(r"^(?:\d+|[A-Fa-f0-9]{16,}|=+$)$")
# 媒体文件名（图片/视频/语音/文件），用于把媒体消息正文规整为占位符
_MEDIA_FILE_RE = re.compile(r"^[\w.-]{6,}\.(?:jpe?g|png|gif|bmp|webp|mp4|mov|avi|mkv|mp3|m4a|aac|amr|pdf|docx?|xlsx?|zip|rar|7z)$", re.I)

# ────────────────────────────────────────────────────────────────────────────
# group_msg_table 列名（解密后字段已拆成列；列名 = 字段号）
# 经 QQ 2272735608 / NTQQ 9.9.17 真实库校准
# ────────────────────────────────────────────────────────────────────────────
COL_MSG_ID = "40001"
COL_MSG_TYPE = "40011"
COL_SENDER_UID = "40020"
COL_PEER = "40021"        # 会话/群标识（群 code）
COL_TIME = "40050"
COL_NICK = "40090"        # 群消息发送者昵称（注意：非 40093）
COL_NICK_ALT = "40093"    # 部分版本/私聊的昵称列，兜底
COL_SENDER_UIN = "40033"
COL_BODY = "40800"        # 正文 protobuf blob
COL_REPLY = "40900"       # 引用快照 blob
MSG_TYPE_TEXT = 2


@dataclass
class ParsedMessage:
    msg_id: str | None
    time_iso: str
    sender_uid: str | None
    sender_uin: str | None
    sender_nick: str | None
    text: str
    mentions: list[dict[str, str]] = field(default_factory=list)
    reply: dict[str, Any] | None = None


# ────────────────────────────────────────────────────────────────────────────
# protobuf 解码
# ────────────────────────────────────────────────────────────────────────────
def _decode_blob(blob: bytes) -> dict[str, Any]:
    """用 blackboxprotobuf 解码消息记录 blob；失败则返回空 dict。"""
    try:
        import blackboxprotobuf  # 延迟导入，非 ingest 路径无需安装
    except ImportError as exc:  # pragma: no cover - 环境提示
        raise ImportError("未安装 blackboxprotobuf，请 pip install blackboxprotobuf") from exc

    try:
        decoded, _typedef = blackboxprotobuf.decode_message(bytes(blob))
    except Exception as exc:
        logging.warning("protobuf 解码失败（%s），跳过该消息", exc)
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _g(d: Any, field_num: str) -> Any:
    return d.get(field_num) if isinstance(d, dict) else None


def _as_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            return int(value.decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            return None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        try:
            text = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    elif isinstance(value, str):
        text = value
    else:
        # blackboxprotobuf 偶尔把短字节误判成嵌套 message；不当字符串处理
        return None
    text = text.strip()
    return text or None


def _timestamp_to_iso(epoch_seconds: int | None) -> str:
    if not epoch_seconds or epoch_seconds <= 0:
        return "UNKNOWN_TIME"
    try:
        return dt.datetime.fromtimestamp(epoch_seconds).strftime("%Y-%m-%dT%H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return "UNKNOWN_TIME"


# ────────────────────────────────────────────────────────────────────────────
# 正文 / @ / 引用 抽取（body 子树递归；见底部 CALIBRATION）
# ────────────────────────────────────────────────────────────────────────────
def _walk(node: Any) -> Iterator[Any]:
    """深度优先遍历 blackboxprotobuf 解码树的所有节点。"""
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)
    else:
        yield node


def _looks_like_text(text: str) -> bool:
    if not text or text.isspace() or _NOISE_RE.match(text):
        return False
    # 需含至少一个「可读」字符（中文/字母），排除纯标点/控制
    return bool(re.search(r"[一-鿿A-Za-z]", text))


def _collect_text(body: Any, exclude: set[str] | None = None) -> str:
    """从 MsgBody 子树收集正文文本。

    NTQQ 文本元素字符串位于 MsgContent 内层（研究标注 45101–45112 段）。
    不同版本具体字段号有差异，这里采用「收集所有可读字符串叶节点」的稳妥策略，
    校准时可在 ``inspect_db`` 输出里定位到精确字段号后改用定点提取。
    ``exclude`` 排除已被识别为 @ 目标的 uid/昵称，避免污染正文。
    """
    exclude = exclude or set()
    texts: list[str] = []
    has_media = False
    for leaf in _walk(body):
        candidate = _as_str(leaf)
        if not candidate or candidate in exclude:
            continue
        if _MEDIA_FILE_RE.match(candidate):
            has_media = True
            continue
        if _looks_like_text(candidate) and not UID_RE.match(candidate):
            texts.append(candidate)
    if not texts and has_media:
        return "[媒体]"
    return "\n".join(texts).strip()


def _collect_mentions(body: Any) -> list[dict[str, str]]:
    """扫描 body 子树，提取 @ 的目标用户（uid + 昵称）。"""
    mentions: list[dict[str, str]] = []
    seen_uid: set[str] = set()

    def scan(node: Any) -> None:
        if isinstance(node, dict):
            uid = next(
                (_as_str(v) for v in node.values() if isinstance(v, (str, bytes, bytearray)) and UID_RE.match(_as_str(v) or "")),
                None,
            )
            if uid and uid not in seen_uid:
                seen_uid.add(uid)
                name = next(
                    (_as_str(v) for v in node.values() if _looks_like_text(_as_str(v) or "") and not UID_RE.match(_as_str(v) or "")),
                    None,
                )
                mentions.append({"uid": uid, "name": name or uid})
        for value in (node.values() if isinstance(node, dict) else node if isinstance(node, list) else []):
            scan(value)

    scan(body)
    return mentions


def _parse_reply(reply_node: Any) -> dict[str, Any] | None:
    if not isinstance(reply_node, dict) or not reply_node:
        return None
    sender_uid = next((_as_str(v) for v in reply_node.values() if UID_RE.match(_as_str(v) or "")), None)
    sender_nick = next((_as_str(v) for v in reply_node.values() if _looks_like_text(_as_str(v) or "")), None)
    content = _collect_text(reply_node)
    if not sender_uid and not sender_nick and not content:
        return None
    return {"senderUid": sender_uid, "senderName": sender_nick, "content": content}


# ────────────────────────────────────────────────────────────────────────────
# 单条消息：blob → ParsedMessage → QCE dict
# ────────────────────────────────────────────────────────────────────────────
def parse_record(blob: bytes, fallback_time_iso: str = "UNKNOWN_TIME") -> ParsedMessage:
    decoded = _decode_blob(blob)
    body = _g(decoded, F_BODY)
    mentions = _collect_mentions(body)
    reply = _parse_reply(_g(decoded, F_REPLY))

    # 正文排除已被识别为 @ / 引用对象的标识，避免昵称混入
    exclude: set[str] = {m["uid"] for m in mentions} | {m["name"] for m in mentions}
    if reply:
        exclude.add(reply.get("senderName") or "")
        exclude.add(reply.get("senderUid") or "")

    return ParsedMessage(
        msg_id=str(_as_int(_g(decoded, F_MSG_ID)) or ""),
        time_iso=_timestamp_to_iso(_as_int(_g(decoded, F_TIME))) or fallback_time_iso,
        sender_uid=_as_str(_g(decoded, F_SENDER_UID)),
        sender_uin=str(_as_int(_g(decoded, F_SENDER_UIN)) or ""),
        sender_nick=_as_str(_g(decoded, F_SENDER_NICK)),
        text=_collect_text(body, exclude),
        mentions=mentions,
        reply=reply,
    )


def to_qce_message(parsed: ParsedMessage) -> dict[str, Any]:
    """映射成项目 ``chat_processing`` 期望的 QCE schema。"""
    elements: list[dict[str, Any]] = []
    for mention in parsed.mentions:
        elements.append(
            {
                "type": "at",
                "data": {"uid": mention["uid"], "uin": "", "name": mention["name"]},
            }
        )

    text = parsed.text
    if parsed.reply:
        reply_data = {
            "senderName": parsed.reply.get("senderName") or "",
            "content": parsed.reply.get("content") or "",
            "referencedMessageId": "",
        }
        elements.append({"type": "reply", "data": reply_data})
        # 与 QCE 导出一致：正文前置 [回复 昵称: 片段]，``anonymize_messages`` 会改写它
        prefix = f"[回复 {reply_data['senderName']}: {reply_data['content'][:80]}]".strip()
        text = f"{prefix}\n{text}".strip() if text else prefix

    return {
        "id": parsed.msg_id,
        "time": parsed.time_iso,
        "sender": {
            "uid": parsed.sender_uid or "",
            "uin": parsed.sender_uin or "",
            "name": parsed.sender_nick or parsed.sender_uin or "Unknown",
        },
        "content": {
            "text": text,
            "mentions": [
                {"uid": m["uid"], "uin": "", "name": m["name"]} for m in parsed.mentions
            ],
            "elements": elements,
        },
    }


# ────────────────────────────────────────────────────────────────────────────
# 组装与写出
# ────────────────────────────────────────────────────────────────────────────
def build_payload(messages: list[ParsedMessage]) -> dict[str, Any]:
    """组装完整 QCE JSON：``statistics.timeRange`` 供 ``infer_report_date`` 用。"""
    times = [m.time_iso for m in messages if m.time_iso and m.time_iso != "UNKNOWN_TIME"]
    start = min(times) if times else ""
    end = max(times) if times else ""
    return {
        "statistics": {"timeRange": {"start": start, "end": end}},
        "messages": [to_qce_message(m) for m in messages],
    }


def write_export(payload: dict[str, Any], export_dir: Path, report_date: str) -> Path:
    """写出 ``<YYYY-MM-DD>T<HH-MM-SS>.json``，文件名命中 ``DATE_PATTERN``。"""
    export_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%H-%M-%S")
    out_path = export_dir / f"{report_date}T{stamp}.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return out_path


# ────────────────────────────────────────────────────────────────────────────
# SQLite 读取（schema 自适应）
# ────────────────────────────────────────────────────────────────────────────
def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"NTQQ 明文数据库不存在：{db_path}（请先用 qq_dump_db 解密）")
    # NTQQ 解密后是标准 SQLite；只读访问
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows if not r["name"].startswith("sqlite_")]


def table_columns(conn: sqlite3.Connection, table: str) -> list[dict[str, str]]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [{"name": r["name"], "type": r["type"]} for r in rows]


def find_message_blob_column(conn: sqlite3.Connection, table: str) -> str | None:
    """启发式定位存 protobuf blob 的列（BLOB 类型且名含 record/msg/content/blob）。"""
    cols = table_columns(conn, table)
    blob_cols = [c["name"] for c in cols if c["type"].upper() in ("BLOB", "") ]
    for preferred in ("msgRecord", "msg_record", "record", "content", "msgContent", "blob"):
        for name in blob_cols:
            if name == preferred:
                return name
    return blob_cols[0] if blob_cols else None


def find_message_tables(conn: sqlite3.Connection) -> list[str]:
    """启发式找消息表：优先 group_msg_table（字段已拆列），其次含 blob 的 msg 表。"""
    all_tables = list_tables(conn)
    ranked: list[str] = []
    # 第一优先：group_msg_table（真实 schema，字段拆列）
    if "group_msg_table" in all_tables:
        ranked.append("group_msg_table")
    for table in all_tables:
        lower = table.lower()
        if table in ranked:
            continue
        if ("msg" not in lower and "message" not in lower):
            continue
        cols = {c["name"] for c in table_columns(conn, table)}
        if COL_BODY in cols or find_message_blob_column(conn, table) is not None:
            ranked.append(table)
    return ranked


def _date_window(report_date: str) -> tuple[int, int]:
    """目标日期 00:00:00 ~ 次日 00:00:00 的 epoch 区间（本地时区）。"""
    day = dt.datetime.strptime(report_date, "%Y-%m-%d")
    start = int(day.timestamp())
    end = int((day + dt.timedelta(days=1)).timestamp())
    return start, end


def query_messages(
    db_path: Path,
    *,
    table: str | None = None,
    blob_column: str | None = None,
    time_column: str | None = None,
    group_filter: str | None = None,
    group_column: str | None = None,
    report_date: str | None = None,
) -> list[bytes]:
    """从明文库查目标消息的 protobuf blob 列表。

    table / blob_column 等留空时走自动发现；精确值由 ``inspect_db`` 校准后填入配置，
    以适配不同 NTQQ 版本与群/私聊分表策略。
    """
    conn = connect(db_path)
    try:
        table = table or (find_message_tables(conn)[0] if find_message_tables(conn) else None)
        if not table:
            raise RuntimeError("未在数据库中发现消息表，请用 `ingest --inspect` 查看实际表结构。")
        blob_column = blob_column or find_message_blob_column(conn, table)
        if not blob_column:
            raise RuntimeError(f"表 {table} 未找到 protobuf blob 列，请用 `ingest --inspect` 校准 --blob-column。")

        cols = {c["name"] for c in table_columns(conn, table)}
        where: list[str] = []
        params: list[Any] = []

        if group_filter:
            gcol = group_column or next((c for c in cols if "group" in c.lower() or "peer" in c.lower()), None)
            if gcol:
                where.append(f'("{gcol}" = ? OR CAST("{gcol}" AS TEXT) LIKE ?)')
                params.extend([group_filter, f"%{group_filter}%"])

        if report_date and time_column and time_column in cols:
            start, end = _date_window(report_date)
            where.append(f'"{time_column}" BETWEEN ? AND ?')
            params.extend([start, end])

        sql = f'SELECT "{blob_column}" FROM "{table}"'
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY rowid"

        rows = conn.execute(sql, params).fetchall()
        return [row[0] for row in rows if row[0]]
    finally:
        conn.close()


# ────────────────────────────────────────────────────────────────────────────
# 按列读取（group_msg_table 真实 schema；字段已拆成列）
# ────────────────────────────────────────────────────────────────────────────
def parse_group_row(row: dict[str, Any]) -> ParsedMessage:
    """从 group_msg_table 的一行（列名=字段号）构造 ParsedMessage。

    仅对 40800 正文 / 40900 引用 做 protobuf 解码，其余字段直接读列。
    """
    body_blob = row.get(COL_BODY)
    body = _decode_blob(body_blob) if body_blob else {}
    mentions = _collect_mentions(body)
    reply = _parse_reply(_decode_blob(row[COL_REPLY])) if row.get(COL_REPLY) else None

    exclude: set[str] = {m["uid"] for m in mentions} | {m["name"] for m in mentions}
    if reply:
        exclude.add(reply.get("senderName") or "")
        exclude.add(reply.get("senderUid") or "")

    return ParsedMessage(
        msg_id=str(row.get(COL_MSG_ID) or ""),
        time_iso=_timestamp_to_iso(_as_int(row.get(COL_TIME))),
        sender_uid=_as_str(row.get(COL_SENDER_UID)),
        sender_uin=str(row.get(COL_SENDER_UIN) or ""),
        sender_nick=_as_str(row.get(COL_NICK)) or _as_str(row.get(COL_NICK_ALT)),
        text=_collect_text(body, exclude),
        mentions=mentions,
        reply=reply,
    )


_GROUP_COLS = (
    COL_MSG_ID, COL_MSG_TYPE, COL_SENDER_UID, COL_PEER, COL_TIME,
    COL_NICK, COL_NICK_ALT, COL_SENDER_UIN, COL_BODY, COL_REPLY,
)


def query_group_rows(
    db_path: Path,
    *,
    table: str = "group_msg_table",
    group_code: str | None = None,
    report_date: str | None = None,
    group_column: str = COL_PEER,
    time_column: str = COL_TIME,
) -> list[ParsedMessage]:
    """从 group_msg_table 按群 + 日期查消息（按列读取）。

    解密库偶有 cell fragmentation，全表扫描大 BLOB 列可能报 malformed。
    故先取 rowid（不读 blob），再逐行读取、跳过坏行——丢失个别消息不影响日报。
    """
    conn = connect(db_path)
    try:
        existing = {c["name"] for c in table_columns(conn, table)}
        select_cols = [c for c in _GROUP_COLS if c in existing]
        if not select_cols:
            raise RuntimeError(f"表 {table} 不含已知消息字段列，请用 `ingest --inspect` 校准。")
        col_list = ", ".join(f'"{c}"' for c in select_cols)

        where: list[str] = []
        params: list[Any] = []
        if group_code and group_column in existing:
            where.append(f'"{group_column}" = ?')
            params.append(group_code)
        if report_date and time_column in existing:
            start, end = _date_window(report_date)
            where.append(f'"{time_column}" BETWEEN ? AND ?')
            params.extend([start, end])

        # 1) rowid 列表（不读 blob，规避坏页）
        sql_ids = f'SELECT rowid FROM "{table}"'
        if where:
            sql_ids += " WHERE " + " AND ".join(where)
        sql_ids += f' ORDER BY "{time_column}"' if time_column in existing else " ORDER BY rowid"
        rowids = [r[0] for r in conn.execute(sql_ids, params).fetchall()]

        # 2) 逐行读取，跳过坏行
        parsed: list[ParsedMessage] = []
        skipped = 0
        for rid in rowids:
            try:
                row = conn.execute(
                    f'SELECT {col_list} FROM "{table}" WHERE rowid = ?', (rid,)
                ).fetchone()
            except sqlite3.DatabaseError as exc:
                logging.warning("跳过坏行 rowid=%s：%s", rid, exc)
                skipped += 1
                continue
            if row:
                parsed.append(parse_group_row(dict(row)))
        if skipped:
            logging.warning("共跳过 %d 条无法读取的消息（解密库 cell 瑕疵，不影响日报）", skipped)
        return parsed
    finally:
        conn.close()


def inspect_db(db_path: Path, *, sample_table: str | None = None, sample_limit: int = 1) -> str:
    """生成人类可读的库结构报告 + 样本消息解码，供一次性字段校准使用。"""
    conn = connect(db_path)
    lines: list[str] = [f"# NTQQ DB 体检报告：{db_path}"]
    try:
        tables = list_tables(conn)
        lines.append(f"\n## 表（{len(tables)} 个）: {', '.join(tables)}")

        msg_tables = find_message_tables(conn)
        lines.append(f"\n## 疑似消息表: {', '.join(msg_tables) or '(未自动发现)'}")

        target_tables = ([sample_table] if sample_table else msg_tables[:2]) or tables[:2]
        for table in target_tables:
            lines.append(f"\n## 表 `{table}` 字段:")
            for col in table_columns(conn, table):
                lines.append(f"  - {col['name']} : {col['type'] or '(无类型)'}")
            blob_col = find_message_blob_column(conn, table)
            lines.append(f"  → 推断 blob 列: {blob_col or '(无)'}")

            if blob_col:
                rows = conn.execute(f'SELECT "{blob_col}" FROM "{table}" LIMIT {int(sample_limit)}').fetchall()
                for i, row in enumerate(rows, 1):
                    if not row[0]:
                        continue
                    lines.append(f"\n### 样本消息 {i}（原始解码树）:")
                    decoded = _decode_blob(row[0])
                    lines.append(json.dumps(decoded, ensure_ascii=False, indent=2, default=str)[:4000])
                    parsed = parse_record(row[0])
                    lines.append(f"\n### 样本消息 {i}（抽取结果）:")
                    lines.append(json.dumps(parsed.__dict__, ensure_ascii=False, indent=2, default=str))
        return "\n".join(lines)
    finally:
        conn.close()


# ────────────────────────────────────────────────────────────────────────────
# CALIBRATION（一次性校准说明）
# ────────────────────────────────────────────────────────────────────────────
# 顶层字段（发送者/时间/昵称）置信度高，通常无需调整。
# 正文 / @ / 引用 采用递归收集策略，跨版本基本可用；若某版本抽取异常，
# 在你本机跑 `python -m csbaoyan_daily.cli ingest --inspect --db-path <db>`，
# 把「样本消息原始解码树」发回来，我把定点字段号补进 _collect_text / _collect_mentions。
