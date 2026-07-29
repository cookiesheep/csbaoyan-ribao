# 前端重设计开发提示词 ·「活字印刷 Living Press」

> 把这份文档完整发给新的开发会话即可。它自包含全部背景与规格。

---

## 0. 一句话任务

把一个 CS 保研群「每日 AI 信息日报」的**纯静态前端**（`pages/` 目录），从当前 GitHub 配色 + 系统字体的通用风格，重设计为**「学术日报 / 活字印刷」**风格——把每篇日报真正排成报纸版面，并用「印刷机物理」主题动效驱动交互。**惊艳、有文化重量、动效拉满，但克制高级、拒绝 AI 俗套。**

在线站点（参考现状）：<https://csbaoyan.cn>
仓库：<https://github.com/cookiesheep/csbaoyan-ribao>

---

## 1. 项目背景（必须读懂）

- **这是什么**：`csbaoyan-ribao` —— 把一个 CS 保研 QQ 群每天海量杂乱的聊天，用 AI 提炼成一份结构化日报（招生/夏令营/预推免/导师/面试经验/风险）。每日定时自动生成并发布。
- **前端位置**：仓库的 `pages/` 目录，是纯静态站点（无后端、无构建步骤），由服务器 `python -m http.server` 托管 + Cloudflare 隧道对外。
- **技术栈**：原生 HTML/CSS/JS；Markdown 渲染用 `vendor/marked.min.js`（marked.js）+ `vendor/purify.min.js`（DOMPurify）。**不要引入构建工具/框架**，保持「改完即用」。
- **下游数据格式固定，不要改**：日报由 Python 生成，markdown 结构是固定的（见下）。前端只改「如何渲染」，不要要求改后端格式。

### 数据契约（必须遵守）
- `pages/data/reports.json`：JSON 数组，每项 `{"date":"YYYY-MM-DD","md_path":"reports/YYYY-MM-DD.md"}`，**按日期倒序**（最新在前）。
- `pages/data/reports/<date>.md`：单篇日报 markdown，**固定结构**：
  ```
  # CS保研信息日报
  > 免责声明：以下内容由 AI 总结...（一段引用）
  ## 今日概览
  （一段话概览）
  ## 重要信息
  - 要点1（常以 **加粗** 开头当小标题）
  - 要点2 ...
  ## 经验/观点
  - ...
  ## 有趣讨论
  - ...
  ## 风险与待核实
  - ...
  ```
- 现有功能（必须保留）：主页视图、阅读视图（日期切换器 + markdown 渲染）、搜索弹窗（Cmd/Ctrl+K）、明暗主题切换。

---

## 2. 设计方向：活字印刷 Living Press

### 2.1 核心理念
不是「贴一个牛皮纸/报纸背景」，而是**用自定义渲染器把每篇日报真正「排」成报纸版面**，再用**「一份报纸如何被印出来」的物理过程**（上墨、印刷、翻页、盖章、折页）作为动效词汇。气质：**金融时报 / 澎湃 / 严肃学术刊物**——权威、可信赖、有文化重量。受众是 CS 保研学生，保研是严肃升学决策，报纸的权威感天然契合。

### 2.2 反俗套红线（必须遵守）
- ❌ 禁紫色渐变白底、禁 emoji 当图标、禁「圆角卡片+左边框强调」、禁 SVG 火柴人、禁 Inter/Roboto/系统字体当标题。
- ✅ 暖纸底 + 单一朱红强调 + 衬线标题 + 慷慨留白；**一个细节做到 120%，其余 80%**。

### 2.3 字体（webfont via CDN，带 fallback）
- **中文标题/正文**：`LXGW WenKai`（霞鹜文楷，免费、有书卷气）或 `Noto Serif SC`（思源宋体）。CDN：jsDelivr / 字体 CDN。
- **西文/数字**：`EB Garamond` 或 `Spectral`（古典衬线，数字用 oldstyle figures）。
- **等宽（报头期号/日期/命令感）**：`JetBrains Mono`。
- 字体加载用 `font-display: swap`，并给系统衬线 fallback（`"Songti SC","SimSun",serif`）。

### 2.4 色板（CSS 变量，明/暗双主题）
```css
:root{
  --paper:#f4ede0;        /* 暖米纸底 */
  --paper-2:#ece3d2;      /* 次级纸/分区 */
  --ink:#1c1814;          /* 深墨正文 */
  --ink-soft:#4a4339;     /* 次级墨 */
  --muted:#7a6f5e;        /* 弱化 */
  --rule:#cdbf9f;         /* 栏线/分隔 */
  --stamp:#b8302a;        /* 朱红印章/唯一强调色 */
  --stamp-ink:#9a2620;
  --gold:#9a7b2e;         /* 极少量点缀（期号） */
}
[data-theme="dark"]{
  --paper:#15110c; --paper-2:#1d1812; --ink:#ece3d2; --ink-soft:#c9bda6;
  --muted:#8a7f6c; --rule:#3a3127; --stamp:#e05a4f; --stamp-ink:#c4453a; --gold:#c79a3c;
}
```

### 2.5 纸张质感（氛围而非纯色）
- 纸纹噪点：一层 SVG `feTurbulence` 噪点 / 细微纸纤维纹理，低不透明度叠加在 `--paper` 上。
- 报头下方一道**双线（粗细双规则线）**，经典报刊分割。
- 正文字段带极轻「墨迹阴影」（`text-shadow: 0 0.5px 0 rgba(0,0,0,.03)`），像微微凸起的活字。

---

## 3. 内容 → 报纸版面 的确定性映射（这是「不是皮肤」的关键）

**实现方式**：marked.js 正常渲染后，对输出 HTML 做后处理转换（建议用 `DOMParser` 解析 → 按标题文本重组 → 序列化 → 再交 DOMPurify，或 sanitize 后操作注入的 live DOM）。按 `## 标题` 文本**确定性**映射成报纸版面角色：

| 报告内容 | 排成的报纸角色 | 实现要点 |
|---|---|---|
| 刊名「保研日报」 | **报头 Masthead**：刊名（大号衬线，可局部竖排）+ 副刊名「CS保研信息日报」+ **第 NO.X 期**（期号=manifest 中该日报的序号，自增）+ 日期+星期 | 独立 `<header class="masthead">`；期号用等宽数字+金色 |
| `> 免责声明` | 报头下**法律声明小字**（极小、居中、灰） | 包成 `.colophon` |
| `## 今日概览` | **导语 Standfirst**：masthead 下、斜体、较大、单栏居中，像头版导语 | 该 section 正文包 `.standfirst` |
| `## 重要信息` | **头版头条 Lead Story**：**首字下沉 drop cap** + **双栏** + 两端对齐 + 标点悬挂 | `.lead` + `.lead p:first-of-type::first-letter`（3.5em、float、朱红/墨色）；`column-count:2;column-rule;justify` |
| `## 经验/观点` | **评论版 Commentary**：单栏长读，左栏线，引文样式 | `.commentary` |
| `## 有趣讨论` | **花絮 Briefs**：每条 `<li>` 渲染成「简讯」，**首句加粗当小标题** | `.briefs li`，首个加粗段包 `<b class="brief-kicker">` |
| `## 风险与待核实` | **勘误/提示框 Advisory**：虚线/双线边框盒 + ⚠ 标记，像报纸更正声明 | `.advisory` 包裹 |
| 每节最长句（JS 抽取） | **跨栏摘录引文 Pull-quote**：超大衬线引语，横跨双栏 | 抽取后插入 `<blockquote class="pullquote">` |

**中文报纸灵魂细节（一定要做，出气质）**：
- **竖排标题**：报头刊名或栏目标签用 `writing-mode: vertical-rl` 竖排，与横排日期交织。
- **首字下沉**、**栏间细线 `column-rule`**、**两端对齐 `text-align:justify`**、**标点悬挂 `hanging-punctuation:first last`**（渐进增强）。
- 栏目标签：`重要信息` 等渲染成**小写大写字母 + 编号 + 横线**（如 `№ 01 ── 重要信息`），用等宽字体。
- 数字用 **oldstyle figures**（`font-feature-settings:"onum"`）。

---

## 4. 动效词汇表：印刷机物理（动效拉满但主题连贯）

均**优先纯 CSS / SVG** 实现，必要时极轻 JS。全部必须支持 `prefers-reduced-motion: reduce` 降级为「直接显现」。

1. **「上机印刷」入场**：页面/日报加载，一道横向「墨辊」自上而下扫过（一条 `--ink` 渐变条 + `mask`/`clip-path` 下移），扫过处文字从 `blur(10px)+opacity:0` 收锐为清晰墨字，**按栏/行 staggered**（`animation-delay` 递增）。≈ 印刷机压墨。
2. **油墨晕染 Ink-bloom**：报头刊名、首字下沉大字，用**径向遮罩从中心向外晕开**（`mask-image: radial-gradient()` 配合 `@keyframes` 扩张），像湿墨渗入纸。
3. **翻页换日期**：切换日期 = 真翻页——旧页 `transform: rotateY(-12deg)` + `clip-path` 卷边 + 阴影变深后淡出，新页「啪」落定（轻微 `translateY+scale` 回弹）。左右键/按钮翻前一天。
4. **朱红印章 Stamp Drop（全站签名时刻）**：每期「第 NO.X 期 / 日期」处，一枚朱红圆章从顶**砸下**（`translateY(-200%)→0` + `scale(1.3→1)` + 短暂 `blur`），落地瞬间**油墨四溅**（几个朱红小点 `opacity/scale` 扩散），轻微旋转 `rotate(-8deg)` 斜盖。这是最出片的瞬间，仪式感拉满。
5. **号外快讯 Ticker**：报头下一条「号外 · 今日要闻」横滚条，把今日概览里的关键词像新闻台 ticker 滚动（`@keyframes` translateX，hover 暂停）。
6. **折页展开 Fold**：栏目可折叠；展开 = 报纸折痕打开（`max-height` + 子块轻微 `rotateX` 透视翻转依次展开）。
7. **栏线绘制**：栏目分隔线、栏间细线、报头双线，`width/scaleX:0→100%` 逐条画出（staggered）。
8. **纸张物理**：hover 段落/卡片轻微「揭起」（`translateY(-2px)` + 真实多层阴影）；纸纹随滚动轻微视差。

---

## 5. 交互（让它「活」）

- **版面切换**：「头版」（概览 + 头条摘要卡片网格）↔「全文」（多栏长读）两种视图，按钮切换带翻页过渡。
- **本期目录 TOC**：固定侧栏/顶部「本期目录」——跳转到 重要信息/经验/有趣/风险，像报纸版面索引，滚动高亮当前栏。
- **剪报 Clipping**：hover 任意段落出现小剪刀图标，点击 = 「剪下来」（复制到剪贴板 + toast「已剪报」）。
- **日期翻阅**：左右方向键 / 按钮 = 翻前一天报纸。
- **搜索**（保留并美化）：弹窗做成「资料室检索卡」，命中关键词像荧光笔划线。

---

## 6. 必须删除 / 修正的内容（重要）

- ❌ **删除「日报已暂时停止更新」横幅**（`.pause-banner` 整块）——本站现在每天自动更新。
- 🔧 **更新所有外链**：`jielosc/csbaoyan-chat-daily` → `cookiesheep/csbaoyan-ribao`（报头 GitHub、反馈、issues 链接）。
- 🔧 `og:url` → `https://csbaoyan.cn`；`<title>` / meta description 更新为新项目。
- 🔧 顶部状态栏：去掉 Telegram 链接（若无），保留 GitHub / 期数 / 搜索 / 主题切换。

---

## 7. 文件结构与交付

- 保持 `pages/` 为纯静态、无构建。可重写 `index.html` / `styles.css` / `app.js`；保留 `vendor/marked.min.js`、`vendor/purify.min.js`。
- 允许拆分 CSS（如 `styles/base.css`、`styles/print.css`、`styles/motion.css`）和 JS 模块，但保持 `<script src>` 直接引用（无 bundler）。如需 webfont，用 `<link>` 引 CDN。
- **不要破坏数据契约**：`data/reports.json` 与 `data/reports/*.md` 的格式与路径不变。

### 验收标准（必须自测通过）
1. 用仓库自带的 `pages/data/reports.json` + `pages/data/reports/*.md`（有数十篇真实样本）本地 `python -m http.server` 打开 `pages/index.html`，**首页 + 任意一期日报**都正确渲染成报纸版面（报头/期号/双栏/首字下沉/竖排标签/各栏目角色齐全）。
2. 日期切换 = 翻页动效；印章砸下动效在每期可见。
3. 搜索（Cmd/Ctrl+K）、明暗主题切换、响应式（窄屏单栏、报头自适应）均正常。
4. `prefers-reduced-motion` 下所有动效降级为无动画、内容完整可读。
5. 无控制台报错；marked + DOMPurify 仍正常工作；无紫色渐变/系统字体标题等俗套。

---

## 8. 落地建议顺序
1. 先搭**排版系统**（字体、色板、纸纹、报头、双栏、首字下沉、栏目角色映射）——先让静态报纸「长这样」。
2. 再加**动效**（印刷入场、油墨晕染、翻页、印章、ticker、栏线绘制）。
3. 最后**交互**（头版/全文切换、目录、剪报）与**响应式/降级/外链清理**。

> 完成后输出改动的 `pages/` 文件即可。开发中如某条动效实际效果不佳，可在保持「报纸排版 + 印刷物理」总基调下自行调整参数——设计允许迭代。

---

## 9. 部署拓扑与开发/上线流程（必读，避免改错地方！）

本项目有 **4 个代码/内容位置**，各司其职，**切勿混淆**：

| 位置 | 角色 | 前端开发要不要动 |
|---|---|---|
| **GitHub** `cookiesheep/csbaoyan-ribao` | **唯一源代码源（source of truth）** | ✅ 在这里开发：clone → 改 `pages/` → commit → push |
| **笔记本**（任一本地 checkout） | 开发用本地副本 | ✅ 作为开发工作区 |
| **台式机** `D:\code\csbaoyan` | **数据生成端**：跑 qq_dump_db + ingest + DeepSeek 出报 + 上传 `.md`。前端文件在此只是旧快照 | ❌ **不要在这里改前端** |
| **服务器** byocc `/var/www/csbaoyan` | **网站托管端**：`python -m http.server :3002`，经 Cloudflare → csbaoyan.cn | 部署目标（见下，勿自行改） |

### 关键澄清（最重要）
- **网站前端由服务器托管，不是台式机。** 台式机每天只生成日报 `.md` 数据并 scp 上传到服务器；前端 HTML/CSS/JS 与报告数据是**两件分开的事**。
- 你的任务**只做前端代码**（`pages/` 下的 `index.html`/`styles.css`/`app.js`/`vendor/`），**不要碰数据生成、不要碰台式机、不要碰服务器**。

### 开发流程
1. `git clone https://github.com/cookiesheep/csbaoyan-ribao.git`（克隆到干净新目录，如 `csbaoyan-ribao-fe`）
2. 在克隆里改 `pages/`；在 `pages/` 目录下 `python -m http.server 8080` 本地预览，用仓库自带的 `pages/data/`（数十篇真实样本）测试
3. 自测通过 → commit + push 到 GitHub

### 上线部署（不是你的任务，仅供了解）
前端推到 GitHub 后，**上线到 csbaoyan.cn 是单独一步**（由项目维护者审核后执行，你不用做）：
```bash
# 把前端文件（不含 data）同步到服务器（端口 6543）
scp -P 6543 pages/index.html pages/styles.css pages/app.js -r pages/vendor root@122.9.99.104:/var/www/csbaoyan/
# 服务器 http.server 实时读文件，刷新即生效；报告数据(.md)不受影响
```

### 你的交付物
**改好的 `pages/` 代码，commit 并 push 到 GitHub**，且本地 `python -m http.server` 预览满足第 7 节验收标准。**不要直接部署到线上服务器。**
