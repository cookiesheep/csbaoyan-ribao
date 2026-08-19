"""LLM 事实核查裁判（宜与生成模型不同厂商，规避自偏好）。"""

from __future__ import annotations

import re
from dataclasses import dataclass

JUDGE_SYSTEM_PROMPT = "你是严谨的中文事实核查员。只依据给定的来源聊天记录判断声明是否成立，绝不引入外部知识或臆测。"

JUDGE_INSTRUCTION = """判断下面这条声明相对来源是否成立，只可能从三类中选一：
- supported：声明能被来源直接或合理推断支持
- contradicted：来源信息与声明明显冲突
- not_enough_info：来源中找不到足够依据
输出格式：第一行写标签（supported / contradicted / not_enough_info），第二行可选写一个 0-1 的置信度小数，第三行起写一句理由。"""

_LABELS = ("supported", "contradicted", "not_enough_info")
# 仅匹配带小数点的 0-1 数，避免误吃「8 月 15 日」这类整数
_CONF_RE = re.compile(r"([01]\.\d+|0?\.\d+)")


@dataclass(frozen=True)
class JudgeVerdict:
    label: str
    confidence: float
    rationale: str


def parse_judge(content: str) -> JudgeVerdict:
    """从裁判回复解析标签 + 置信度。无标签默认 not_enough_info；无小数置信默认 1.0。"""
    text = (content or "").strip()
    low = text.lower()
    label = next((lab for lab in _LABELS if lab in low), "not_enough_info")
    m = _CONF_RE.search(text)
    confidence = float(m.group(1)) if m else 1.0
    return JudgeVerdict(label=label, confidence=confidence, rationale=text)


def _call(client, model, source, claim, retries, temperature) -> str:
    user = (
        f"【来源】聊天记录：\n{source}\n\n"
        f"【待核查声明】\n{claim}\n\n"
        f"{JUDGE_INSTRUCTION}"
    )
    last_exc: Exception | None = None
    for _ in range(max(1, retries)):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
            )
            return resp.choices[0].message.content
        except Exception as exc:  # noqa: BLE001 - 重试，最终抛出
            last_exc = exc
    raise RuntimeError(f"事实核查裁判调用失败：{last_exc}")


def judge_claim(client, model, source, claim, *, retries: int = 3, temperature: float = 0.0) -> JudgeVerdict:
    return parse_judge(_call(client, model, source, claim, retries, temperature))
