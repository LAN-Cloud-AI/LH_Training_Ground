# LH Training Ground

小红书**帖子级情感**训练场（原 `content_sentiment_lab`），从 LeadsHunter / LH_evaluation_agent 中独立出来的公开仓库。

- **仓库**：[LAN-Cloud-AI/LH_Training_Ground](https://github.com/LAN-Cloud-AI/LH_Training_Ground)
- **关联私有仓**：
  - [LAN-Cloud-AI/leadsHunter](https://github.com/LAN-Cloud-AI/leadsHunter)
  - [LAN-Cloud-AI/LH_evaluation_agent](https://github.com/LAN-Cloud-AI/LH_evaluation_agent)
- **测试台**：https://xhs_agent_test.41box.com （本地 `127.0.0.1:8791`）

方案背景见 leadsHunter 文档 `docs/task16-小红书帖子级情感分析-技术方案.md`。

## 架构：场景（行业）+ 产品案例（SKU）

| 层 | 路径 | 作用 |
|----|------|------|
| **场景 = 行业** | `scenarios/{id}/` | skill / schema / 打标规则；行业差异写在这里 |
| **产品案例 = SKU** | `scenarios/{id}/products/*.yaml` | 本品/竞品/爬取关键词；只换车型不改规则 |

内置场景：

- `new_car`（新车）：排除二手求购、已成交复盘等
- `used_car`（二手车）：二手求购/收车为有效潜客；排除新车蹲销售/提新车

换一款车：复制 `products/mona_l03.yaml` → `products/your_model.yaml`，改品牌/车系/关键词即可，**不必改 skill**。  
新增行业：在测试台爬取页手填场景 ID/中文名，或调用 `POST /api/scenarios/ensure`；也可手动建 `scenarios/{id}/`。

## 能力

1. **crawl**：TikHub 搜索 + `note_detail` → `PostRecord` 本地 JSONL（带 `scenario_id`）
2. **judge**：按场景 skill 初判（`fake` / `deepseek`），intent 按 `scenario_id` 分支
3. **review-queue**：AI 预筛异常，供人审
4. **eval**：对照 seed / 金标
5. **dry-run**：离线演示
6. **webapp**：爬取页最前选场景 → 产品 → 关键词；评论库写入 `scenario_id` / `product_id`

**默认不写**生产 `leads` / `llm_annotations`。

## 快速开始

```bash
cd /Users/i/myCode/LH_Training_Ground   # 或 git clone 后的路径
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # 填入 TikHub / DeepSeek（勿覆盖生产 agent/.env.local）

csl-lab list-products --scenario new_car
csl-lab dry-run --scenario new_car --product mona_l03
csl-lab eval --scenario new_car --product mona_l03 --provider fake
```

真实爬取（会计费）：

```bash
csl-lab crawl --scenario new_car --product mona_l03
csl-lab crawl --scenario used_car --product your_used_sku
```

Web 控制台：

```bash
./scripts/run-webapp.sh
# 或 LaunchAgent: com.lh.xhs-agent-test-webapp
```

兼容旧命令：`--scenario mona_l03_new_car` 会映射为 `new_car` + `mona_l03`。

## 如何新增行业

1. UI：爬取页「场景」输入新 ID 或中文名 → 爬取/判断时自动 `ensure` 骨架
2. API：`POST /api/scenarios/ensure`，body `{"scenario_id":"ev_battery","display_name":"动力电池"}`
3. 手写：复制 `scenarios/used_car/`，改 `scenario.yaml` / `skill.md`
4. 意向映射：在 `src/csl_lab/webapp/intent.py` 为新 `scenario_id` 增加分支

## 人审

见 `review/human_review_schema.md`。金标建议落 `gold/new_car/v001/`。

## 测试

```bash
pytest -q
```
