# 独立读者计数器（发行量）

「保研日报」的访客计数服务：按**人头**计数（cookie 去重），不按访问次数。
零第三方依赖，一个 Python 文件，标准库直跑。

## 口径

- 首次访问（无 `csbaoyan_vid` cookie）→ 下发一年期 cookie，计数 +1
- 再次访问 / 刷新（有 cookie）→ 只读当前总数，**不重复计数**
- 同一 IP 在 `--rate-limit-seconds`（默认 10s）窗口内至多计 1 次，防止脚本刷量
- 清除浏览器 cookie 后再访问会计为新读者——这是所有 cookie 方案的上限，前端已标注「仅作参考」
- 落盘文件只有 `{"visitors": N}` 一个整数，**不存 IP / UA / 指纹**

## API

| 方法 | 路径 | 行为 |
|------|------|------|
| POST | `/count` | 无 cookie：+1 并 Set-Cookie；有 cookie：只读 |
| GET | `/count` | 只读当前总数 |

## 本地试跑

```bash
python3 visit_counter.py --port 8001 --data-dir ./data
curl -X POST http://127.0.0.1:8001/count   # → {"visitors": 1}，响应带 Set-Cookie
curl -X POST http://127.0.0.1:8001/count   # → {"visitors": 1}（同 IP 限流内不加数）
curl http://127.0.0.1:8001/count           # → {"visitors": 1}
```

## 服务器部署（csbaoyan.cn）

### 1. 上传

```bash
# 本地（repo 根目录执行）
ssh -p 6543 root@122.9.99.104 "mkdir -p /opt/csbaoyan-counter/data"
scp -P 6543 counter/visit_counter.py root@122.9.99.104:/opt/csbaoyan-counter/
```

服务器只需 Python 3.8+（`python3 --version` 确认），无需 pip 装任何东西。

### 2. systemd 常驻

新建 `/etc/systemd/system/csbaoyan-counter.service`：

```ini
[Unit]
Description=CS Baoyan visitor counter
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/csbaoyan-counter/visit_counter.py --host 127.0.0.1 --port 8001 --data-dir /opt/csbaoyan-counter/data
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now csbaoyan-counter
curl -X POST http://127.0.0.1:8001/count   # 应答 {"visitors": 1}
```

### 3. nginx 反代

在 csbaoyan.cn 站点的 `server` 块里加：

```nginx
location = /api/count {
    proxy_pass http://127.0.0.1:8001/count;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

`X-Forwarded-Proto` 让 cookie 在 https 站点上自动附加 `Secure` 属性。

```bash
nginx -t && systemctl reload nginx
```

### 4. 验证

打开 https://csbaoyan.cn —— 首页 Readers 卡与印房「累计大盘」的 Readers 卡应显示数字；
刷新页面数字**不变**；换无痕窗口（或清 cookie）再开，+1。

## 注意

- 服务只应监听 `127.0.0.1`（默认如此），由 nginx 反代对外；直接暴露端口可被伪造
  `X-Forwarded-For` 刷量
- GitHub Pages 镜像没有后端，Readers 卡会一直显示「—」，属预期降级
- 想重置计数：`systemctl stop csbaoyan-counter`，删掉 `data/count.json` 再 start
