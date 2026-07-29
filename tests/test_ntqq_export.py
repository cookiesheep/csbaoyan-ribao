"""ntqq_export 单元测试（阶段一验证）。

用合成的 protobuf blob + 内存 SQLite，验证：
  1. 字段抽取（发送者/时间/昵称/正文/@/引用）
  2. QCE schema 映射
  3. query_messages → parse → build_payload → write_export 全链路
  4. 产物能被现有 anonymize_messages 无差别消费（下游零改动证明）
  5. 输出文件名命中 file_utils.DATE_PATTERN，可被 get_json_file_by_date 找到

既支持 pytest，也可直接 `python tests/test_ntqq_export.py` 运行。
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

# 让 `python tests/test_ntqq_export.py` 也能 import 到 src
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from csbaoyan_daily.domain.chat_processing import anonymize_messages  # noqa: E402
from csbaoyan_daily.domain.file_utils import get_json_file_by_date  # noqa: E402
from csbaoyan_daily.ingest import ntqq_export  # noqa: E402


# ── 极简 protobuf 编码（仅用于构造测试夹具）────────────────────────────────
def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            break
    return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _f_varint(field: int, n: int) -> bytes:
    return _tag(field, 0) + _varint(n)


def _f_bytes(field: int, b: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(b)) + b


def _f_str(field: int, s: str) -> bytes:
    return _f_bytes(field, s.encode("utf-8"))


def _f_msg(field: int, inner: bytes) -> bytes:
    return _f_bytes(field, inner)


# ── 字段号（与 ntqq_export 保持一致）──────────────────────────────────────
F_MSG_ID, F_SENDER_UID, F_SENDER_UIN, F_TIME, F_SENDER_NICK = "40001", "40020", "40033", "40050", "40093"
F_BODY, F_REPLY = "40800", "40900"


def _build_record(*, msg_id, uid, uin, nick, epoch, text, at=None, reply=None) -> bytes:
    body_content = b""
    if text:
        body_content += _f_str(1, text)
    if at:
        body_content += _f_msg(2, _f_str(1, at["uid"]) + _f_str(2, at["name"]))
    msgbody = _f_msg(40800, body_content)

    record = (
        _f_varint(int(F_MSG_ID), msg_id)
        + _f_str(int(F_SENDER_UID), uid)
        + _f_varint(int(F_SENDER_UIN), uin)
        + _f_varint(int(F_TIME), epoch)
        + _f_str(int(F_SENDER_NICK), nick)
        + _f_msg(int(F_BODY), msgbody)
    )
    if reply:
        record += _f_msg(int(F_REPLY), _f_str(1, reply["uid"]) + _f_str(2, reply["name"]) + _f_str(3, reply["content"]))
    return record


GROUP_CODE = "987654321"
TARGET_DATE = "2026-07-28"
TARGET_EPOCH = int(dt.datetime(2026, 7, 28, 10, 0, 0).timestamp())
OTHER_EPOCH = int(dt.datetime(2026, 7, 27, 23, 0, 0).timestamp())  # 前一天，应被日期过滤掉


def _make_db(tmp: Path) -> Path:
    """构造内存→临时文件的 NTQQ 风格 SQLite（group_msg_table）。"""
    db_path = tmp / "nt_msg.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE group_msg_table ("
        "id INTEGER PRIMARY KEY, chatPeer TEXT, time INTEGER, msgRecord BLOB)"
    )
    rows = [
        (1, GROUP_CODE, TARGET_EPOCH, _build_record(
            msg_id=1001, uid="u_sender1", uin=123456, nick="张三-cs", epoch=TARGET_EPOCH,
            text="@李四-teacher 上交夏令营截止了吗？邮箱 zs@sjtu.edu.cn",
            at={"uid": "u_mention1", "name": "李四-teacher"},
            reply={"uid": "u_replied", "name": "王五-admin", "content": "明天截止"})),
        (2, GROUP_CODE, TARGET_EPOCH + 300, _build_record(
            msg_id=1002, uid="u_mention1", uin=654321, nick="李四-teacher", epoch=TARGET_EPOCH + 300,
            text="[图片:abc.png] 已截止 http://apply.sjtu.edu.cn")),
        (3, GROUP_CODE, OTHER_EPOCH, _build_record(  # 非目标日期
            msg_id=1003, uid="u_sender1", uin=123456, nick="张三-cs", epoch=OTHER_EPOCH,
            text="这是前一天的消息")),
    ]
    conn.executemany("INSERT INTO group_msg_table VALUES (?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return db_path


def test_parse_record_extracts_fields():
    blob = _build_record(
        msg_id=1001, uid="u_sender1", uin=123456, nick="张三-cs", epoch=TARGET_EPOCH,
        text="上交夏令营截止了吗？",
        at={"uid": "u_mention1", "name": "李四-teacher"},
        reply={"uid": "u_replied", "name": "王五-admin", "content": "明天截止"},
    )
    parsed = ntqq_export.parse_record(blob)
    assert parsed.msg_id == "1001"
    assert parsed.sender_uin == "123456"
    assert parsed.sender_uid == "u_sender1"
    assert parsed.sender_nick == "张三-cs"
    assert parsed.time_iso.startswith("2026-07-28")
    assert "上交夏令营截止了吗" in parsed.text
    assert "李四-teacher" not in parsed.text  # @ 昵称不应混入正文
    assert any(m["uid"] == "u_mention1" for m in parsed.mentions)
    assert parsed.reply is not None


def test_full_pipeline_and_downstream_compat():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        db_path = _make_db(tmp)
        export_dir = tmp / "exports"

        blobs = ntqq_export.query_messages(
            db_path, table="group_msg_table", blob_column="msgRecord",
            time_column="time", group_filter=GROUP_CODE, group_column="chatPeer",
            report_date=TARGET_DATE,
        )
        # 命中目标日期 + 目标群的 2 条
        assert len(blobs) == 2

        parsed = [ntqq_export.parse_record(b) for b in blobs]
        parsed = [m for m in parsed if m.time_iso.startswith(TARGET_DATE)]
        assert len(parsed) == 2

        payload = ntqq_export.build_payload(parsed)
        out_path = ntqq_export.write_export(payload, export_dir, TARGET_DATE)

        # 文件名命中 DATE_PATTERN，可被现有逻辑按日期检索
        found = get_json_file_by_date(export_dir, TARGET_DATE)
        assert found == out_path

        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert "messages" in data and len(data["messages"]) == 2
        # 时间范围用于 infer_report_date
        assert data["statistics"]["timeRange"]["end"].startswith(TARGET_DATE)

        # ★ 关键：产物能直接喂给现有 anonymize_messages，下游零改动
        anon = anonymize_messages(data["messages"])
        assert len(anon) == 2
        # 邮箱 / 链接应被脱敏
        joined = "\n".join(m.to_line() for m in anon)
        assert "zs@sjtu.edu.cn" not in joined
        assert "apply.sjtu.edu.cn" not in joined
        # 发送者应被别名化，真实昵称不残留
        assert "张三-cs" not in joined and "李四-teacher" not in joined


def test_inspect_db_runs():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = _make_db(Path(tmpdir))
        report = ntqq_export.inspect_db(db_path)
        assert "group_msg_table" in report
        assert "样本消息" in report


if __name__ == "__main__":
    test_parse_record_extracts_fields()
    test_full_pipeline_and_downstream_compat()
    test_inspect_db_runs()
    print("✅ 全部测试通过")
