# AI一千零一夜 🌙

一个搜集全网「用 AI 做出来的有意思的东西」的智能体。每晚 19:56，说书人「心灵捕手」在飞书群
「AI｜一千零一夜」开讲「第 N 夜」：1 条主打精讲 + 2~3 条简讯，排名制连载，脑洞创意优先。

## 节目形态

- **第 N 夜连载**：夜编号持久化（`night_state.json`），推送成功才递增
- **排名制**：No.1 主打（是什么 / 谁做的 / 妙在哪 / 双链接 / 今夜一问）+ No.2~4 简讯
- **六类标签**：奇想 / 应用 / 硬件 / 作品 / 玩法 / 研究，连续同类自动降权轮换
- **只收造物**：新闻、融资、评论、教程一律出局
- **质量闸门**：当日无惊喜内容时自动回捞「遗珠库」（`pearls.json`）；连遗珠也不行则停播一期，拒发平庸
- **永不重发**：已见 URL 永久记录（`seen_urls.json`）

## 流水线（每晚自动执行一次）

```
fetch_news.py ──→ raw_news_YYYYMMDD.json   （9 路信息源采集 + 去重 + 过滤已推送 + 注入遗珠库）
      │
ai_report.py（首选）/ generate_report.py（降级） ──→ news_YYYYMMDD.md（「第 N 夜」节目稿）
      │
push_to_feishu.py ──→ 飞书群（失败私信管理员）
      │
mark_seen.py ──→ seen_urls.json / night_state.json / pearls.json（CI 提交回仓库）
```

## 信息源（9 路）

| 渠道 | 接入方式 |
|------|----------|
| Hacker News (Show HN) | Algolia API |
| Product Hunt | 官方 RSS |
| GitHub 新项目 | Search API（近 7 天新建 + star 门槛） |
| HuggingFace | Spaces trending + Daily Papers API |
| 即刻 AI探索站 | RSSHub 路由（多实例回退） |
| X (Twitter) AI builder 账号组 | twitterapi.io 主 + nitter RSS 备 |
| Reddit (LocalLLaMA / StableDiffusion) | RSS 端点 |
| KOL 博客 / Newsletter | 原生 RSS（Simon Willison / 量子位 / Hackaday / Ben's Bites） |
| 播客 show notes | 原生 RSS（科技早知道 / OnBoard! / Latent Space） |

## 调度

- **主触发**：妙搭定时触发器每晚北京时间 19:56 调用 `workflow_dispatch`
- **备份**：GitHub cron UTC 12:56（北京 20:56），guard job 检查当天已成功运行则跳过
- 状态文件由 Actions 以 github-actions bot 身份 commit 回仓库（`[skip ci]`）

## 本地运行

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入 TWITTERAPI_IO_KEY、CURSOR_API_KEY（可选）
python3 test_sources.py                          # 信息源体检
python3 fetch_news.py                            # 采集
python3 ai_report.py || python3 generate_report.py  # 整理（AI 优先，自动降级）
python3 push_to_feishu.py                        # 推送（需 lark-cli 已配置 bot 身份）
python3 mark_seen.py                             # 更新状态
```

## CI Secrets（GitHub Actions）

| Secret | 用途 |
|--------|------|
| `LARK_APP_ID` / `LARK_APP_SECRET` | lark-cli bot 身份（飞书推送） |
| `TWITTERAPI_IO_KEY` | X 采集主途径 |
| `CURSOR_API_KEY` | AI 说书人整理（缺省自动降级模板） |
