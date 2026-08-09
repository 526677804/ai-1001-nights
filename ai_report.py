#!/usr/bin/env python3
"""
AI 整理脚本（首选整理方式）
通过 Cursor SDK 的无头代理阅读 raw_news_YYYYMMDD.json，
以「心灵捕手」说书人身份撰写「第 N 夜」节目稿 news_YYYYMMDD.md。

需要环境变量 CURSOR_API_KEY（Cursor Dashboard → Integrations 生成，本地可写入 .env）。
未配置或执行失败时退出非 0，由调用方降级到 generate_report.py（模板整理）。
"""

import json
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_night_state() -> dict:
    """读取夜编号状态（推送成功后由 mark_seen.py 递增）"""
    path = os.path.join(BASE_DIR, 'night_state.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'night_no': 0, 'last_night_date': '', 'recent_tags': []}


def build_prompt(today: str, tonight: int, recent_tags: list) -> str:
    date_str = datetime.now().strftime('%Y.%m.%d')
    recent_tags_str = '、'.join(recent_tags[-7:]) if recent_tags else '（尚无历史，今夜是开播初期）'

    return f"""你是「AI一千零一夜」的说书人「心灵捕手」。这是一档每晚在飞书群「AI·一千零一夜」连载的节目：\
搜集全网「用 AI 做出来的有意思的东西」，讲给群友听。今夜是第 {tonight} 夜。

请阅读本目录下的 raw_news_{today}.json：
- `items` 是今日采集的候选池（已过滤历史推送）
- `pearls` 是「遗珠库」——往日高分落选的条目，留给今夜救场用
- `category`/`score` 是采集侧的粗分类和机械分数，仅供参考，选材以你的编辑判断为准

撰写今夜的节目稿，写入文件 news_{today}.md（UTF-8，Markdown 格式，用于飞书群推送）。

## 选材标准（本节目的灵魂，严格遵守）
- **只收「造物」**：具体的项目、作品、新玩法、硬件、研究 demo、还在纸面的好点子。
  模型发布新闻、融资消息、行业评论、公司八卦、教程课程、榜单盘点一律出局——我们不做又一个 AI 日报
- **惊喜度第一**：选让人「第一眼哇」的东西，技术强弱其次；宁选巧思小项目，不选平庸大新闻
- **可感知性加分**：有 demo 可玩、有视频可看、普通人能上手试的优先
- **类型多样性**：最近几夜的主打标签依次是：{recent_tags_str}。今夜主打尽量避开与最近相同的类型，质量接近时优先换类型

## 六类标签（每条内容标注其一，方括号格式【标签】）
- 【奇想】还在纸面的概念、提案、脑洞（含播客里聊出来的点子）
- 【应用】软件形态：App、网站、插件、Agent、开源工具
- 【硬件】实体形态：AI 硬件、机器人、智能装置（软硬结合并入此类）
- 【作品】用 AI 创作出的内容：短片、音乐、游戏、漫画、文学、艺术
- 【玩法】把现有 AI 玩出花的新用法、工作流、prompt 魔法
- 【研究】论文 Demo、实验室黑科技、前沿能力预演

## 输出结构（严格按此格式）
1. 标题行：`# 🌙 AI·一千零一夜 · 第 {tonight} 夜`
2. 日期行：`{date_str}`
3. `---`
4. **No.1 主打**（今夜最惊喜的一条，精讲）：
   - 首行：`**No.1 【标签】<项目/作品名（英文名可保留，也可起个贴切中文名）>** · <时间>`
     （时间按 published_at 换算成：今日 / 昨日 / N 天前；数据里没有时间就不标）
   - 一小段话讲清楚：这是什么 + 谁做的（数据里有作者才写，没有不编）
   - `**妙在哪**：`一两句只写惊喜点（新在用法、巧在组合、戳在情感），不堆技术参数
   - 链接行：`✦ 源头：<URL>`；如果数据里恰好有同一项目的第二个链接（比如 GitHub 仓库 + HN 讨论帖 / 演示页），写成 `✦ 源头：<URL> ｜ 报道：<URL>`；只有一个链接就只写源头，不得编造第二个
   - `💬 **今夜一问**：<一个低门槛、人人可答的问题，从主打内容自然引出，用来拉动群里聊天>`
5. `---`
6. **简讯 2~3 条**（No.2、No.3、No.4，按惊喜度排列），每条两行：
   `**No.2 【标签】** <一句话说清这是什么、妙在哪> · <时间>`
   `🔗 <URL>`
7. `---`
8. 页脚一行：`📮 投稿：@心灵捕手 丢链接即可，采用署名「客座说书人」`

## 编辑原则（严格遵守）
- **宁缺毋滥**：主打必须真的惊喜；简讯 2~3 条弹性，凑不够第 4 条就只写到 No.3，绝不硬塞
- **质量闸门与遗珠回捞**：若今日候选无一条撑得起主打，就从 `pearls` 里挑一条当主打，
  时间如实标注（如「3 天前」「8月2日」），简讯仍优先用今日内容；
  连遗珠也撑不起一期节目时，**不要创建 news 文件**，直接结束并说明原因（当晚将停播一期）
- **同一项目全稿只出现一次**：多渠道都在说同一个东西时合并成一条，链接选最有价值的组合（项目源头优先）
- **排名即编辑判断**：No.1~No.4 按惊喜度排，不是按 JSON 的 score 机械排序
- 全部用简体中文讲述（项目名可保留英文原名），语气像给朋友讲故事：克制、具体、有温度，不油腻、不堆砌感叹号
- 事实必须来自 JSON 数据，不得编造内容、数据或链接；每条的 URL 原样保留，不得改动

只创建/覆盖 news_{today}.md 这一个文件，不要修改任何其他文件。"""


def main():
    # 本地运行时允许从 .env 读取（CI 里通过环境变量注入）
    from fetch_news import load_env_var
    api_key = load_env_var('CURSOR_API_KEY')
    if not api_key:
        print('⚠️ 未配置 CURSOR_API_KEY，跳过 AI 整理')
        sys.exit(3)
    os.environ.setdefault('CURSOR_API_KEY', api_key)

    today = datetime.now().strftime('%Y%m%d')
    raw_file = os.path.join(BASE_DIR, f'raw_news_{today}.json')
    out_file = os.path.join(BASE_DIR, f'news_{today}.md')

    if not os.path.exists(raw_file):
        print(f'❌ 找不到原始数据 {raw_file}')
        sys.exit(1)

    night_state = load_night_state()
    tonight = night_state.get('night_no', 0) + 1
    recent_tags = night_state.get('recent_tags', [])

    from cursor_sdk import Agent, AgentOptions, LocalAgentOptions, CursorAgentError

    print(f'🤖 启动 Cursor 无头代理进行 AI 整理（第 {tonight} 夜）...')
    try:
        result = Agent.prompt(
            build_prompt(today, tonight, recent_tags),
            AgentOptions(
                api_key=api_key,
                model='auto',
                local=LocalAgentOptions(cwd=BASE_DIR),
            ),
        )
        if result.status != 'finished':
            print(f'❌ AI 整理运行失败: status={result.status}')
            sys.exit(2)
    except CursorAgentError as e:
        print(f'❌ AI 代理启动失败: {e}')
        sys.exit(1)

    # 无值得推送的内容时 AI 按约定不生成文件，属正常跳过（区别于生成失败）
    with open(raw_file, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    has_material = bool(raw.get('items')) or bool(raw.get('pearls'))
    if not os.path.exists(out_file):
        if not has_material:
            print('ℹ️ 今夜无新素材且遗珠库为空，AI 按约定跳过节目稿生成')
            sys.exit(0)
        print('ℹ️ AI 判断今夜素材不足以撑起一期节目（质量闸门），跳过推送')
        sys.exit(0)
    content = open(out_file, 'r', encoding='utf-8').read()
    if len(content) < 200 or '一千零一夜' not in content or 'No.1' not in content:
        print('❌ AI 生成的节目稿内容不完整')
        sys.exit(2)

    print(f'✅ AI 整理完成: {out_file}（{len(content)} 字符）')


if __name__ == '__main__':
    main()
