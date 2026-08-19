"""G-Eval 单维度打分。

G-Eval（Liu et al. 2023）的可复现简化变体：固定的 CoT 评分细则 → 裁判模型输出 1-5
整数（附简短理由）→ 解析最后一个整数 → 归一化到 [0,1]。温度恒为 0 保证可复现。

注意：裁判模型宜与生成模型不同厂商以规避自偏好；本模块不强制，由调用方传入合适的
client/model（见 app/eval.py 与文档）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

GEVAL_FAITHFULNESS_PROMPT = """你将评估一份「保研群日报」是否忠实于原始聊天记录（来源）。
忠实度衡量：日报里的每一条信息是否都能在来源里找到依据，有无编造、夸大或张冠李戴。
评分（1-5 整数）：
1 = 严重失实，大量编造
2 = 多处信息无来源依据
3 = 部分信息无来源依据
4 = 基本忠实，偶有小瑕疵
5 = 完全忠实，所有信息都有来源依据
请先给 1-2 句依据，最后一行只输出一个 1-5 的整数。"""

GEVAL_RECALL_PROMPT = """你将评估一份「保研群日报」对原始聊天记录（来源）关键信息的覆盖程度。
召回率衡量：来源里的重要信息（夏令营、导师、院校、经验、时间节点等）是否被日报捕获，有无重要遗漏。
评分（1-5 整数）：
1 = 几乎遗漏全部重要信息
2 = 遗漏多数重要信息
3 = 约捕获一半重要信息
4 = 覆盖大多数重要信息
5 = 全面覆盖，无明显遗漏
请先给 1-2 句说明，最后一行只输出一个 1-5 的整数。"""

GEVAL_SYSTEM_PROMPT = "你是严格的中文日报质量评审。只依据给定的来源做判断，绝不引入外部知识。"

# 匹配独立的 1-5 整数；取最后一个，对应「最后一行输出整数」的指令
_SCORE_RE = re.compile(r"(?<!\d)([1-5])(?!\d)")


@dataclass(frozen=True)
class GevalScore:
    criterion: str       # faithfulness / recall / ...
    raw: int             # 1-5
    normalized: float    # 0.0-1.0
    rationale: str       # 裁判给出的原始回复


def parse_score(response: str) -> tuple[int, str]:
    """从裁判回复中解析 1-5 整数（取最后一个匹配），返回 (整数, 原始回复)。"""
    matches = _SCORE_RE.findall(response or "")
    if not matches:
        raise ValueError(f"裁判回复中未找到 1-5 整数：{(response or '')[:80]!r}")
    return int(matches[-1]), (response or "").strip()


def _call_llm(client, model, system_prompt, user_prompt, retries, temperature) -> str:
    last_exc: Exception | None = None
    for _ in range(max(1, retries)):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
            )
            return resp.choices[0].message.content
        except Exception as exc:  # noqa: BLE001 - 重试，最终抛出
            last_exc = exc
    raise RuntimeError(f"G-Eval 裁判调用失败：{last_exc}")


def geval_score(
    client,
    model,
    criterion_prompt: str,
    source: str,
    report: str,
    *,
    retries: int = 3,
    temperature: float = 0.0,
    criterion_name: str = "criterion",
) -> GevalScore:
    """对单个评估维度打分。"""
    user_prompt = (
        f"【来源】原始聊天记录：\n{source}\n\n"
        f"【待评估】日报：\n{report}\n\n"
        f"请按以下细则评分：\n{criterion_prompt}"
    )
    content = _call_llm(client, model, GEVAL_SYSTEM_PROMPT, user_prompt, retries, temperature)
    raw, rationale = parse_score(content)
    return GevalScore(criterion=criterion_name, raw=raw, normalized=raw / 5.0, rationale=rationale)
