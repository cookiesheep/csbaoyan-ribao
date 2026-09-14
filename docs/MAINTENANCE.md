# 运维手册 · Maintenance & Operations

> 边缘采集 + 云端处理部署的完整运维参考。当前拓扑已于 **2026-09-08** 实跑迁移；旧的“台式机生成一切”流程已停用。

---

## 1. 架构总览

```
┌──────────────────────────────────┐    ┌────────────────────────────────────┐
│ ① 边缘采集：Windows 台式机         │    │ ② 处理与托管：Linux 服务器           │
│   COOKIESHEEP (局域网)            │    │   byocc (华为云 122.9.99.104)       │
│   - NTQQ 桌面端（QQ 2272735608）  │    │   - 日报 worker + DeepSeek          │
│   - qq_dump_db + ingest           │ ─▶ │   - XHS JSON + 多图素材生成          │
│   - 计划任务 CsBaoyanDaily 06:30  │scp │   - 静态站 127.0.0.1:8765           │
│   - 不运行 LLM、渲染和管理后台      │    │   - 管理后台 127.0.0.1:14310         │
└──────────────────────────────────┘    └──────────────┬─────────────────────┘
                                                       │
                                        ┌──────────────▼─────────────────────┐
                                        │ ③ Cloudflare（独立 Tunnel）          │
                                        │   csbaoyan.cn → :8765               │
                                        │   admin.csbaoyan.cn → :14310        │
                                        │   byocc-own 与本项目隔离，禁止改动     │
                                        └────────────────────────────────────┘
```

**数据流**：台式机解密本地 QQ 库 → ingest 抽取 QCE JSON → SSH 原子交接 → 华为云 DeepSeek 生成日报/XHS JSON → 云端确定性渲染素材 → 静态站与管理后台分别经独立 Cloudflare Tunnel 提供服务。

---

## 2. 机器清单（当前实例）

| 角色 | 主机 | 访问方式 | 关键路径/服务 |
|------|------|----------|---------------|
| 数据源 | 台式机 COOKIESHEEP | `ssh desktop`（用户 wqf18；Codex 使用专用密钥） | `D:\code\csbaoyan`、`D:\code\qq_dump_db`、`CsBaoyanDaily`、`CSBaoyan-QQ-Autostart` |
| 处理与托管 | 华为云 byocc | `ssh byocc`（root@122.9.99.104:6543） | `/opt/csbaoyan-daily`、`/opt/xhs-pack-generator`、`/srv/*`、`/var/www/csbaoyan`、相关 systemd 单元 |
| DNS/隧道 | Cloudflare | 浏览器 | 账号B：csbaoyan.cn；隧道 csbaoyan2（UUID `3d1a7c6e-8ec4-4f0a-bd24-4f90be115477`） |

> ⚠️ **两个 Cloudflare 账号**是历史原因（byocc.cc 在账号A，csbaoyan.cn 在账号B）。隧道与域名**必须在同一账号**，否则报 1033。当前 csbaoyan 隧道已正确建在账号B。

---

## 3. 台式机（数据源）运维

### 3.1 关键文件
- 项目：`D:\code\csbaoyan\`（含 venv、`.env`、`daily_auto.ps1`、`pages/`）
- 解密工具：`D:\code\qq_dump_db\`（`dump_qq_key_auto.py`，`NT_DB_BASE` 已补丁为 `D:\QQ_data\Tencent Files`）
- 日志：`D:\code\csbaoyan\logs\daily_<日期>.txt`
- 上传密钥：`C:\Users\wqf18\.ssh\csbaoyan_upload_key`（已写入服务器 authorized_keys）

### 3.2 每日自动流程
- **计划任务 `CsBaoyanDaily`**，每天 **06:30**（北京时间），以 wqf18 的 **InteractiveToken** 运行，与 QQ 位于同一登录会话；`-StartWhenAvailable` 会在用户会话可用后补跑。不要改成 Password/S4U/SYSTEM，否则 `qq_dump_db` 可能返回 0 但无法刷新交互会话中的 QQ 数据库。
- **计划任务 `CSBaoyan-QQ-Autostart`**，当前用户登录时直接启动 `D:\QQ_data\QQNT\QQ.exe`，让 QQ 生命周期不依赖 SSH 窗口；日报脚本仍保留缺进程时自动拉起的第二道兜底。
- 执行 `daily_auto.ps1`（默认采集**昨天**）：
  1. `dump_qq_key_auto.py --qq 2272735608` 解密，并校验 `nt_msg.db` 的大小和修改时间确实由本次任务刷新
  2. `edge_python_bootstrap.py ingest` 生成并校验 QCE JSON
  3. 上传为 `/srv/csbaoyan-daily/inbox/<日期>Tedge.json.part`，再原子改名
  4. 触发 `csbaoyan-daily@<日期>.service`；台式机写入 `logs\handoff\<日期>.json` 后退出

### 3.3 前置依赖（必须满足）
- **QQ 桌面端保持登录运行**（解密要读 `QQ.exe` 进程内存提密钥）。建议设 QQ 开机自启。
- 台式机开机 / 未休眠（06:30 能触发）。
- 能访问服务器 6543 端口（上传用）。DeepSeek 已由华为云调用，台式机不再承担 LLM 和卡片渲染。

### 3.4 常用操作

**手动补跑某天**（如机器关过、漏了某天）：
```powershell
powershell -ExecutionPolicy Bypass -File D:\code\csbaoyan\daily_auto.ps1 -Date 2026-07-30
```

如果 QQ 当前未运行，但运维人员已经确认 `output\<QQ号>\nt_msg.db` 是最近一次成功解密、且包含待补日期，可显式复用该数据库：
```powershell
powershell -ExecutionPolicy Bypass -File D:\code\csbaoyan\daily_auto.ps1 -Date 2026-07-30 -UseExistingDatabase
```
`-UseExistingDatabase` 只用于人工历史补数，计划任务不得配置该参数。日志会记录数据库路径和最后修改时间，避免悄悄使用陈旧数据。

**明确复用已确认新鲜的数据库并强制重新交接**：
```powershell
powershell -ExecutionPolicy Bypass -File D:\code\csbaoyan\daily_auto.ps1 `
  -Date 2026-07-30 -UseExistingDatabase -ForceHandoff
```

**查任务状态/日志**：
```powershell
Get-ScheduledTaskInfo -TaskName CsBaoyanDaily   # LastTaskResult=0 即成功
Get-ScheduledTask -TaskName CSBaoyan-QQ-Autostart  # 正常登录后应为 Running
Get-Content D:\code\csbaoyan\logs\daily_2026-07-29.txt -Tail 20
```

**手动触发一次任务**：`Start-ScheduledTask -TaskName CsBaoyanDaily`

**重新注册生产任务（必须与 QQ 同一交互会话）**：
```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File D:\code\csbaoyan\scripts\register_edge_task.production.ps1
```
注册后用 `Get-ScheduledTask CsBaoyanDaily | Select-Object -ExpandProperty Principal` 确认 `LogonType=Interactive`；导出的任务 XML 会显示底层值 `InteractiveToken`。

### 3.5 换群 / 换 QQ 号
改 `D:\code\csbaoyan\.env`：
- `CSBAOYAN_GROUP_CODE=<新群号>`（用 `ingest --inspect` 看 `group_msg_table` 的 `40021` 列确认群 code）
- `CSBAOYAN_NTQQ_QQ=<新QQ号>`
- qq_dump_db 的 `NT_DB_BASE` 指向新 QQ 的数据目录

---

## 4. 服务器（托管）运维

### 4.1 服务清单
| systemd 服务 | 作用 | 端口 |
|--------------|------|------|
| `csbaoyan-web` | 静态站（python http.server） | 127.0.0.1:8765 |
| `cloudflared-csbaoyan` | Cloudflare 隧道（csbaoyan2） | 出站 |
| `csbaoyan-daily@<date>` | 按日期生成日报与 XHS JSON，成功后触发素材同步 | oneshot |
| `csbaoyan-reconcile.timer` | 每 15 分钟重试 inbox 未处理交接 | timer |
| `xhs-pack-sync.service` / `.timer` | 生成素材包；事件触发 + 每 15 分钟兜底 | oneshot/timer |
| `xhs-pack-admin` | 素材管理后台 | 127.0.0.1:14310 |
| `cloudflared-csbaoyan-admin` | admin.csbaoyan.cn 独立 Tunnel | 出站；metrics 127.0.0.1:20244 |
| `cloudflared`（byocc，账号A） | byocc.cc 隧道 | 出站 |

> ⚠️ `cloudflared-byocc-own`（byocc.cc）是**另一个生产服务**，本次迁移没有改它。不要为了修 csbaoyan 重启或修改它。

### 4.2 常用操作（在服务器上，root）

**重启静态站**：`systemctl restart csbaoyan-web`

**重启 csbaoyan 隧道**：`systemctl restart cloudflared-csbaoyan`

**本地验证静态站**：`curl -I http://127.0.0.1:8765/`（应 200）

**检查完整云端链路**：
```bash
systemctl is-active csbaoyan-web cloudflared-csbaoyan xhs-pack-admin \
  cloudflared-csbaoyan-admin xhs-pack-sync.timer csbaoyan-reconcile.timer
journalctl -u 'csbaoyan-daily@2026-09-07.service' -n 80 --no-pager
journalctl -u xhs-pack-sync.service -n 80 --no-pager
```

**隧道连接状态**：
```bash
cloudflared tunnel info 3d1a7c6e-8ec4-4f0a-bd24-4f90be115477   # 看 CONNECTIONS
```

**外网验证**：`curl -I https://csbaoyan.cn/`（应 200）

### 4.3 配置文件位置
- 隧道配置：`/root/.cloudflared/csbaoyan-config.yml`（含 `protocol: http2`，必须！否则 QUIC 在某些网络下连不上）
- 网站根目录：`/var/www/csbaoyan/`（`data/reports` + `data/xhs` 由 `csbaoyan` 服务账户写入）
- 日报发行版：`/opt/csbaoyan-daily-releases/<commit>`，当前版本软链接 `/opt/csbaoyan-daily`
- 素材发行版：`/opt/xhs-pack-generator-releases/<commit>`，当前版本软链接 `/opt/xhs-pack-generator`
- 运行数据：`/srv/csbaoyan-daily`、`/srv/xhs-pack-generator/packs`
- 私密环境：`/etc/csbaoyan/csbaoyan.env`、`xhs.env`、`cloudflared-admin.env`（root:csbaoyan 0640）
- 证书：`/root/.cloudflared/cert.pem`（账号A，byocc 管理用）；账号B 证书备份 `certB.pem`

### 4.4 手动放一份报告到服务器（不走台式机）
```bash
# 在台式机或本机
scp -i C:\Users\wqf18\.ssh\csbaoyan_upload_key -P 6543 pages\data\reports\2026-07-29.md root@122.9.99.104:/var/www/csbaoyan/data/reports/
```

---

## 5. Cloudflare 运维

### 5.1 两个账号的边界
- **账号A**：`byocc.cc` + `byocc` 隧道 + cert.pem（服务器上 `/root/.cloudflared/cert.pem`）。**不要在这里动 csbaoyan.cn。**
- **账号B**：`csbaoyan.cn`（zone）+ `csbaoyan2` 隧道。网站的 DNS 与隧道都在这里。

### 5.2 DNS 记录（账号B 的 csbaoyan.cn）
- 一条 CNAME：`@` → `3d1a7c6e-8ec4-4f0a-bd24-4f90be115477.cfargotunnel.com`，**代理状态：橙色云（Proxied）**。
- NS：`lochlan.ns.cloudflare.com` / `opal.ns.cloudflare.com`（在阿里云改的，已生效）。

### 5.3 隧道需要在账号B操作时的授权
服务器上 cert.pem 默认是账号A。要在账号B建/改隧道时：
1. `mv /root/.cloudflared/cert.pem /root/.cloudflared/certA_live.pem`
2. `cloudflared tunnel login` → 把输出的 URL 在**账号B**浏览器打开 → 勾选 csbaoyan.cn → Authorize
3. 操作完 `cp certA_live.pem cert.pem` 恢复账号A证书
4. 运行中的 csbaoyan2 隧道靠 `<uuid>.json` 凭证运行，不受 cert.pem 切换影响

### 5.4 域名续费 / 实名认证
- `csbaoyan.cn` 在**阿里云**购买，**.cn 必须保持实名认证有效**，否则解析会被暂停。
- 走 Cloudflare 隧道**免 ICP 备案**（服务器不开公网 80/443，华为云无触发点）。

---

## 6. 日常巡检 Checklist

每天/每周瞄一眼即可：
- [ ] 打开 `https://csbaoyan.cn`，首页正常、有最新日报
- [ ] 台式机：QQ 在线、任务 `CsBaoyanDaily` 昨天结果=0
- [ ] 服务器：`csbaoyan-web`、`cloudflared-csbaoyan`、`xhs-pack-admin`、`cloudflared-csbaoyan-admin`、两项 timer 均 active
- [ ] DeepSeek 余额充足（出报消耗 token）

---

## 7. 故障排查（分层诊断）

### 症状：网站打不开 / 502 / 530 / 1033
按层从下往上查（在服务器上）：
```bash
curl -I http://127.0.0.1:8765/          # ① 静态站活着？(应200)
systemctl is-active csbaoyan-web        # ② 服务在跑？
cloudflared tunnel info 3d1a7c6e-8ec4-4f0a-bd24-4f90be115477  # ③ 隧道有连接？
systemctl is-active cloudflared-csbaoyan # ④ 隧道服务在跑？
dig +short csbaoyan.cn                   # ⑤ DNS 解析到 CF？
curl -I https://csbaoyan.cn/             # ⑥ 外网可达？
```
- **1033**：隧道与域名跨账号，或 CNAME 指错隧道 UUID → 见 5.2 / 5.3。
- **530 + 日志 QUIC fail**：确认 `csbaoyan-config.yml` 有 `protocol: http2`，重启隧道。
- 隧道无连接：`journalctl -u cloudflared-csbaoyan -n 30` 看错误。

### 症状：今天的日报没更新
1. 台式机 QQ 是否在线？（解密依赖）
2. `Get-ScheduledTaskInfo CsBaoyanDaily` 的 `LastTaskResult` 是否 0
3. 看 `D:\code\csbaoyan\logs\daily_<日期>.txt`：解密/ingest 是否成功、消息数是否合理、是否出现 `HANDOFF_COMPLETE`
4. 若出现 `DECRYPT_STALE_OUTPUT`，说明解密进程退出码虽然为 0，但数据库没有刷新；确认任务是 `InteractiveToken`、QQ 在同一用户会话登录，再手工触发任务
5. 若「未找到日期的导出文件」→ 那天 QQ 没同步到消息（机器关过？），QQ 登录拉一下离线消息后补跑
6. 若已经 `HANDOFF_COMPLETE`，转到服务器检查 `csbaoyan-daily@<日期>.service` 和 `/srv/csbaoyan-daily/logs/<日期>.log`
7. 若日报/XHS JSON 已生成但素材没出现，检查 `xhs-pack-sync.service`；timer 会每 15 分钟幂等重试

生产脚本检测不到 `QQ.exe` 时，会先通过公共桌面或开始菜单快捷方式自动启动 QQ，等待登录和消息同步后再解密。该机制依赖 Windows 用户已经登录且 QQ 保存了登录状态；若自动登录失效，任务仍会安全失败并在日志写入 `QQ_AUTO_START_FAILED` 或 `DECRYPT_FAILED`，不会复用旧数据库。

### 症状：DeepSeek 报错（云端生成失败）
- 当前模型名使用 `deepseek-v4-flash` 或 `deepseek-v4-pro`；`deepseek-chat` / `deepseek-reasoner` 已停用，生产脚本会在调用前给出 `MODEL_CONFIG_INVALID`。
- `/etc/csbaoyan/csbaoyan.env` 与 `/etc/csbaoyan/xhs.env` 各自配置主/备用 Key，权限必须保持 `root:csbaoyan 0640`；普通超时、网络错误、429 不切换备用 Key。
- 看 `journalctl -u csbaoyan-daily@<日期>` 判断日报阶段；看 `/srv/xhs-pack-generator/logs` 判断文案/卡片阶段。不要输出 EnvironmentFile 内容。
- 云端采用直连 DeepSeek；临时降低日报并发应通过服务环境/命令参数完成，修改后记录并恢复。

### 症状：NTQQ 升级后字段抽不全
NTQQ 跨版本字段号会变。重新校准：
```powershell
.venv\Scripts\python.exe -m csbaoyan_daily.cli ingest --inspect --db-path <解密后的nt_msg.db>
```
把「样本消息原始解码树」对照 `ntqq_export.py` 顶部字段常量调整（见 [optimize-export.md](optimize-export.md) 的 CALIBRATION）。

---

## 8. 备份与恢复

**最关键的两样**：
1. **QQ 号 + 群 code**：2272735608 / 943826679（记在 `.env`）
2. **服务器隧道凭证**：`/root/.cloudflared/3d1a7c6e-*.json`（丢了就得在账号B重建隧道）

**日报和素材**：服务器 `/var/www/csbaoyan/data/reports`、`/var/www/csbaoyan/data/xhs`、`/srv/xhs-pack-generator/packs` 是当前真相源。台式机保留迁移时快照，但迁移后的新内容不会自动回写台式机。

**重建最小集**（灾难恢复）：
1. 新 Windows 机：装 NTQQ + 登录 QQ → 部署项目 + qq_dump_db → `.env` → `ingest --inspect` 校准 → 计划任务
2. 服务器：部署两个 commit 发行版与 venv/node_modules → 恢复 `/var/www/csbaoyan`、`/srv/xhs-pack-generator/packs`、`/etc/csbaoyan/*.env` → 启动本文 4.1 的全部 csbaoyan 单元
3. 恢复台式机→服务器 SSH 密钥和 `/srv/csbaoyan-daily/inbox` 写入权限

---

## 9. 安全清单
- [ ] DeepSeek API key 定期轮换（不要明文外泄）
- [ ] 台式机 SSH 密码、服务器 root 强密码 / 改密钥登录
- [ ] `csbaoyan_upload_key` 仅用于上传，权限 600
- [ ] 解密产物 `output/<QQ>/nt_msg.db` 含明文聊天，勿提交 git、勿外传（`.gitignore` 已含 `chat_exports/`）
- [ ] QCE 交接文件含一天的原始群聊，仅经 SSH 传输，服务成功后删除；服务器 inbox/日志不得开放给 Web 服务

## 10. 2026-09-08 迁移保护规则

- COOKIESHEEP 只运行 `CsBaoyanDaily` 与 `CSBaoyan-QQ-Autostart`；`CSBaoyan-XHS-Daily`、`CSBaoyan-XHS-Admin`、`CSBaoyan-XHS-Tunnel` 必须保持 Disabled，并确认没有旧的独立 `cloudflared.exe tunnel run` 进程。旧 connector 残留会让 Cloudflare 随机把请求发到已下线的 Windows 源站，表现为间歇或持续 502。
- 旧脚本备份：`D:\code\csbaoyan\migration-backups\daily_auto.pre-cloud-20260908.ps1`；旧任务 XML：`D:\code\csbaoyan\migration-backups\scheduled-tasks-20260908`。
- 华为云正式目录：`/opt/csbaoyan-daily`、`/opt/xhs-pack-generator`、`/srv/csbaoyan-daily`、`/srv/xhs-pack-generator`、`/var/www/csbaoyan`、`/etc/csbaoyan`。
- `/opt/*` 使用 commit 目录 + 当前软链接发布；升级时构建新目录、验收后原子换软链接，不要原地覆盖当前 release。
- 当前资源上限：日报 worker 4G/400% CPU，素材 sync 2G/400%，后台 1G/200%，admin Tunnel 256M/50%。不得删除这些边界。
- `server_process_daily.sh` 按输入 SHA 幂等；成功才写 `processed/<date>.sha256` 并删除 inbox。`run-linux-sync.sh` 自带 flock，Pack 层还按 source hash/prompt/schema 幂等。
- 详细的全服务器保护清单和回滚顺序以 `D:\code\服务器运维总览.md` 第 10 节为准。

## 11. 2026-09-09 至 09-13 边缘解密假成功事故

- 华为云所有正式服务、timer 和公开入口始终正常；9 月 8 日日报与素材也实际存在。
- 9 月 9–13 日的 `CsBaoyanDaily` 每天都运行，但当时任务使用 `LogonType=Password`，与交互式 QQ 会话隔离。
- `dump_qq_key_auto.py` 返回退出码 0，却没有刷新 `D:\code\qq_dump_db\output\2272735608\nt_msg.db`；数据库修改时间一直停在 9 月 8 日，随后 ingest 只能报告“找不到目标日期消息”。
- 2026-09-14 在交互会话重新解密后，数据库从约 262 MB 更新到 343 MB，9 月 9–13 日 QCE 全部恢复并在华为云生成日报、XHS JSON 和素材包。
- 永久修复有两层：`daily_auto.ps1` 在解密后验证数据库必须由本次运行刷新；`CsBaoyanDaily` 改为 `InteractiveToken`，确保与 QQ 位于同一登录会话。
- 生产修复已于 2026-09-14 部署；PowerShell Principal=`Interactive`、任务 XML=`InteractiveToken`，安全手工触发返回 0，下一次运行是 2026-09-15 06:30。部署前脚本和任务 XML 备份在 `D:\code\csbaoyan\migration-backups\edge-session-fix-20260914-181116`。首次完整的无人值守新日期解密仍以 9 月 15 日自然运行结果为准。
