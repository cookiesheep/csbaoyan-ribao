from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TOKEN_BOUNDARY_CLASS = r"A-Za-z0-9_\u4e00-\u9fff"
PERSON_TITLE_SUFFIXES = (
    "老师",
    "学长",
    "学姐",
    "同学",
    "导师",
    "教授",
    "院士",
    "师兄",
    "师姐",
    "主任",
    "老板",
)
PERSON_TITLE_PATTERN = "|".join(re.escape(title) for title in PERSON_TITLE_SUFFIXES)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL_PATTERN = re.compile(
    r"(?i)\b(?:https?://|www\.)[^\s]+|(?<!@)\b(?:[A-Za-z0-9-]+\.)+(?:com|cn|edu|org|net|io|ai|cc)(?:/[^\s]*)?"
)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
CONTACT_ID_PATTERN = re.compile(r"(?i)\b(?:qq|vx|wechat|weixin|微信)[:： ]*[A-Za-z0-9_-]{5,}\b")
PUBLIC_ALIAS_RULES = ()


# ---- Stage 1a: 规则噪声预过滤（借鉴 SXP-Simon 清洗 + teledigest NFKC/unicode 过滤）----
# Emoji 与零宽/格式控制符：用于从保留文本中剥离，并识别纯表情消息。
_EMOJI_RANGES: tuple[tuple[int, int], ...] = (
    (0x1F300, 0x1F5FF),  # 杂项符号与象形文字
    (0x1F600, 0x1F64F),  # 表情
    (0x1F680, 0x1F6FF),  # 交通与地图
    (0x1F700, 0x1F77F),
    (0x1F780, 0x1F7FF),
    (0x1F800, 0x1F8FF),
    (0x1F900, 0x1F9FF),  # 补充符号
    (0x1FA00, 0x1FA6F),
    (0x1FA70, 0x1FAFF),
    (0x2600, 0x26FF),    # 杂项符号
    (0x2700, 0x27BF),    # 装饰符号（Dingbats）
    (0x2300, 0x23FF),    # 杂项技术符号（含 ⌚⌛）
    (0xFE0E, 0xFE0F),    # 变体选择符
    (0x200B, 0x200D),    # 零宽空格 / 非连接符 / 连接符
)
_EMOJI_EXTRA: frozenset[int] = frozenset(
    {0x203C, 0x2049, 0x20E3, 0x2122, 0x2139, 0x2B1B, 0x2B1C, 0x2B50, 0x2B55}
)

# 纯应答/语气词，几乎不携带日报价值（保守集合，可在配置里调）。
NOISE_TOKENS: frozenset[str] = frozenset(
    {
        "嗯", "嗯嗯", "嗯哼", "哦", "哦哦", "啊", "额", "em", "emmm", "emmmmm",
        "哈", "哈哈", "哈哈哈哈", "ok", "OK", "Ok", "okk", "okay",
        "收到", "好的", "好", "是", "对",
    }
)


def should_register_suffix_alias(suffix: str) -> bool:
    if len(suffix) < 2:
        return False
    if re.fullmatch(r"[\u4e00-\u9fff]+", suffix):
        return len(suffix) <= 3
    return True


@dataclass
class AnonymizedMessage:
    time: str
    speaker: str
    text: str

    def to_line(self) -> str:
        return f"[{self.time}] {self.speaker}: {self.text}"


@dataclass
class ChatChunk:
    index: int
    messages: list[AnonymizedMessage]

    @property
    def text(self) -> str:
        return "\n".join(message.to_line() for message in self.messages)

    @property
    def start_time(self) -> str:
        return self.messages[0].time

    @property
    def end_time(self) -> str:
        return self.messages[-1].time


class AliasResolver:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.alias_by_canonical: dict[str, str] = {}
        self.token_to_canonical: dict[str, str] = {}
        self._pre_register(messages)
        self.global_direct_map, self.global_direct_pattern = self._build_global_direct_pattern()
        self.global_digit_map, self.global_digit_pattern = self._build_global_digit_pattern()

    def _pre_register(self, messages: list[dict[str, Any]]) -> None:
        for message in messages:
            sender = message.get("sender") or {}
            self.register(sender.get("uid"), sender.get("uin"), sender.get("name"))

            content = message.get("content") or {}
            mentions = content.get("mentions") or []
            for mention in mentions:
                self.register(mention.get("uid"), mention.get("uin"), mention.get("name"))

            for element in content.get("elements") or []:
                if element.get("type") == "at":
                    data = element.get("data") or {}
                    self.register(data.get("uid"), data.get("uin"), data.get("name"))

    def _clean_token(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _get_public_alias(self, uid: Any = None, uin: Any = None) -> str | None:
        uid_text = self._clean_token(uid)
        uin_text = self._clean_token(uin)
        for rule in PUBLIC_ALIAS_RULES:
            if uid_text and uid_text == rule.get("uid"):
                return str(rule["alias"])
            if uin_text and uin_text == rule.get("uin"):
                return str(rule["alias"])
        return None

    def register(self, uid: Any = None, uin: Any = None, name: Any = None) -> str | None:
        uid_text = self._clean_token(uid)
        uin_text = self._clean_token(uin)
        name_text = self._clean_token(name)
        canonical = uid_text or uin_text or (f"name:{name_text}" if name_text else None)
        if not canonical:
            return None

        alias = self.alias_by_canonical.get(canonical)
        if alias is None:
            alias = self._get_public_alias(uid_text, uin_text) or f"User_{len(self.alias_by_canonical) + 1}"
            self.alias_by_canonical[canonical] = alias

        if uid_text:
            self.token_to_canonical[uid_text] = canonical
        if uin_text:
            self.token_to_canonical[uin_text] = canonical
        if name_text and len(name_text) >= 2 and name_text not in self.token_to_canonical:
            self.token_to_canonical[name_text] = canonical
            if "-" in name_text:
                suffix = name_text.rsplit("-", 1)[-1].strip()
                if should_register_suffix_alias(suffix) and suffix not in self.token_to_canonical:
                    self.token_to_canonical[suffix] = canonical
        return alias

    def resolve(self, uid: Any = None, uin: Any = None, name: Any = None) -> str | None:
        for raw in (uid, uin, name):
            token = self._clean_token(raw)
            if not token:
                continue
            canonical = self.token_to_canonical.get(token)
            if canonical:
                return self.alias_by_canonical[canonical]
        return self.register(uid, uin, name)

    def _is_safe_global_token(self, token: str) -> bool:
        if len(token) < 2:
            return False
        if token.startswith("u_") or token.isdigit():
            return True
        if re.search(r"[\u4e00-\u9fff]", token):
            return True
        return any(char in token for char in "-（）()[]/ ")

    def _build_global_direct_pattern(self) -> tuple[dict[str, str], re.Pattern[str] | None]:
        token_alias: dict[str, str] = {}
        for token, canonical in self.token_to_canonical.items():
            if token.isdigit() or not self._is_safe_global_token(token):
                continue
            token_alias.setdefault(token, self.alias_by_canonical[canonical])

        if not token_alias:
            return token_alias, None

        escaped_tokens = sorted((re.escape(token) for token in token_alias), key=len, reverse=True)
        pattern = re.compile(
            rf"(?<![{TOKEN_BOUNDARY_CLASS}])"
            rf"(?:{'|'.join(escaped_tokens)})"
            rf"(?:(?=(?:{PERSON_TITLE_PATTERN}))|(?![{TOKEN_BOUNDARY_CLASS}]))"
        )
        return token_alias, pattern

    def _build_global_digit_pattern(self) -> tuple[dict[str, str], re.Pattern[str] | None]:
        digit_alias: dict[str, str] = {}
        for token, canonical in self.token_to_canonical.items():
            if token.isdigit():
                digit_alias.setdefault(token, self.alias_by_canonical[canonical])

        if not digit_alias:
            return digit_alias, None

        escaped_tokens = sorted((re.escape(token) for token in digit_alias), key=len, reverse=True)
        pattern = re.compile(rf"(?<!\d)(?:{'|'.join(escaped_tokens)})(?!\d)")
        return digit_alias, pattern

    def sanitize_global(self, text: str) -> str:
        result = text
        if self.global_direct_pattern is not None:
            result = self.global_direct_pattern.sub(lambda match: self.global_direct_map[match.group(0)], result)
        if self.global_digit_pattern is not None:
            result = self.global_digit_pattern.sub(lambda match: self.global_digit_map[match.group(0)], result)
        return result


def normalize_media_placeholders(text: str) -> str:
    text = re.sub(r"\[图片:[^\]]+\]", "[图片]", text)
    text = re.sub(r"\[语音:[^\]]+\]", "[语音]", text)
    text = re.sub(r"\[视频:[^\]]+\]", "[视频]", text)
    text = re.sub(r"\[文件:[^\]]+\]", "[文件]", text)
    return text


def redact_sensitive_text(text: str) -> str:
    text = EMAIL_PATTERN.sub("[邮箱]", text)
    text = URL_PATTERN.sub("[链接]", text)
    text = PHONE_PATTERN.sub("[手机号]", text)
    text = CONTACT_ID_PATTERN.sub("[联系方式]", text)
    return text


def sanitize_text_core(raw_text: str, message: dict[str, Any], resolver: AliasResolver) -> str:
    text = raw_text.strip()
    if not text:
        return ""

    local_replacements = build_message_replacements(message, resolver)
    text = normalize_media_placeholders(text)
    text = redact_sensitive_text(text)
    text = resolver.sanitize_global(text)
    text = apply_token_replacements(text, local_replacements)
    text = re.sub(r"@(?:[^\n@\]]{0,96}?)(User_\d+)", r"@\1", text)
    return text


def extract_message_body_text(message: dict[str, Any]) -> str:
    content = message.get("content") or {}
    raw_text = str(content.get("text") or "").strip()
    if not raw_text:
        return ""

    if raw_text.startswith("[回复 "):
        parts = raw_text.split("\n", 1)
        if len(parts) == 2:
            return parts[1].strip()

    return raw_text


def sanitize_reply_excerpt(
    reply_data: dict[str, Any],
    resolver: AliasResolver,
    message_index: dict[str, dict[str, Any]],
) -> str:
    referenced_message_id = str(reply_data.get("referencedMessageId") or "").strip()
    referenced_message = message_index.get(referenced_message_id)

    if referenced_message:
        excerpt_source = extract_message_body_text(referenced_message)
        excerpt_message = referenced_message
    else:
        excerpt_source = str(reply_data.get("content") or "").strip()
        excerpt_message = {"content": {"text": excerpt_source, "mentions": [], "elements": []}}

    excerpt = sanitize_text_core(excerpt_source, excerpt_message, resolver)
    excerpt = re.sub(r"\s+", " ", excerpt)
    return excerpt[:80]


def sanitize_message_text(
    raw_text: str,
    message: dict[str, Any],
    resolver: AliasResolver,
    message_index: dict[str, dict[str, Any]],
) -> str:
    text = raw_text.strip()
    if not text:
        return ""

    if text.startswith("[合并转发:"):
        return "[合并转发]"

    text = normalize_media_placeholders(text)

    content = message.get("content") or {}
    for element in content.get("elements") or []:
        if element.get("type") != "reply":
            continue
        data = element.get("data") or {}
        alias = resolver.resolve(name=data.get("senderName"))
        sender_name = str(data.get("senderName") or "").strip()
        if not alias or not sender_name:
            continue
        reply_prefix = f"[回复 {sender_name}: {data.get('content', '')}]"
        excerpt = sanitize_reply_excerpt(data, resolver, message_index)
        sanitized_prefix = f"[回复 {alias}: {excerpt}]"
        text = text.replace(reply_prefix, sanitized_prefix)

    text = sanitize_text_core(text, message, resolver)
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_message_replacements(message: dict[str, Any], resolver: AliasResolver) -> dict[str, str]:
    replacements: dict[str, str] = {}

    def register(uid: Any = None, uin: Any = None, name: Any = None) -> None:
        alias = resolver.resolve(uid, uin, name)
        if not alias:
            return

        for token in (uid, uin, name):
            if token is None:
                continue
            text = str(token).strip()
            if not text:
                continue
            replacements[text] = alias

            if isinstance(token, str) and "-" in text:
                suffix = text.rsplit("-", 1)[-1].strip()
                if should_register_suffix_alias(suffix):
                    replacements[suffix] = alias

    sender = message.get("sender") or {}
    register(sender.get("uid"), sender.get("uin"), sender.get("name"))

    content = message.get("content") or {}
    for mention in content.get("mentions") or []:
        register(mention.get("uid"), mention.get("uin"), mention.get("name"))

    for element in content.get("elements") or []:
        data = element.get("data") or {}
        if element.get("type") == "at":
            register(data.get("uid"), data.get("uin"), data.get("name"))
        elif element.get("type") == "reply":
            register(name=data.get("senderName"))

    return replacements


def apply_token_replacements(text: str, replacements: dict[str, str]) -> str:
    result = text
    for token, alias in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        if not token or token == alias:
            continue
        result = replace_token(result, token, alias)
    return result


def replace_token(text: str, token: str, alias: str) -> str:
    if token.isdigit():
        return re.sub(rf"(?<!\d){re.escape(token)}(?!\d)", alias, text)

    return re.sub(
        rf"(?<![{TOKEN_BOUNDARY_CLASS}])"
        rf"{re.escape(token)}"
        rf"(?:(?=(?:{PERSON_TITLE_PATTERN}))|(?![{TOKEN_BOUNDARY_CLASS}]))",
        alias,
        text,
    )


def anonymize_messages(messages: list[dict[str, Any]]) -> list[AnonymizedMessage]:
    resolver = AliasResolver(messages)
    message_index = {
        str(message.get("id") or "").strip(): message
        for message in messages
        if str(message.get("id") or "").strip()
    }
    anonymized: list[AnonymizedMessage] = []

    for message in messages:
        if message.get("system") or message.get("recalled"):
            continue

        sender = message.get("sender") or {}
        alias = resolver.resolve(sender.get("uid"), sender.get("uin"), sender.get("name"))
        if not alias:
            continue

        content = message.get("content") or {}
        raw_text = str(content.get("text") or "").strip()
        if not raw_text:
            continue

        text = sanitize_message_text(raw_text, message, resolver, message_index)
        if not text:
            continue

        message_time = str(message.get("time") or "").strip() or "UNKNOWN_TIME"
        anonymized.append(AnonymizedMessage(time=message_time, speaker=alias, text=text))

    if not anonymized:
        raise ValueError("没有可用于摘要的有效聊天消息。")

    return anonymized


def _is_emoji_char(ch: str) -> bool:
    code_point = ord(ch)
    for low, high in _EMOJI_RANGES:
        if low <= code_point <= high:
            return True
    return code_point in _EMOJI_EXTRA


def clean_message_text(text: str) -> str:
    """NFKC 归一化、剥离 emoji/零宽控制符、折叠空白。"""
    normalized = unicodedata.normalize("NFKC", text)
    stripped = "".join(ch for ch in normalized if not _is_emoji_char(ch))
    return re.sub(r"\s+", " ", stripped).strip()


@dataclass(frozen=True)
class NoiseFilterStats:
    input_count: int
    output_count: int
    dropped_empty: int
    dropped_emoji_only: int
    dropped_noise_token: int
    dropped_flood: int


def filter_noise_messages(
    messages: list[AnonymizedMessage],
    *,
    drop_noise_tokens: bool = True,
    drop_flood: bool = True,
    flood_threshold: int = 3,
) -> tuple[list[AnonymizedMessage], NoiseFilterStats]:
    """对匿名化后的消息做规则噪声过滤。

    仅丢弃：纯 emoji / 纯应答语气词 / 同人连续刷屏；保留消息会同步清洗内联 emoji。
    返回过滤后列表与统计；列表为空时由调用方决定是否回退。
    """
    dropped_empty = 0
    dropped_emoji_only = 0
    dropped_noise_token = 0
    dropped_flood = 0

    cleaned: list[tuple[AnonymizedMessage, str]] = []
    for message in messages:
        had_text = bool(message.text and message.text.strip())
        text = clean_message_text(message.text)
        if not text:
            if had_text:
                dropped_emoji_only += 1
            else:
                dropped_empty += 1
            continue
        if drop_noise_tokens and text in NOISE_TOKENS:
            dropped_noise_token += 1
            continue
        cleaned.append((message, text))

    if drop_flood and flood_threshold > 1 and cleaned:
        deduped: list[tuple[AnonymizedMessage, str]] = []
        run_length = 0
        previous_key: tuple[str, str] | None = None
        for message, text in cleaned:
            key = (message.speaker, text)
            if key == previous_key:
                run_length += 1
                if run_length >= flood_threshold:
                    dropped_flood += 1
                    continue
            else:
                previous_key = key
                run_length = 1
            deduped.append((message, text))
        cleaned = deduped

    result = [
        AnonymizedMessage(time=message.time, speaker=message.speaker, text=text)
        for message, text in cleaned
    ]
    stats = NoiseFilterStats(
        input_count=len(messages),
        output_count=len(result),
        dropped_empty=dropped_empty,
        dropped_emoji_only=dropped_emoji_only,
        dropped_noise_token=dropped_noise_token,
        dropped_flood=dropped_flood,
    )
    return result, stats


def chunk_messages(
    messages: list[AnonymizedMessage],
    max_chars: int,
    max_messages: int,
    overlap_messages: int = 0,
) -> list[ChatChunk]:
    if max_chars <= 0 or max_messages <= 0:
        raise ValueError("Chunk 限制参数必须为正整数。")
    if overlap_messages < 0:
        raise ValueError("Chunk 重叠消息数不能为负数。")
    if overlap_messages >= max_messages:
        raise ValueError("Chunk 重叠消息数必须小于每个 Chunk 的最大消息条数。")

    chunks: list[ChatChunk] = []
    start_index = 0
    while start_index < len(messages):
        current: list[AnonymizedMessage] = []
        current_chars = 0
        end_index = start_index

        while end_index < len(messages):
            message = messages[end_index]
            line_length = len(message.to_line()) + 1
            if current and (current_chars + line_length > max_chars or len(current) >= max_messages):
                break

            current.append(message)
            current_chars += line_length
            end_index += 1

        chunks.append(ChatChunk(index=len(chunks) + 1, messages=current))

        if end_index >= len(messages):
            break

        safe_overlap = min(overlap_messages, len(current) - 1)
        start_index = end_index - safe_overlap

    return chunks


def write_anonymized_transcript(messages: list[AnonymizedMessage], output_path: Path) -> None:
    content = "\n".join(message.to_line() for message in messages) + "\n"
    output_path.write_text(content, encoding="utf-8")
