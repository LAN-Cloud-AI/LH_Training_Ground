---
title: LeadsHunter模型训练场 · Web 控制台
type: guide
status: current
owner: Kaison
updated: 2026-08-01
related:
  - README.md
---
# LeadsHunter模型训练场 · Web 控制台

公网域名：**https://xhs_agent_test.41box.com**（已套 **Cloudflare Access**）

本地：`http://127.0.0.1:8791`（不经 Access，仅本机）

英文名：**LeadsHunter Model Training Ground**

## Cloudflare Access

| 项 | 值 |
|----|----|
| 应用名 | LeadsHunter Model Training Ground |
| 域名 | `xhs_agent_test.41box.com` |
| Team | `long-sky-131d.cloudflareaccess.com` |
| 登录方式 | **Cloudflare** / **GitHub** / Email one-time PIN |
| Passkey / Independent MFA | **已关闭** |
| 允许邮箱 | `i@ios.moe`、`sxszbxk@gmail.com`、`mingxuan400@gmail.com` |
| Session | 24h |

登录页应看到：`Sign in with: Cloudflare`、`GitHub`，以及 Email / Send login code。

用 Cloudflare / GitHub 登录时，账号绑定邮箱必须在允许名单内，否则会提示无权限。GitHub 以账号的 **primary / verified email** 匹配白名单。

要加同事：网页「用户管理」增删邮箱。

## 功能

- **配置**：TikHub Token、DeepSeek Key、模型选择、Cloudflare API Token
- **用户管理**：增删 Access 允许邮箱（同步训练场 + App Launcher）
- **爬取**：自定义关键词，只爬帖子（搜索 + note_detail），不爬评论
- **判断 / 评论库**：DeepSeek 初判 → 映射「有意向/没意向」入库；可开人工纠错开关写回纠错记录

## 启动

LaunchAgent：`com.lh.xhs-agent-test-webapp`（KeepAlive）

```bash
launchctl print gui/$(id -u)/com.lh.xhs-agent-test-webapp
curl http://127.0.0.1:8791/api/health
```

手动：

```bash
./scripts/run-webapp.sh
```

## Tunnel

`~/.cloudflared/config-leadshunter-mac-studio.yml` 中：

```yaml
- hostname: xhs_agent_test.41box.com
  service: http://127.0.0.1:8791
```

DNS 路由到 tunnel `leadshunter-mac-studio`。

## 用户管理（Access 邮箱）

网页「用户管理」页可增删 Cloudflare Access 允许邮箱，同步更新：

- 训练场应用 `xhs_agent_test.41box.com`
- App Launcher

需在「配置」页填写 **Cloudflare API Token**（或环境变量 `CLOUDFLARE_API_TOKEN`），权限：

- Account → Access: Apps and Policies → Edit
- Account → Access: Organizations, Identity Providers, and Groups → Read

至少保留一个邮箱，避免把自己锁出。

## 数据

- 配置：`data/webapp/runtime_config.json`（gitignore）
- 评论库：`data/webapp/comments.db`（SQLite）
