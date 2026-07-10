# 人审产物格式（金标）

每条金标一行 JSON（JSONL），建议路径：`gold/new_car/vNNN/items.jsonl`（按**通用新车**场景沉淀，便于跨车型复用）。

## 必填字段

```json
{
  "gold_id": "new_car:v001:note_xxx",
  "scenario_id": "new_car",
  "product_id": "mona_l03",
  "case_product": "mona_l03",
  "skill_version": "content_sentiment_new_car_v0.1",
  "note_id": "...",
  "post_snapshot": {
    "note_id": "...",
    "title": "...",
    "body": "...",
    "published_at": "...",
    "author_nickname": "...",
    "city": "...",
    "like_count": 0,
    "comment_count": 0,
    "content_type": "note",
    "source_keyword": "..."
  },
  "judge_raw": { },
  "ai_review": { "flags": [], "priority": "high|mid|low" },
  "human_label": {
    "sentiment_polarity": "positive|neutral|negative|mixed",
    "sentiment_intensity": 1,
    "aspects": [],
    "competitor_mentions": [],
    "brand_stance": { "own": "unclear", "overall": "neutral" },
    "content_role": "owner_review",
    "opinion_risk": "low",
    "summary": "...",
    "reason": "...",
    "confidence": 1.0
  },
  "human_notes": "修正理由 / skill 补丁说明",
  "reviewer": "name_or_id",
  "reviewed_at": "ISO-8601"
}
```

## 流程建议

1. `csl-lab review-queue --judgements data/judgements/xxx.jsonl` 生成待审队列。
2. 优先处理 `priority=high`。
3. 将终审结果追加到 `gold/{scenario}/v001/items.jsonl`；**post_snapshot 不可变**。
4. 同步把可复用的规则写回 `scenarios/.../skill.md`，再跑 `csl-lab eval`。
