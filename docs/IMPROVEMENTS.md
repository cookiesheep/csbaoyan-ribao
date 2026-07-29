# 技术改进与设计原理 · Technical Improvements

> 本文档讲清楚：相比原项目，我们**改了什么、为什么这么改**。适合想理解设计或贡献代码的人阅读。
> 速览版对比表见 [README](../README.md#相比原项目的改进)。

---

## 1. 核心问题：原项目为什么会停更

原项目 [jielosc/csbaoyan-chat-daily](https://github.com/jielosc/csbaoyan-chat-daily) 的数据来源是 [qq-chat-exporter](https://github.com/shuakami/qq-chat-exporter)，后者底层是 **NapCat**——通过实现 NTQQ 协议，**让腾讯以为有「第二个客户端」登录了你的账号**。

这带来两个致命问题（见原项目 [pause-update.md](pause-update.md)）：
1. **封号**：腾讯风控检测到非官方协议登录 → 强制下线。作者换设备/系统无效（账号被标记），换小号才不封，但小号进不了群。
2. **手动导出**：每天要手动跑导出，既累又随时可能触发封号。

**Lagrange / LLOneBot / NapCat 是同一家人**（都占用 PC 端协议），换任何一个框架都绕不开封号。所以「换协议框架」不是出路。

## 2. 我们的解法：路线 B（本地数据库直读）

**关键洞察**：要拿群消息，根本不需要再登录一次 QQ。你的 NTQQ 桌面端**已经登录、已经在收消息**，聊天记录就在本地一个 SQLCipher 加密的 SQLite 库里。我们只要：

1. 从 NTQQ 进程内存提取解密密钥（[qq_dump_db](https://github.com/NapNeko/qq_dump_db)）
2. 解密本地库 → 明文 SQLite
3. 按群 + 日期查询消息
4. 转成项目要的 JSON

**为什么这样不封号**：全程**纯本地文件操作**——不向腾讯发任何网络请求，不产生第二个登录会话。风控系统无从检测。这是从协议层（会被检测）到文件层（不可检测）的根本切换。

## 3. 新增的核心组件

### 3.1 `ingest` 命令（替代手动导出）
- `src/csbaoyan_daily/ingest/ntqq_export.py`：DB 读取 + protobuf 解析 + QCE schema 映射
- `src/csbaoyan_daily/app/ingest.py`：应用编排
- CLI 子命令 `ingest`，与原 `generate`/`pipeline` 无缝衔接

**对下游零侵入**：`ingest` 产出的 JSON 完全符合原项目 `chat_processing.py` 期望的 schema（`sender.uid/uin/name`、`content.text/mentions/elements`、`statistics.timeRange`），文件名命中 `file_utils.DATE_PATTERN`。原项目的脱敏、分块、AI 汇总、发布**一行没改**。

### 3.2 schema 自适应（跨版本健壮）
NTQQ 把消息字段**拆成列**（列名=字段号）。我们基于 [QQBackup issue #83](https://github.com/QQBackup/qq-win-db-key/issues/83)（130 万条真实消息逆向）固化了字段号：
- `40020` 发送者 NT UID、`40033` 发送者 QQ、`40050` 时间戳、`40090` 群昵称、`40800` 正文 protobuf、`40900` 引用快照、`40021` 群标识

并提供 `ingest --inspect` **体检模式**：打印库结构 + 一条样本消息的完整解码树，NTQQ 升级后字段变了，照着调字段号常量即可，不用改逻辑。

### 3.3 防御式读取（解密库健壮性）
解密后的 SQLCipher 库偶发 cell fragmentation（少数页损坏），全表扫描大 BLOB 列会报 `database disk image is malformed`。
解法：**先查 rowid（不碰 blob）→ 逐行读取 → 跳过坏行**。丢几条消息对日报无影响，且彻底规避 malformed。这是实测踩坑后加的（实测 251 条里有 1 条坏行）。

### 3.4 正文/媒体智能处理
- `_collect_text` 递归收集可读字符串叶节点（blackboxprotobuf 盲解析），排除噪声（纯数字、UID、base64）
- 媒体文件名（`.jpg/.mp4/...`）规整为 `[媒体]` 占位符
- `@` 目标 uid/昵称先抽取、再从正文排除，避免昵称污染正文

## 4. 架构演进：单机 → 三机协同

原项目是「单机 + GitHub Pages」。我们的实例是**三机协同**（详见 [MAINTENANCE.md](MAINTENANCE.md)）：

| 机 | 角色 | 为什么 |
|----|------|--------|
| Windows 台式机 | 数据源 + 生成 | 必须是 Windows（qq_dump_db 依赖 Windows API 读 NTQQ 内存）；家宽 IP、单一 QQ 会话 = 零封号 |
| Linux 服务器 | 24/7 托管 | 静态站 + Cloudflare 隧道，大陆免备案 |
| Cloudflare | DNS + 反代 | 隧道出站，服务器不开公网 80/443，绕开 ICP 备案 |

> 注意：数据源**不能**搬到 Linux 服务器——Linux 版 QQ 是另一个二进制，qq_dump_db 不支持；在服务器挂 QQ 又是「机房 IP + 第二会话」，重回封号风险。这是踩过坑后的结论。

## 5. 量化对比

| 指标 | 原项目 | 本项目 |
|------|--------|--------|
| 日常人工操作 | 每天手动导出 | 0（定时任务） |
| 封号风险 | 中-高 | 极低 |
| 出报延迟 | 取决于手动 | 固定 06:30 自动 |
| 数据完整性 | 依赖导出工具覆盖 | 直读本地库，含防御式跳坏行 |
| 可维护性 | 单点 | 三机解耦，任一可独立替换 |

## 6. 已知局限与未来方向
- **正文抽取是 best-effort**：递归收集在极少数复杂消息（嵌套合并转发）上可能不完整；未来可定点提取文本字段号（见 `ntqq_export.py` 底部 CALIBRATION）。
- **依赖 Windows + NTQQ 在线**：数据源必须是 Windows 且 QQ 登录。无法做到完全无头。
- **合规灰色**：本地库解密属 ToS 灰色地带；仅用于本人所在群、不外传。
- **前端**：当前沿用原项目前端，待美化（见后续前端优化任务）。

## 7. 致谢
本项目是 [jielosc/csbaoyan-chat-daily](https://github.com/jielosc/csbaoyan-chat-daily) 的下游改进分支，AI 总结、脱敏、前端等核心能力均来自原作者。我们只解决「数据来源」这一卡脖子环节。
