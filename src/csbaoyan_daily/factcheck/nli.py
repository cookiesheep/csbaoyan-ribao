"""本地 NLI 预过滤（可选）：用中文 NLI 模型对 (来源, 声明) 打蕴含/矛盾/中立。

torch/transformers 是重依赖（约 2GB），按需安装；未安装时 available() 返回 False，
factcheck pipeline 自动跳过本层、全部声明交给 LLM 裁判（优雅降级）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NliResult:
    label: str         # entailment / contradiction / neutral
    confidence: float  # 0.0-1.0


class NliScorer:
    """NLI 预过滤接口。"""

    def available(self) -> bool:
        raise NotImplementedError

    def score(self, premise: str, hypothesis: str) -> NliResult:
        raise NotImplementedError


class ErlangshenNliScorer(NliScorer):
    """Erlangshen-Roberta-110M-NLI（中文 NLI）。懒加载 torch/transformers。"""

    def __init__(self, model_name: str = "IDEA-CCNL/Erlangshen-Roberta-110M-NLI") -> None:
        self._model_name = model_name
        self._pipe = None

    def available(self) -> bool:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            return False
        return True

    def _ensure(self):
        if self._pipe is None:
            from transformers import pipeline

            self._pipe = pipeline(
                "text-classification",
                model=self._model_name,
                function_to_apply="softmax",
                top_k=3,
            )
        return self._pipe

    @staticmethod
    def _normalize(raw_label: str) -> str:
        low = (raw_label or "").lower().replace("label_", "").strip()
        for key in ("entailment", "contradiction", "neutral"):
            if key in low:
                return key
        return "neutral"

    def score(self, premise: str, hypothesis: str) -> NliResult:
        pipe = self._ensure()
        out = pipe({"text": premise, "text_pair": hypothesis})
        if isinstance(out, list):
            best = max(out, key=lambda d: d.get("score", 0.0))
        else:
            best = out
        return NliResult(self._normalize(best.get("label", "")), float(best.get("score", 0.0)))
