"""两层事实核查：本地 NLI 预过滤（可选）+ 非生成器 LLM 裁判。

策略：NLI 高置信蕴含 → 直接判 supported；高置信矛盾 → contradicted；其余交 LLM 裁判。
NLI 不可用时全部声明交 LLM 裁判。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .claims import Claim, extract_claims
from .judge import judge_claim


@dataclass(frozen=True)
class ClaimVerdict:
    claim: Claim
    label: str         # supported / contradicted / not_enough_info
    confidence: float
    rationale: str
    source: str        # nli / judge


@dataclass(frozen=True)
class FactcheckResult:
    verdicts: list[ClaimVerdict]

    @property
    def counts(self) -> dict[str, int]:
        return dict(Counter(v.label for v in self.verdicts))

    @property
    def support_rate(self) -> float:
        total = len(self.verdicts)
        if total == 0:
            return 0.0
        return self.counts.get("supported", 0) / total


def run_factcheck(
    client,
    model,
    source: str,
    report: str,
    *,
    nli=None,
    retries: int = 3,
    temperature: float = 0.0,
    confidence_threshold: float = 0.7,
) -> FactcheckResult:
    claims = extract_claims(report)
    use_nli = nli is not None and nli.available()
    verdicts: list[ClaimVerdict] = []
    for claim in claims:
        if use_nli:
            res = nli.score(source, claim.text)
            if res.label == "entailment" and res.confidence >= confidence_threshold:
                verdicts.append(ClaimVerdict(claim, "supported", res.confidence, res.label, "nli"))
                continue
            if res.label == "contradiction" and res.confidence >= confidence_threshold:
                verdicts.append(ClaimVerdict(claim, "contradicted", res.confidence, res.label, "nli"))
                continue
        jv = judge_claim(client, model, source, claim.text, retries=retries, temperature=temperature)
        verdicts.append(ClaimVerdict(claim, jv.label, jv.confidence, jv.rationale, "judge"))
    return FactcheckResult(verdicts)


def format_factcheck_result(result: FactcheckResult) -> str:
    counts = result.counts
    lines = [
        "# 事实核查结果",
        "",
        f"- 声明总数：{len(result.verdicts)}",
        f"- supported：{counts.get('supported', 0)}",
        f"- contradicted：{counts.get('contradicted', 0)}",
        f"- not_enough_info：{counts.get('not_enough_info', 0)}",
        f"- 支持率：{result.support_rate:.2f}",
        "",
        "## 逐条核验",
    ]
    for v in result.verdicts:
        lines.append(f"- [{v.label}|{v.source}|{v.confidence:.2f}] {v.claim.text}")
        if v.source == "judge" and v.rationale:
            first = v.rationale.splitlines()[0]
            lines.append(f"  - 理由：{first}")
    return "\n".join(lines)
