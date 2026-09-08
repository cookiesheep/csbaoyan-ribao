# 运维手册 · Maintenance & Operations

> 三机协同部署的完整运维参考。本手册既记录**当前实例**的真实配置（便于直接操作），也给出**通用步骤**（便于迁移/重建）。

---

## 1. 架构总览

```
┌──────────────────────────────────┐    ┌──────────────────────────────────┐
│ ① 数据源：Windows 台式机           │    │ ② 托管：Linux 服务器              │
│   COOKIESHEEP (局域网)            │    │   byocc (华为云 122.9.99.104)     │
│   - NTQQ 桌面端（QQ 2272735608）  │    │   - 静态站 /var/www/csbaoyan       │
│   - 项目 D:\code\csbaoyan         │ ─▶ │   - python http.server :3002       │
│   - qq_dump_db D:\code\qq_dump_db │scp │   - systemd: csbaoyan-web           │
│   - 计划任务 CsBaoyanDaily 06:30  │    │                                    │
└──────────────────────────────────┘    └──────────────┬───────────────────┘
                                                       │
                                        ┌──────────────▼───────────────────┐
                                        │ ③ Cloudflare（两个账号！）         │
                                        │   账号A: byocc.cc + byocc 隧道     │
                                        │   账号B: csbaoyan.cn + csbaoyan2   │
                                        │        隧道(3d1a7c6e) → :3002      │
                                        └───────────────────────────────────┘
```

**数据流**：台式机解密本地 QQ 库 → ingest 抽取消息 → DeepSeek 生成日报 → scp 上传 `.md` 到服务器 → 服务器经 Cloudflare 隧道对外提供 `https://csbaoyan.cn`。

---

## 2. 机器清单（当前实例）

| 角色 | 主机 | 访问方式 | 关键路径/服务 |
|------|------|----------|---------------|
| 数据源 | 台式机 COOKIESHEEP | `ssh desktop`（端口 2222，用户 wqf18） | `D:\code\csbaoyan`、`D:\code\qq_dump_db`、计划任务 `CsBaoyanDaily` |
| 托管 | 华为云 byocc | `ssh byocc`（root@122.9.99.104:6543） | `/var/www/csbaoyan`、systemd `csbaoyan-web` + `cloudflared-csbaoyan` |
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
- **计划任务 `CsBaoyanDaily`**，每天 **06:30**（北京时间），以 wqf18 身份（密码登录，开机即跑，`-StartWhenAvailable` 错过会补跑）。
- **计划任务 `CSBaoyan-QQ-Autostart`**，当前用户登录时直接启动 `D:\QQ_data\QQNT\QQ.exe`，让 QQ 生命周期不依赖 SSH 窗口；日报脚本仍保留缺进程时自动拉起的第二道兜底。
- 执行 `daily_auto.ps1`（默认生成**昨天**的日报）：
  1. `dump_qq_key_auto.py --qq 2272735608` 解密
  2. `cli pipeline --skip-commit --skip-push` 生成日报
  3. `scp` 上传 `<日期>.md` + `reports.json` 到服务器

### 3.3 前置依赖（必须满足）
- **QQ 桌面端保持登录运行**（解密要读 `QQ.exe` 进程内存提密钥）。建议设 QQ 开机自启。
- 台式机开机 / 未休眠（06:30 能触发）。
- 能访问 DeepSeek API（出报用）与服务器 6543 端口（上传用）。

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

**只重新生成不重新解密**（密钥没变、库已解密）：
```powershell
cd D:\code\csbaoyan
$env:PYTHONPATH="src"
.venv\Scripts\python.exe -m csbaoyan_daily.cli pipeline --skip-commit --skip-push --date 2026-07-30
```

**查任务状态/日志**：
```powershell
Get-ScheduledTaskInfo -TaskName CsBaoyanDaily   # LastTaskResult=0 即成功
Get-ScheduledTask -TaskName CSBaoyan-QQ-Autostart  # 正常登录后应为 Running
Get-Content D:\code\csbaoyan\logs\daily_2026-07-29.txt -Tail 20
```

**手动触发一次任务**：`Start-ScheduledTask -TaskName CsBaoyanDaily`

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
| `csbaoyan-web` | 静态站（python http.server） | 127.0.0.1:3002 |
| `cloudflared-csbaoyan` | Cloudflare 隧道（csbaoyan2） | 出站 |
| `cloudflared`（byocc，账号A） | byocc.cc 隧道 | 出站 |

> ⚠️ `cloudflared`（byocc）是**你的另一个生产服务**，勿碰。

### 4.2 常用操作（在服务器上，root）

**重启静态站**：`systemctl restart csbaoyan-web`

**重启 csbaoyan 隧道**：`systemctl restart cloudflared-csbaoyan`

**本地验证静态站**：`curl -I http://127.0.0.1:3002/`（应 200）

**隧道连接状态**：
```bash
cloudflared tunnel info 3d1a7c6e-8ec4-4f0a-bd24-4f90be115477   # 看 CONNECTIONS
```

**外网验证**：`curl -I https://csbaoyan.cn/`（应 200）

### 4.3 配置文件位置
- 隧道配置：`/root/.cloudflared/csbaoyan-config.yml`（含 `protocol: http2`，必须！否则 QUIC 在某些网络下连不上）
- 网站根目录：`/var/www/csbaoyan/`（前端 `index.html`/`app.js` + `data/reports/`）
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
- [ ] 服务器：`systemctl is-active csbaoyan-web cloudflared-csbaoyan` 都 active
- [ ] DeepSeek 余额充足（出报消耗 token）

---

## 7. 故障排查（分层诊断）

### 症状：网站打不开 / 502 / 530 / 1033
按层从下往上查（在服务器上）：
```bash
curl -I http://127.0.0.1:3002/          # ① 静态站活着？(应200)
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
3. 看 `D:\code\csbaoyan\logs\daily_<日期>.txt`：解密是否 18 OK、pipeline 是否完成、scp 是否 exit=0
4. 若「未找到日期的导出文件」→ 那天 QQ 没同步到消息（机器关过？），QQ 登录拉一下离线消息后补跑

生产脚本检测不到 `QQ.exe` 时，会先通过公共桌面或开始菜单快捷方式自动启动 QQ，等待登录和消息同步后再解密。该机制依赖 Windows 用户已经登录且 QQ 保存了登录状态；若自动登录失效，任务仍会安全失败并在日志写入 `QQ_AUTO_START_FAILED` 或 `DECRYPT_FAILED`，不会复用旧数据库。

### 症状：DeepSeek 报错（生成失败）
- 当前模型名使用 `deepseek-v4-flash` 或 `deepseek-v4-pro`；`deepseek-chat` / `deepseek-reasoner` 已停用，生产脚本会在调用前给出 `MODEL_CONFIG_INVALID`。
- `.env` 的 `OPENAI_API_KEY` 是主 Key；可选 `OPENAI_FALLBACK_API_KEY` 仅在主 Key 明确返回余额/配额不足时启用。普通超时、网络错误、429 限流不会切换，避免双 Key 重复消耗。
- 客户端对 DeepSeek 采用直连，不继承 Windows 用户代理；若直连失败，先检查 `curl.exe --noproxy '*' https://api.deepseek.com` 和本机网络。
- 临时调并发：`pipeline --model deepseek-v4-flash --max-workers 2`

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

**日报本身**：`pages/data/reports/*.md` 在台式机和服务器各一份，天然双备份；可定期 git 提交做第三份。

**重建最小集**（灾难恢复）：
1. 新 Windows 机：装 NTQQ + 登录 QQ → 部署项目 + qq_dump_db → `.env` → `ingest --inspect` 校准 → 计划任务
2. 服务器：`pages/` 进 `/var/www/csbaoyan` → 起 `csbaoyan-web` → 账号B建隧道 → CNAME
3. 台式机→服务器 SSH 密钥

---

## 9. 安全清单
- [ ] DeepSeek API key 定期轮换（不要明文外泄）
- [ ] 台式机 SSH 密码、服务器 root 强密码 / 改密钥登录
- [ ] `csbaoyan_upload_key` 仅用于上传，权限 600
- [ ] 解密产物 `output/<QQ>/nt_msg.db` 含明文聊天，勿提交 git、勿外传（`.gitignore` 已含 `chat_exports/`）
