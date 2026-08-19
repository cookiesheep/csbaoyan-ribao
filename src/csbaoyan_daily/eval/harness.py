"""评估脚手架：对一份日报同时跑 faithfulness + recall 两套 G-Eval。"""

from __future__ import annotations

from dataclasses import dataclass

from .geval import GEVAL_FAITHFULNESS_PROMPT, GEVAL_RECALL_PROMPT, GevalScore, geval_score


@dataclass(frozen=True)
class EvalResult:
    faithfulness: GevalScore
    recall: GevalScore

    @property
    def average(self) -> float:
        return (self.faithfulness.normalized + self.recall.normalized) / 2.0


def run_evaluation(
    client,
    model,
    source: str,
    report: str,
    *,
    retries: int = 3,
    temperature: float = 0.0,
) -> EvalResult:
    """对同一份 (来源, 日报) 跑忠实度 + 召回率两个维度。"""
    faith = geval_score(
        client, model, GEVAL_FAITHFULNESS_PROMPT, source, report,
        retries=retries, temperature=temperature, criterion_name="faithfulness",
    )
    recall = geval_score(
        client, model, GEVAL_RECALL_PROMPT, source, report,
        retries=retries, temperature=temperature, criterion_name="recall",
    )
    return EvalResult(faithfulness=faith, recall=recall)


def format_eval_result(result: EvalResult) -> str:
    lines = ["# G-Eval 评估结果", ""]
    for score in (result.faithfulness, result.recall):
        lines.append(f"- {score.criterion}: {score.raw}/5（{score.normalized:.2f}）")
    lines.append(f"- average: {result.average:.2f}")
    lines.append("")
    lines.append("## 裁判理由")
    for score in (result.faithfulness, result.recall):
        lines.append(f"### {score.criterion}")
        lines.append(score.rationale)
        lines.append("")
    return "\n".join(lines)
