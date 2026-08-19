"""从日报 markdown 中抽取原子声明，供事实核验逐条判断。"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 中文 + 英文句末标点切句
_SENT_SPLIT = re.compile(r"[。！？；!?;]")
_BULLET = re.compile(r"^[-*+]\s+")
_NUM_PREFIX = re.compile(r"^\d+[.、)]\s+")
_BRACKET_TAG = re.compile(r"^\[[^\]]*\]\s*")


@dataclass(frozen=True)
class Claim:
    text: str


def extract_claims(report: str) -> list[Claim]:
    """把日报按行拆成原子声明：剥掉 markdown 项目符号/编号/`[标签|优先级]` 前缀，再按句切。"""
    claims: list[Claim] = []
    for raw in (report or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = _BRACKET_TAG.sub("", line)
        line = _BULLET.sub("", line)
        line = _NUM_PREFIX.sub("", line)
        line = line.strip()
        if not line:
            continue
        for part in _SENT_SPLIT.split(line):
            part = part.strip().strip("——").strip()
            if len(part) >= 6:
                claims.append(Claim(part))
    return claims
