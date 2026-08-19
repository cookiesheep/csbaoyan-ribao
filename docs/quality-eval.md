# 日报质量评估与事实核验

本仓库提供两个独立的离线质量工具，都消费 `generate` 产出的报告与其脱敏 transcript，不改动生产流水线：

| 命令 | 作用 | 产出 |
|------|------|------|
| `cli eval` | G-Eval 评估：对日报打 **faithfulness（忠实度）+ recall（召回率）** 分 | 1-5 分 + 归一化 + 裁判理由 |
| `cli factcheck` | 两层事实核验：**本地 NLI 预过滤（可选）+ 非生成器 LLM 裁判**，逐条核验声明 | supported / contradicted / not_enough_info 计数 + 支持率 + 逐条理由 |

两者默认都用 `.env` 里的 DeepSeek 配置，也都可以通过 `--base-url/--api-key/--model` 指定独立裁判。

---

## 1. `eval`：G-Eval 评估

### 原理

G-Eval（Liu et al. 2023）的简化可复现变体：固定的中文 CoT 评分细则 → 裁判模型先给依据、最后一行输出 1-5 整数 → 解析最后一个整数 → 归一化到 [0,1]。**温度恒为 0**，保证同一输入多次跑结果一致。

- **faithfulness（忠实度）**：日报每条信息是否都能在来源找到依据，有无编造/夸大/张冠李戴。
- **recall（召回率）**：来源里的重要信息（夏令营、导师、院校、经验、时间节点）是否被捕获。

### 用法

```powershell
# 评估昨天（默认）的日报
PYTHONPATH=src python -m csbaoyan_daily.cli eval

# 指定日期，并把结果写到文件
PYTHONPATH=src python -m csbaoyan_daily.cli eval --date 2026-07-29 --out internal/eval/2026-07-29.md
```

### 输出示例

```
# G-Eval 评估结果

- faithfulness: 5/5（1.00）
- recall: 4/5（0.80）
- average: 0.90

## 裁判理由
### faithfulness
所有信息均可在来源找到，无编造。
### recall
...
```

### 自偏好规避

裁判模型与生成模型用同一厂商时存在「自偏好」风险（模型倾向给自己/同族输出高分）。**建议**：生成用 DeepSeek 时，eval 裁判用其它厂商（如智谱 GLM）：

```powershell
PYTHONPATH=src python -m csbaoyan_daily.cli eval `
  --base-url https://open.bigmodel.cn/api/paas/v4/ `
  --api-key <GLM_KEY> --model glm-4.6
```

---

## 2. `factcheck`：两层事实核验

### 原理

把日报拆成原子声明（剥掉 markdown 符号/`[标签|优先级]` 前缀，按中文句末标点切句），逐条核验：

1. **第一层 · 本地 NLI 预过滤（可选）**：用中文 NLI 模型（Erlangshen-Roberta-110M-NLI）对 `(来源, 声明)` 打蕴含/矛盾/中立。
   - 高置信 **蕴含** → 直接判 `supported`，省一次 LLM 调用。
   - 高置信 **矛盾** → 直接判 `contradicted`。
   - 其余（中立或低置信）→ 进入第二层。
2. **第二层 · 非生成器 LLM 裁判**：对来源做 grounded 判断，输出 `supported / contradicted / not_enough_info` + 置信度 + 一句理由。

阈值默认 `--confidence-threshold 0.7`（NLI 置信度 ≥ 0.7 才短路）。

### 用法

```powershell
# 默认：NLI 开（装了 torch 才生效，否则自动降级）
PYTHONPATH=src python -m csbaoyan_daily.cli factcheck --date 2026-07-29

# 强制只用 LLM 裁判（关掉 NLI）
PYTHONPATH=src python -m csbaoyan_daily.cli factcheck --date 2026-07-29 --no-nli

# 用 GLM 作裁判（与 DeepSeek 生成器不同厂商）
PYTHONPATH=src python -m csbaoyan_daily.cli factcheck `
  --base-url https://open.bigmodel.cn/api/paas/v4/ `
  --api-key <GLM_KEY> --model glm-4.6 --out internal/factcheck/2026-07-29.md
```

### NLI 依赖（可选）

本地 NLI 需要 `torch` + `transformers`（约 2GB），**不**在基础 `requirements.txt` 里，按需安装：

```powershell
pip install "torch>=2.0" "transformers>=4.30"
```

未安装时 `factcheck` 会打印一条 warning 并自动降级为全量 LLM 裁判，**不报错、不阻塞**。降级只增加 LLM 调用成本，不影响核验结论正确性。

---

## 3. 付印统计与前端展示（编辑部透明度）

`generate` 每次出报都会顺手写一份**付印工单**（确定性计数，零 LLM 调用）：

```
pages/data/stats/<date>.json    # 每期一份：原始消息数 / 去噪构成 / 发言者数 / 分块数 / 要点数 / 原话引用数 / 抽取模式 / 模型
pages/data/stats/summary.json   # 全期聚合：期数 + 各项累计 + latest_eval（首页/印房页一次拉取）
```

- 位于 `publish` 的 pathspec（`pages/data`）内，**随站点自动发布**；只存计数，不存任何消息内容。
- 前端围绕它渲染三个可见组件（Living Press 语言）：
  - **付印流程单 Docket**：每期报头下方一条「原始 N → 去噪 −N → 有效 N · N 位发言者 → 要点 N · 原话 N → 付印」，可展开看去噪构成与 G-Eval 分数。
  - **原话引用排版**：正文中 “...” / 「...」 引用统一加朱红下划线 + 「原话」角标。
  - **印房页**（`#pressroom`）：五段流水线说明 + 质量体系 + 累计大盘（读 `summary.json`）。
- 历史期数（升级前生成的）没有 stats JSON：前端 fetch 404 时静默缺省，不渲染 docket、不报错。

### `--with-eval`：出报后自动打分（opt-in）

```powershell
PYTHONPATH=src python -m csbaoyan_daily.cli pipeline --with-eval
```

generate 成功后对当期跑一次 G-Eval（2 次 LLM 调用），把 faithfulness/recall 写进该期 stats JSON 的 `eval` 字段并刷新 `summary.json`（前端 docket 与印房页自动展示）。评估失败只记 warning，**不阻塞出报**。裁判仍与生成共用 `.env` 配置——想规避自偏好，用独立的 `pipeline --base-url/--api-key/--model` 覆盖，或继续用离线 `cli eval` 配不同厂商裁判。

---

## 与生产流水线的关系

`eval` / `factcheck` 是**只读、离线**的质量度量工具：

- 输入：`generate` 已产出的 `pages/data/reports/<date>.md` + `internal/transcripts/<date>.txt`。
- 输出：只打印或写到 `internal/`（不会进 `pages/`，不影响发布的站点）。
- 不改 `generate / verify / publish / broadcast` 任何逻辑；`pipeline` 仅在显式传 `--with-eval` 时才追加一次 G-Eval（见上节）。

推荐用法：每天 `pipeline` 出报后，对关键日期或抽检日期跑一次 `eval` + `factcheck`，跟踪 faithful/recall/support_rate 的趋势。
