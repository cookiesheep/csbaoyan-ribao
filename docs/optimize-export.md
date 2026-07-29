# 路线 B：本地数据库直读（自动 + 不封号）

> 用一条命令替代「每天手动导出聊天记录」。不创建 QQ 第二会话，纯本地文件操作，规避原作者踩的封号坑。

## 一、原理：为什么这条路不封号

| | 原方案（qq-chat-exporter / NapCat） | 路线 B（本地库直读） |
|---|---|---|
| 拿数据的方式 | 用非官方协议**登录第二个 QQ 会话**拉消息 | **不登录**，读你本机已登录 NTQQ 的本地数据库文件 |
| 网络请求 | 有，走 QQ 协议 | **无**，纯本地文件读写 |
| 封号风险 | 中-高（腾讯检测到第二会话 → 强制下线/封号） | **极低**（无第二会话，风控无从事先检测） |

你的 NTQQ 桌面端正常登录着（一个正常会话），聊天记录存在本地一个 SQLCipher 加密的 SQLite 库里。路线 B 从进程内存提取密钥 → 解密本地库 → 查目标群当天消息 → 转成项目要的 JSON。全程不发任何网络请求。

> ⚠️ 合规提示：解密本地库、提取进程内存密钥属腾讯 ToS 灰色地带。读的是你自己所在群的消息、不外传，实际封号风险极低，但非零合规风险；类似工具有被 DMCA 下架先例。仅用于个人获取自己所在群的信息，遵守法律法规。

## 二、前置准备

1. **NTQQ 桌面端**：就是你平时用的 QQ 电脑版（[im.qq.com](https://im.qq.com) 下载）。确认它装在你电脑上、能正常登录目标保研群。设置 → 关于，版本是 `9.9.x` 这种现代版即为 NTQQ。
2. **qq_dump_db**（解密工具）：
   ```powershell
   git clone https://github.com/NapNeko/qq_dump_db.git D:\tools\qq_dump_db
   .venv\Scripts\python.exe -m pip install cryptography
   ```
3. **项目依赖**（已含）：`pip install -r requirements.txt`（含 `blackboxprotobuf`）。

## 三、一次性校准（关键，必做一次）

NTQQ 跨版本字段会微调。第一次必须用体检模式看真实库结构，把字段调准：

1. QQ 保持登录运行 → 解密一次：
   ```powershell
   .venv\Scripts\python.exe D:\tools\qq_dump_db\dump_qq_key_auto.py --qq 你的QQ号
   ```
   解密后的明文库在 `qq_dump_db\output\你的QQ号\nt_msg.db`（路径以工具实际输出为准）。

2. 体检：
   ```powershell
   $env:PYTHONPATH = "src"
   .venv\Scripts\python.exe -m csbaoyan_daily.cli ingest --inspect `
     --db-path "D:\tools\qq_dump_db\output\你的QQ号\nt_msg.db"
   ```
   输出含：所有表、疑似消息表、字段、**一条样本消息的完整解码树 + 抽取结果**。

3. **把这份体检输出发给 Claude**，据此把 `--table` / `--blob-column` / `--time-column` / `--group-column` 和正文/@ 字段定点调准（这一步不可省，是确保日报内容正确的关键）。

## 四、配置 `.env`

```ini
# 已解密的明文库路径（或 daily_full.ps1 自动解密后覆盖）
CSBAOYAN_NTQQ_DB_PATH=D:\tools\qq_dump_db\output\你的QQ号\nt_msg.db
# 目标群过滤值（群号或群名片段；校准后填精确列名到命令行 --group-column）
CSBAOYAN_GROUP_CODE=987654321
# 你的 QQ 号（qq_dump_db 解密步骤用）
CSBAOYAN_NTQQ_QQ=10001
# qq_dump_db 的 dump_qq_key_auto.py 路径（填了才会自动解密）
CSBAOYAN_DUMP_DB_DIR=D:\tools\qq_dump_db\dump_qq_key_auto.py
```

## 五、每日运行

### 手动一键
```powershell
.\scripts\daily_full.ps1                # 解密→ingest→出昨天日报
.\scripts\daily_full.ps1 -Date 2026-07-28  # 指定日期
```

### 全自动（Windows 计划任务）
```powershell
# 每天 06:30 自动跑（QQ 需保持登录）
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File D:\code\csbaoyan-chat-daily\repo\scripts\daily_full.ps1"
$trigger = New-ScheduledTaskTrigger -Daily -At 6:30am
Register-ScheduledTask -TaskName "CsBaoyanDaily" -Action $action -Trigger $trigger
```

之后每天自动：解密最新库 → 抽取昨天目标群消息 → AI 生成日报 → 发布。**零手动。**

## 六、数据流

```
本机 NTQQ（正常登录，1 个会话，不封号）
   │ 本地文件
   ▼
nt_msg.db ──qq_dump_db 解密──▶ 明文 SQLite
   │
   ▼ ingest 命令（blackboxprotobuf 按字段号抽取）
chat_exports/<date>T<time>.json   ← 命中 file_utils.DATE_PATTERN
   │ 下游零改动
   ▼
generate → verify → publish → broadcast   ← 现有 pipeline
```

## 七、常见问题

**ingest 报「未找到消息表」？** 跑 `ingest --inspect` 看实际表名，用 `--table` 指定。

**导出的正文不全/有噪声？** NTQQ 版本字段差异。把 `--inspect` 的「样本消息原始解码树」发回来，定点调 `_collect_text` 字段号。

**不想每天解密？** 密钥通常按安装稳定。可手动解密一次后，把 `CSBAOYAN_NTQQ_DB_PATH` 指向该明文库；但库内容不会自动更新——要拿最新消息仍需重新解密当前库。计划任务里带上解密步骤最省心。

**在校准前想先看效果？** 可先用任意一条已有的 qq-chat-exporter JSON 放进 `chat_exports/` 直接跑 `pipeline`，确认下游链路；ingest 是数据源的替代品，两者产出格式一致。
