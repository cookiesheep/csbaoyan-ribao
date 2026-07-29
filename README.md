# 保研日报 · CS Baoyan Daily 📰

> 基于 AI 的 CS 保研群每日信息提炼。**不封号、全自动、零手动导出。**

🌐 **在线示例**：<https://csbaoyan.cn>

---

## 这是什么

把一个 CS 保研 QQ 群里每天海量、杂乱的聊天，自动提炼成一份结构化日报（招生信息、夏令营/预推免、导师联系、面试经验、风险提示等），方便没空爬楼的保研人快速跟进。

每日定时运行：**解密本地 QQ 聊天数据库 → 脱敏 → AI 分块提炼 → 汇总成日报 → 发布到网站**。全程无需手动导出聊天记录。

## 我们解决了什么痛点（最重要的一件事）

本项目是 [jielosc/csbaoyan-chat-daily](https://github.com/jielosc/csbaoyan-chat-daily) 的**改进分支**。原项目已于 2026-05 停更，停更原因（见 [原项目说明](docs/pause-update.md)）是两个叠加的痛点：

| 痛点 | 原项目 | 本项目 |
|------|--------|--------|
| **封号（致命）** | 用 `qq-chat-exporter`（底层 NapCat）**登录第二个 QQ 会话**拉消息 → 腾讯风控 → 强制下线/封号 | 改为**读本地 NTQQ 数据库**，不创建任何第二会话、不发任何网络请求 → **零封号风险** |
| **每天手动导出（麻烦）** | 每天手动跑导出工具，耗时且随时可能触发封号 | 一台常开 Windows 机器（QQ 保持登录）**定时任务全自动**，每日 06:30 自动出报 |

> 简言之：原项目「为了拿数据去登录第二个 QQ」会被封；本项目「只读自己已登录 QQ 的本地数据库」，纯本地文件操作，从根上绕开了风控。

## 相比原项目的改进

| 维度 | 原项目 | 本项目 |
|------|--------|--------|
| 数据来源 | NapCat 协议拉取（封号） | 本地 SQLCipher 库直读（[qq_dump_db](https://github.com/NapNeko/qq_dump_db) 解密 + 自研字段抽取） |
| 封号风险 | 中-高 | **极低**（无第二会话） |
| 日常操作 | 每天手动导出 | 计划任务全自动，零手动 |
| 部署形态 | 单机 + GitHub Pages | **三机协同**：数据源（Windows）+ 服务器托管（Linux）+ Cloudflare 隧道 |
| 数据库健壮性 | — | 防御式读取（自动跳过解密库偶发的 cell 损坏页） |
| NTQQ 字段处理 | — | 基于 [QQBackup 字段研究](https://github.com/QQBackup/qq-win-db-key/issues/83) 的 schema 自适应（跨版本字段号校准 + `inspect` 体检模式） |
| 网站访问 | 仅 GitHub Pages | 自有域名 + Cloudflare（大陆免备案） |

## 架构

```
┌─────────────────────────────┐        ┌──────────────────────────────┐
│  数据源：Windows 台式机       │        │  托管：Linux 服务器           │
│  （QQ 保持登录，家宽 IP）     │        │  （24/7）                     │
│                              │  scp   │                              │
│  qq_dump_db 解密本地库        │ ─────▶ │  静态站 pages/ (端口 3002)     │
│  → ingest 抽取消息            │  日报  │        │                      │
│  → DeepSeek 生成日报          │  上传  │        ▼                      │
│  （Windows 计划任务每日06:30）│        │  Cloudflare 隧道 → csbaoyan.cn │
└─────────────────────────────┘        └──────────────────────────────┘
```

下游的脱敏、分块、AI 汇总、发布逻辑**沿用原项目**（generate / verify / publish / broadcast），本项目只在「数据来源」这一步做了替换与增强，对下游零侵入。

## 快速上手

详细文档：
- **[docs/MAINTENANCE.md](docs/MAINTENANCE.md)** — 三机部署与运维（最详细）
- **[docs/IMPROVEMENTS.md](docs/IMPROVEMENTS.md)** — 技术改进与设计原理（为什么这么改）
- **[docs/optimize-export.md](docs/optimize-export.md)** — 本地库直读（路线 B）原理与校准
- **[docs/deploy-guide.md](docs/deploy-guide.md)** — 原项目部署指南（AI 出报部分）
- **[docs/pause-update.md](docs/pause-update.md)** — 原项目停更说明（我们要解决的痛点）

最小流程：
1. Windows 机器上装 NTQQ 桌面端并登录目标群
2. `git clone https://github.com/<your-name>/csbaoyan-ribao.git` + [qq_dump_db](https://github.com/NapNeko/qq_dump_db)
3. `pip install -r requirements.txt`，配置 `.env`（见 `.env.example`）
4. 用 `ingest --inspect` 一次性校准字段（见 optimize-export.md）
5. 跑 `ingest` → `pipeline` 生成日报；挂计划任务实现全自动

## 致谢

本项目站在前人肩上，**核心 AI 总结流程来自原项目**：

- **[jielosc/csbaoyan-chat-daily](https://github.com/jielosc/csbaoyan-chat-daily)** —— 原作者设计了完整的「脱敏→分块→AI 日报→发布」流程与前端页面，本项目直接沿用并在此基础上做数据源改造。🙏
- **[CS-BAOYAN 社区](https://github.com/CS-BAOYAN)** —— 「绿群」的来源。
- **[NapNeko/qq_dump_db](https://github.com/NapNeko/qq_dump_db)** —— 安全解密本地 NTQQ 数据库。
- **[QQBackup/qq-win-db-key](https://github.com/QQBackup/qq-win-db-key)** —— NTQQ 数据库字段逆向研究（[issue #83](https://github.com/QQBackup/qq-win-db-key/issues/83)），字段抽取的基础。
- **[blackboxprotobuf](https://github.com/nccgroup/blackboxprotobuf)** —— protobuf 盲解析。

## 免责声明

- 日报由 AI 总结生成，可能不完全准确，请以官方信息为准。
- 项目对聊天内容做匿名化处理以降低身份暴露风险，但少数语境下仍可能被上下文识别。
- 本地数据库解密属腾讯 ToS 灰色地带；仅用于获取**你本人所在群**的消息、不外传，实际封号风险极低，但合规风险非零。请遵守相关法律法规，自负责任。

## License

MIT（与原项目一致）。
