# XHS Agent 测试网页

公网测试域名：**https://xhs_agent_test.41box.com**

本地：`http://127.0.0.1:8791`

## 功能

- **配置**：TikHub Token、DeepSeek Key、模型选择
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

## 数据

- 配置：`data/webapp/runtime_config.json`（gitignore）
- 评论库：`data/webapp/comments.db`（SQLite）
