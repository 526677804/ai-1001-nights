#!/usr/bin/env python3
"""
节目稿生成脚本（降级模式）
从 raw_news_YYYYMMDD.json 生成 news_YYYYMMDD.md（「第 N 夜」排名制格式）。

生产环境的首选整理方式是心灵捕手（ai_report.py，有编辑判断、质量闸门与遗珠回捞），
本脚本是无 AI 环境下的兜底方案：按机械分数排出 No.1 主打 + No.2~4 简讯，
保证定时任务链路（采集 → 整理 → 推送）始终可用、连载不断更。
"""

import json
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 采集侧粗分类 → 六类标签的机械映射（降级模式没有编辑判断，只求不离谱）
CATEGORY_TAG = {
    'tools': '🛠【应用】',
    'research': '🔬【研究】',
    'community': '✨【玩法】',
    'media': '✨【玩法】',
    'podcast': '💭【奇想】',
}


def load_config() -> dict:
    with open(os.path.join(BASE_DIR, 'config.json'), 'r', encoding='utf-8') as f:
        return json.load(f)


def load_night_state() -> dict:
    path = os.path.join(BASE_DIR, 'night_state.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'night_no': 0, 'last_night_date': '', 'recent_tags': []}


def item_tag(item: dict) -> str:
    return CATEGORY_TAG.get(item.get('category', ''), '🛠【应用】')


def main():
    today = datetime.now().strftime('%Y%m%d')
    raw_file = os.path.join(BASE_DIR, f'raw_news_{today}.json')

    if not os.path.exists(raw_file):
        print(f"❌ 找不到原始数据: {raw_file}，请先运行 fetch_news.py")
        sys.exit(1)

    with open(raw_file, 'r', encoding='utf-8') as f:
        raw = json.load(f)

    items = raw.get('items') or []
    pearls = raw.get('pearls') or []

    # 今夜素材：优先当日候选池；候选池为空时机械回捞遗珠库（仪式感不断更）
    from_pearls = False
    pool = items
    if not pool and pearls:
        pool = pearls
        from_pearls = True

    # 宁缺毋滥：连遗珠也没有时不生成节目稿（调用方据此跳过推送）
    if not pool:
        print("ℹ️ 今夜无新素材且遗珠库为空，跳过节目稿生成")
        sys.exit(0)

    night_state = load_night_state()
    tonight = night_state.get('night_no', 0) + 1

    date_str = datetime.now().strftime('%Y.%m.%d')

    ranked = sorted(pool, key=lambda x: x.get('score', 0), reverse=True)
    top = ranked[0]
    briefs = ranked[1:4]

    parts = [
        f"# 🌙 AI · 一千零一夜 · 第 {tonight} 夜 ｜ {date_str}",
        "\n---\n",
    ]

    # No.1 主打
    top_title = top.get('title', '').strip()
    top_line = f"**No.1 {item_tag(top)}{top_title}**"
    if from_pearls:
        top_line += " · 遗珠回捞"
    parts.append(top_line)
    summary = (top.get('summary') or '').strip()
    if summary:
        parts.append('\n' + summary[:200])
    parts.append(f"\n来源：{top.get('source', '')}")
    parts.append(f"\n✦ [源头]({top.get('url', '')})")

    # No.2~4 简讯
    if briefs:
        parts.append("\n---\n")
        for i, item in enumerate(briefs, 2):
            title = item.get('title', '').strip()
            parts.append(f"**No.{i} {item_tag(item)}** {title[:80]}")
            parts.append(f"✦ [源头]({item.get('url', '')})\n")

    output_file = os.path.join(BASE_DIR, f'news_{today}.md')
    content = '\n'.join(parts)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"✅ 节目稿已生成（降级模板模式）: {output_file}（{len(content)} 字符）")


if __name__ == '__main__':
    main()
