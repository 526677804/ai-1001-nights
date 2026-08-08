#!/usr/bin/env python3
"""
状态维护脚本（每次运行结束后执行，CI 会把状态文件 commit 回仓库）：

1. seen_urls.json —— 把当天采集到的所有 URL 记入已见记录。
   已见过的内容永不重发（没见过比刚发生更重要），记录永久保留。
2. night_state.json —— 当晚实际推送成功（存在 news_*.md）时：夜编号 +1，
   并从节目稿中提取主打标签，维护「最近几夜主打标签」窗口（类型多样性轮换用）。
3. pearls.json —— 遗珠库：当天高分落选条目自动入库（旱季回捞用）；
   已被节目稿采用的、超过保留期的自动出库，库容量有上限。
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_FILE = os.path.join(BASE_DIR, 'seen_urls.json')
NIGHT_FILE = os.path.join(BASE_DIR, 'night_state.json')
PEARLS_FILE = os.path.join(BASE_DIR, 'pearls.json')

TAG_PATTERN = re.compile(r'【(奇想|应用|硬件|作品|玩法|研究)】')


def load_json(path: str, default: dict) -> dict:
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return default


def save_json(path: str, data: dict):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    config = load_json(os.path.join(BASE_DIR, 'config.json'), {})
    quality = config.get('quality', {})
    pearls_per_day = quality.get('pearls_per_day', 5)
    pearls_max = quality.get('pearls_max', 50)
    pearls_retention_days = quality.get('pearls_retention_days', 30)
    recent_tags_window = quality.get('recent_tags_window', 7)

    today = datetime.now().strftime('%Y%m%d')
    raw_file = os.path.join(BASE_DIR, f'raw_news_{today}.json')

    if not os.path.exists(raw_file):
        print(f"❌ 找不到 {raw_file}")
        sys.exit(1)

    with open(raw_file, 'r', encoding='utf-8') as f:
        raw = json.load(f)

    # 节目稿存在 = 当晚实际推送成功（workflow 里推送失败会中断，不会执行到本脚本）
    news_file = os.path.join(BASE_DIR, f'news_{today}.md')
    pushed = os.path.exists(news_file)
    md_content = ''
    if pushed:
        with open(news_file, 'r', encoding='utf-8') as f:
            md_content = f.read()

    items = raw.get('items', [])

    # ---- 1. 遗珠库维护（先于 seen 记录，基于「本次落选」判断）----
    pearls_data = load_json(PEARLS_FILE, {'updated_at': '', 'pearls': []})
    pearls = pearls_data.get('pearls', [])

    # 出库：已被节目稿采用的、超过保留期的
    cutoff = (datetime.now() - timedelta(days=pearls_retention_days)).strftime('%Y%m%d')
    before = len(pearls)
    pearls = [p for p in pearls
              if p.get('url') and p['url'] not in md_content
              and p.get('added_date', today) >= cutoff]
    removed = before - len(pearls)

    # 入库：当天高分落选条目（未被节目稿采用），每天最多 pearls_per_day 条
    existing_urls = {p['url'] for p in pearls}
    candidates = [i for i in items
                  if i.get('url') and i['url'] not in md_content
                  and i['url'] not in existing_urls]
    candidates.sort(key=lambda x: x.get('score', 0), reverse=True)
    added_pearls = 0
    for item in candidates[:pearls_per_day]:
        pearls.append({
            'title': item.get('title', ''),
            'url': item['url'],
            'source': item.get('source', ''),
            'summary': item.get('summary', ''),
            'published_at': item.get('published_at', ''),
            'score': item.get('score', 0),
            'category': item.get('category', ''),
            'added_date': today,
        })
        added_pearls += 1

    # 容量上限：保留最新入库的
    if len(pearls) > pearls_max:
        pearls = sorted(pearls, key=lambda p: p.get('added_date', ''), reverse=True)[:pearls_max]

    pearls_data['pearls'] = pearls
    pearls_data['updated_at'] = datetime.now().isoformat()
    save_json(PEARLS_FILE, pearls_data)
    print(f"✅ 遗珠库更新：入库 {added_pearls} 条，出库 {removed} 条，现存 {len(pearls)} 条")

    # ---- 2. 夜编号与主打标签窗口 ----
    night = load_json(NIGHT_FILE, {'night_no': 0, 'last_night_date': '', 'recent_tags': []})
    if pushed:
        night['night_no'] = night.get('night_no', 0) + 1
        night['last_night_date'] = today
        m = TAG_PATTERN.search(md_content)
        if m:
            tags = night.get('recent_tags', [])
            tags.append(m.group(1))
            night['recent_tags'] = tags[-recent_tags_window:]
        save_json(NIGHT_FILE, night)
        print(f"✅ 夜编号更新：第 {night['night_no']} 夜已播出"
              f"（主打标签: {m.group(1) if m else '未识别'}）")
    else:
        print("ℹ️ 今夜未推送，夜编号不变")

    # ---- 3. 已见记录（永不重发，永久保留）----
    seen = load_json(SEEN_FILE, {'updated_at': '', 'urls': {}})
    urls = seen.get('urls', {})

    added = 0
    for item in items:
        url = item.get('url', '')
        if url and url not in urls:
            urls[url] = today
            added += 1
    # 被节目稿采用的遗珠也记入已见（用过的珠子不再回捞）
    for item in raw.get('pearls', []):
        url = item.get('url', '')
        if url and url in md_content and url not in urls:
            urls[url] = today
            added += 1

    seen['urls'] = urls
    seen['updated_at'] = datetime.now().isoformat()
    save_json(SEEN_FILE, seen)
    print(f"✅ 已见记录更新：新增 {added} 条，总计 {len(urls)} 条（永久保留，永不重发）")


if __name__ == '__main__':
    main()
