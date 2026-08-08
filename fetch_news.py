#!/usr/bin/env python3
"""
AI一千零一夜 · 采集脚本
搜集全网「用 AI 做出来的有意思的东西」，输出结构化原始数据供说书人（AI 整理）挑选。

信息源（9 路）：
  Show HN / Product Hunt / GitHub 新项目 / HuggingFace (Spaces + Daily Papers) /
  即刻 AI 圈子 (RSSHub) / X 账号组 (twitterapi.io + nitter 回退) / Reddit /
  KOL 博客与 Newsletter / 播客 show notes

产出 raw_news_YYYYMMDD.json，其中：
  items  —— 今日候选池（已去重、已过滤历史推送）
  pearls —— 遗珠库（往日高分落选条目，供质量闸门回捞）
"""

import calendar
import json
import os
import subprocess
import requests
import time
import re
import feedparser
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, asdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 部分站点（Reddit RSS、nitter、RSSHub 等）会拒绝非浏览器 UA
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
}


def fetch_feed(url: str, timeout: int = 20) -> feedparser.FeedParserDict:
    """带浏览器 UA 抓取并解析 RSS/Atom feed"""
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def strip_html(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text or '').strip()


def entry_is_fresh(entry, max_age_hours: int) -> bool:
    """判断 feed 条目是否在时间窗口内；无时间信息时默认保留"""
    t = entry.get('published_parsed') or entry.get('updated_parsed')
    if not t:
        return True
    published = datetime.utcfromtimestamp(calendar.timegm(t))
    return datetime.utcnow() - published <= timedelta(hours=max_age_hours)


def load_env_var(name: str) -> str:
    """读取环境变量，取不到时尝试项目目录下的 .env 文件（KEY=VALUE 格式）"""
    value = os.environ.get(name, '')
    if value:
        return value
    env_file = os.path.join(BASE_DIR, '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('#') or '=' not in line:
                    continue
                k, _, v = line.partition('=')
                if k.strip() == name:
                    return v.strip().strip('"').strip("'")
    return ''


def with_retry(func: Callable, max_retries: int = 2, retry_delay: int = 3) -> Callable:
    """
    重试装饰器：函数失败时自动重试
    """
    def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < max_retries:
                    print(f"   ⚠️  第 {attempt + 1} 次失败，{retry_delay}秒后重试...")
                    time.sleep(retry_delay)
                else:
                    print(f"   ❌ 重试 {max_retries} 次后仍然失败")
        raise last_exception
    return wrapper

@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    source_type: str  # official, media, community, tool, kol, research
    reliability: str  # official, high, medium
    summary: str = ""
    published_at: str = ""
    score: int = 0
    category: str = "community"  # tools / research / community / media / podcast（采集侧粗分类，仅供整理参考）


def load_config() -> dict:
    """加载配置文件"""
    with open(os.path.join(BASE_DIR, 'config.json'), 'r', encoding='utf-8') as f:
        return json.load(f)


def match_keywords(text: str, keywords: List[str]) -> bool:
    """
    检查文本是否命中任一关键词。
    英文关键词按词边界匹配（避免 "AI" 误中 email/said 等），中文关键词按子串匹配。
    """
    for kw in keywords:
        if re.search(r'[\u4e00-\u9fff]', kw):
            if kw.lower() in text.lower():
                return True
        elif re.search(r'(?<![A-Za-z0-9])' + re.escape(kw) + r'(?![A-Za-z0-9])',
                       text, re.IGNORECASE):
            return True
    return False


def fetch_hackernews(keywords: List[str], min_points_bypass: int = 20) -> List[NewsItem]:
    """
    Show HN 造物帖：Algolia API 一次拉取近 48 小时全部 Show HN，本地关键词过滤。
    高分帖（points >= min_points_bypass）免关键词过滤——标题不含 AI 字样的造物交给编辑判断。
    """
    since = int(time.time()) - 48 * 3600
    url = (f"https://hn.algolia.com/api/v1/search_by_date"
           f"?tags=show_hn&numericFilters=created_at_i>{since}&hitsPerPage=200")
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=20)
    resp.raise_for_status()

    items = []
    for hit in resp.json().get('hits', []):
        title = hit.get('title') or ''
        if not title:
            continue
        points = hit.get('points', 0) or 0
        if not match_keywords(title, keywords) and points < min_points_bypass:
            continue

        story_id = hit.get('objectID', '')
        items.append(NewsItem(
            title=re.sub(r'^Show HN:\s*', '', title),
            url=hit.get('url') or f"https://news.ycombinator.com/item?id={story_id}",
            source='Show HN',
            source_type='tool',
            reliability='high',
            summary=f"👍 {points} points · 💬 {hit.get('num_comments', 0)} comments · "
                    f"讨论: https://news.ycombinator.com/item?id={story_id}",
            published_at=hit.get('created_at', ''),
            score=min(points, 150),
            category='tools'
        ))

    return sorted(items, key=lambda x: x.score, reverse=True)[:30]


def fetch_producthunt(keywords: List[str], ph_cfg: dict) -> List[NewsItem]:
    """Product Hunt 当日新品（官方 RSS），按关键词过滤出 AI 相关"""
    feed = fetch_feed(ph_cfg.get('feed_url', 'https://www.producthunt.com/feed'))
    max_age = ph_cfg.get('max_age_hours', 36)

    items = []
    for entry in feed.entries:
        if not entry_is_fresh(entry, max_age):
            continue
        title = entry.get('title', '')
        summary = strip_html(entry.get('summary', ''))[:200]
        if not match_keywords(title + ' ' + summary, keywords):
            continue

        items.append(NewsItem(
            title=title,
            url=entry.get('link', ''),
            source='Product Hunt',
            source_type='tool',
            reliability='high',
            summary=summary,
            published_at=entry.get('published', ''),
            score=65,
            category='tools'
        ))

    return items[:15]


def fetch_github_trending(github_cfg: dict) -> List[NewsItem]:
    """GitHub 近一周新建且已有热度的 AI 项目（Search API 的 created/stars 条件在查询里完成）"""
    terms = github_cfg.get('query_terms', ['AI'])
    days = github_cfg.get('created_within_days', 7)
    min_stars = github_cfg.get('min_stars', 15)
    since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    query = ' OR '.join(terms) + f' created:>{since} stars:>{min_stars}'
    resp = requests.get(
        'https://api.github.com/search/repositories',
        params={'q': query, 'sort': 'stars', 'order': 'desc', 'per_page': 20},
        headers={'Accept': 'application/vnd.github.v3+json'},
        timeout=15
    )
    resp.raise_for_status()

    items = []
    for repo in resp.json().get('items', []):
        stars = repo.get('stargazers_count', 0)
        items.append(NewsItem(
            title=f"[{repo['full_name']}] {repo.get('description') or 'No description'}",
            url=repo['html_url'],
            source='GitHub 新项目',
            source_type='tool',
            reliability='high',
            summary=f"⭐ {stars} stars · 新建于 {repo['created_at'][:10]} · 语言: {repo.get('language') or 'N/A'}",
            published_at=repo['created_at'],
            score=min(50 + stars // 10, 150),
            category='tools'
        ))

    return items[:10]


def fetch_huggingface(hf_cfg: dict) -> List[NewsItem]:
    """HuggingFace：trending Spaces（可玩 demo）+ Daily Papers（研究素材）"""
    items = []

    # Trending Spaces
    resp = requests.get(
        'https://huggingface.co/api/spaces',
        params={'sort': 'trendingScore', 'direction': -1,
                'limit': hf_cfg.get('spaces_limit', 20), 'full': 'true'},
        headers=BROWSER_HEADERS, timeout=20
    )
    resp.raise_for_status()
    for sp in resp.json():
        sid = sp.get('id', '')
        if not sid:
            continue
        card = sp.get('cardData') or {}
        title = card.get('title') or sid.split('/')[-1]
        likes = sp.get('likes', 0) or 0
        desc = (card.get('short_description') or '').strip()
        items.append(NewsItem(
            title=f"[Space] {title}",
            url=f"https://huggingface.co/spaces/{sid}",
            source='HuggingFace Spaces',
            source_type='tool',
            reliability='high',
            summary=' · '.join(x for x in [desc, f"❤️ {likes} likes", f"作者 {sp.get('author', '')}"] if x),
            published_at=sp.get('createdAt', ''),
            score=50 + min(likes // 20, 40),
            category='tools'
        ))

    # Daily Papers（独立 try：论文接口失败不影响 Spaces 结果）
    try:
        resp = requests.get(
            'https://huggingface.co/api/daily_papers',
            params={'limit': hf_cfg.get('papers_limit', 10)},
            headers=BROWSER_HEADERS, timeout=20
        )
        resp.raise_for_status()
        for p in resp.json():
            paper = p.get('paper') or {}
            pid = paper.get('id', '')
            title = paper.get('title') or p.get('title') or ''
            if not pid or not title:
                continue
            upvotes = paper.get('upvotes', 0) or 0
            summary = re.sub(r'\s+', ' ', (paper.get('summary') or p.get('summary') or ''))[:200]
            items.append(NewsItem(
                title=f"[论文] {title}",
                url=f"https://huggingface.co/papers/{pid}",
                source='HuggingFace Daily Papers',
                source_type='research',
                reliability='high',
                summary=f"👍 {upvotes} · {summary}",
                published_at=p.get('publishedAt', ''),
                score=40 + min(upvotes, 30),
                category='research'
            ))
    except Exception as e:
        print(f"   ⚠️ HuggingFace Daily Papers 采集失败（Spaces 不受影响）: {e}")

    return items


def fetch_jike(jike_cfg: dict) -> List[NewsItem]:
    """即刻 AI 圈子（RSSHub 路由，多实例回退）；圈子本身主题相关，不做关键词过滤"""
    instances = jike_cfg.get('rsshub_instances', [])
    max_age = jike_cfg.get('max_age_hours', 36)

    items = []
    for topic in jike_cfg.get('topics', []):
        feed = None
        for inst in instances:
            try:
                candidate = fetch_feed(f"{inst}/jike/topic/{topic['id']}")
                if candidate.entries:
                    feed = candidate
                    break
            except Exception:
                continue

        if feed is None:
            print(f"   ⚠️ 即刻圈子「{topic.get('name', '')}」所有 RSSHub 实例均失败")
            continue

        for entry in feed.entries:
            if not entry_is_fresh(entry, max_age):
                continue
            title = strip_html(entry.get('title', ''))
            summary = strip_html(entry.get('summary', ''))[:250]
            if not title and not summary:
                continue
            items.append(NewsItem(
                title=title[:100] or summary[:60],
                url=entry.get('link', ''),
                source=f"即刻·{topic.get('name', '')}",
                source_type='community',
                reliability='medium',
                summary=summary,
                published_at=entry.get('published', ''),
                score=45,
                category='community'
            ))
        time.sleep(1)

    return items[:15]


def fetch_podcasts(keywords: List[str], pod_cfg: dict) -> List[NewsItem]:
    """播客 show notes 扫描（奇想素材：播客里聊出来的点子）；AI 专属播客不过滤，泛科技播客按关键词过滤"""
    max_age = pod_cfg.get('max_age_hours', 72)

    items = []
    for feed_cfg in pod_cfg.get('feeds', []):
        name = feed_cfg.get('name', '')
        need_filter = feed_cfg.get('filter_by_keywords', False)
        try:
            feed = fetch_feed(feed_cfg['url'])
            for entry in feed.entries[:10]:
                if not entry_is_fresh(entry, max_age):
                    continue
                title = entry.get('title', '')
                notes = strip_html(entry.get('summary', ''))[:300]
                if need_filter and not match_keywords(title + ' ' + notes, keywords):
                    continue
                items.append(NewsItem(
                    title=f"🎙 {name}: {title}",
                    url=entry.get('link', ''),
                    source=name,
                    source_type='media',
                    reliability='high',
                    summary=notes,
                    published_at=entry.get('published', ''),
                    score=55,
                    category='podcast'
                ))
        except Exception as e:
            print(f"   ⚠️ 播客 {name} 采集失败: {e}")
        time.sleep(1)

    return items[:10]


def fetch_reddit(keywords: List[str], subreddits: List[str]) -> List[NewsItem]:
    """
    从 Reddit 采集（RSS 端点，JSON API 已被封禁）
    配置中的 subreddit 均为 AI 专属社区，热帖默认相关，不做关键词过滤
    """
    items = []

    for subreddit in subreddits:
        try:
            url = f"https://www.reddit.com/r/{subreddit}/hot.rss?limit=25"
            try:
                feed = fetch_feed(url)
            except requests.HTTPError as e:
                # Reddit 429 是 IP 级限流，短暂退避后重试一次
                if e.response is not None and e.response.status_code == 429:
                    print(f"   ⚠️ r/{subreddit} 被限流，30 秒后重试...")
                    time.sleep(30)
                    feed = fetch_feed(url)
                else:
                    raise

            for rank, entry in enumerate(feed.entries[:15]):
                title = entry.get('title', '')
                if not title:
                    continue

                items.append(NewsItem(
                    title=title,
                    url=entry.get('link', ''),
                    source=f"r/{subreddit}",
                    source_type='community',
                    reliability='medium',
                    summary=strip_html(entry.get('summary', ''))[:200],
                    published_at=entry.get('published', ''),
                    # RSS 不带票数，按热榜位置估分
                    score=30 - rank,
                    category='community'
                ))
        except Exception as e:
            print(f"Reddit r/{subreddit} 采集失败: {e}")
        # Reddit 对连续请求限流严格，拉大间隔
        time.sleep(5)

    return sorted(items, key=lambda x: x.score, reverse=True)[:10]


# X 采集统计，供 main() 判断是否需要告警
TWITTER_STATS = {'total_accounts': 0, 'failed_accounts': 0, 'method': ''}


def fetch_tweets_via_api(account: str, api_cfg: dict, api_key: str,
                         max_age_hours: int) -> List[dict]:
    """
    通过 twitterapi.io 获取账号最新推文
    返回标准化的 dict 列表：{title, url, summary, published_at, engagement}
    """
    base_url = api_cfg.get('base_url', 'https://api.twitterapi.io')
    resp = None
    # twitterapi.io 有 QPS 限流，429 时退避重试
    for attempt in range(3):
        resp = requests.get(
            f"{base_url}/twitter/user/last_tweets",
            params={'userName': account},
            headers={'X-API-Key': api_key},
            timeout=20
        )
        if resp.status_code == 429 and attempt < 2:
            time.sleep(5 * (attempt + 1))
            continue
        break
    resp.raise_for_status()
    data = resp.json()

    if data.get('status') == 'error':
        raise RuntimeError(data.get('message', 'twitterapi.io 返回错误'))

    # 实际返回中 tweets 可能在顶层或 data 内，两种都兼容
    tweets = data.get('tweets') or data.get('data', {}).get('tweets') or []

    results = []
    now = datetime.now(timezone.utc)
    for tw in tweets:
        if tw.get('isReply'):
            continue
        # createdAt 格式如 "Tue Dec 10 07:00:30 +0000 2024"
        created_str = tw.get('createdAt', '')
        try:
            created = datetime.strptime(created_str, '%a %b %d %H:%M:%S %z %Y')
            if now - created > timedelta(hours=max_age_hours):
                continue
        except ValueError:
            pass

        text = (tw.get('text') or '').strip()
        if not text:
            continue

        engagement = (tw.get('likeCount', 0) or 0) + (tw.get('retweetCount', 0) or 0) * 2
        results.append({
            'title': text.replace('\n', ' '),
            'url': tw.get('url', ''),
            'summary': text[:200],
            'published_at': created_str,
            'engagement': engagement,
        })
    return results


def fetch_tweets_via_nitter(account: str, instances: List[str],
                            max_age_hours: int) -> List[dict]:
    """
    通过 nitter 实例的 RSS 获取账号最新推文（API 不可用时的回退方案）
    返回与 fetch_tweets_via_api 相同结构的 dict 列表
    """
    feed = None
    for instance in instances:
        try:
            candidate = fetch_feed(f"{instance}/{account}/rss")
            if candidate.entries:
                feed = candidate
                break
        except Exception:
            continue

    if feed is None:
        raise RuntimeError('所有 nitter 实例均无法获取')

    results = []
    for entry in feed.entries[:20]:
        title = strip_html(entry.get('title', ''))
        # 跳过回复（nitter 中回复标题以 "R to @xxx:" 开头）
        if title.startswith('R to @'):
            continue
        if not entry_is_fresh(entry, max_age_hours):
            continue

        # nitter 链接转回 x.com 原始链接
        url = entry.get('link', '')
        url = re.sub(r'https?://[^/]+/', 'https://x.com/', url, count=1)
        url = url.replace('#m', '')

        results.append({
            'title': title,
            'url': url,
            'summary': strip_html(entry.get('summary', ''))[:200],
            'published_at': entry.get('published', ''),
            'engagement': 0,
        })
    return results


def fetch_twitter(keywords: List[str], twitter_config: dict) -> List[NewsItem]:
    """
    从 X (Twitter) 采集指定账号的推文
    优先走 twitterapi.io（需配置 API key），失败或未配置时回退 nitter RSS
    账号按分组配置：AI 专属账号组不做关键词过滤，泛主题组按关键词过滤
    """
    items = []
    api_cfg = twitter_config.get('api_provider', {})
    api_key = load_env_var(api_cfg.get('api_key_env', 'TWITTERAPI_IO_KEY')) if api_cfg else ''
    instances = twitter_config.get('nitter_instances', ['https://nitter.net'])
    max_age_hours = twitter_config.get('max_age_hours', 36)
    account_groups = twitter_config.get('account_groups', {})

    if api_key:
        print(f"   使用 {api_cfg.get('name', 'API')} 采集（nitter 作为回退）")
        TWITTER_STATS['method'] = 'api'
    else:
        print("   未配置 X API key，使用 nitter RSS 采集")
        TWITTER_STATS['method'] = 'nitter'

    TWITTER_STATS['total_accounts'] = 0
    TWITTER_STATS['failed_accounts'] = 0

    for group_key, group in account_groups.items():
        group_name = group.get('name', group_key)
        need_filter = group.get('filter_by_keywords', True)
        base_score = group.get('score', 60)

        for account in group.get('accounts', []):
            TWITTER_STATS['total_accounts'] += 1
            tweets = None

            if api_key:
                try:
                    tweets = fetch_tweets_via_api(account, api_cfg, api_key, max_age_hours)
                    # API 对部分账号（如自动化 bot）会成功返回空列表，用 nitter 双确认
                    if not tweets:
                        tweets = None
                except Exception as e:
                    print(f"   ⚠️ X @{account} API 采集失败（{e}），尝试 nitter 回退...")

            if tweets is None:
                try:
                    tweets = fetch_tweets_via_nitter(account, instances, max_age_hours)
                except Exception:
                    print(f"   ❌ X @{account} 所有采集途径均失败")
                    TWITTER_STATS['failed_accounts'] += 1
                    time.sleep(1)
                    continue

            if not tweets:
                time.sleep(1)
                continue

            for tw in tweets:
                if need_filter and not match_keywords(tw['title'] + ' ' + tw['summary'], keywords):
                    continue

                items.append(NewsItem(
                    title=f"@{account}: {tw['title'][:100]}",
                    url=tw['url'],
                    source=f"X - @{account} ({group_name})",
                    source_type='kol',
                    reliability='high',
                    summary=tw['summary'],
                    published_at=tw['published_at'],
                    # 分组基础分 + 互动热度加成（封顶 20）
                    score=base_score + min(tw['engagement'] // 100, 20),
                    category='community'
                ))
            time.sleep(1)

    return sorted(items, key=lambda x: x.score, reverse=True)[:20]


def fetch_kol_blogs(keywords: List[str], feeds: List[dict]) -> List[NewsItem]:
    """从 KOL 博客 / Newsletter 的 RSS 采集（配置驱动），按关键词过滤"""
    items = []

    for feed_cfg in feeds:
        name = feed_cfg.get('name', '')
        try:
            feed = fetch_feed(feed_cfg['url'])
            for entry in feed.entries[:20]:
                if not entry_is_fresh(entry, 48):
                    continue
                title = entry.get('title', '')
                summary = strip_html(entry.get('summary', ''))[:200]
                if not match_keywords(title + ' ' + summary, keywords):
                    continue

                items.append(NewsItem(
                    title=title,
                    url=entry.get('link', ''),
                    source=name,
                    source_type='kol',
                    reliability='high',
                    summary=summary,
                    published_at=entry.get('published', ''),
                    score=60,
                    category='media'
                ))
        except Exception as e:
            print(f"KOL 博客 {name} 采集失败: {e}")
        time.sleep(1)

    return items[:12]


def load_seen_urls() -> set:
    """加载历史已推送 URL（由 mark_seen.py 在推送成功后维护，永不重发）"""
    path = os.path.join(BASE_DIR, 'seen_urls.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return set(json.load(f).get('urls', {}).keys())
        except Exception:
            pass
    return set()


def load_pearls() -> List[dict]:
    """加载遗珠库（往日高分落选条目，由 mark_seen.py 维护），供质量闸门回捞"""
    path = os.path.join(BASE_DIR, 'pearls.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f).get('pearls', [])
        except Exception:
            pass
    return []


def deduplicate_items(items: List[NewsItem]) -> List[NewsItem]:
    """去重"""
    seen_urls = set()
    seen_titles = set()
    result = []

    for item in items:
        if item.url in seen_urls:
            continue

        title_key = item.title[:30].lower()
        if title_key in seen_titles:
            continue

        seen_urls.add(item.url)
        seen_titles.add(title_key)
        result.append(item)

    return result


def send_admin_alert(config: dict, alert_msg: str) -> bool:
    """通过 lark-cli 给管理员发采集异常告警私信"""
    admin_user_id = config.get('feishu', {}).get('admin_user_id', '')
    if not admin_user_id:
        return False

    text = f"""⚠️ AI一千零一夜采集异常

时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{alert_msg}

请检查采集日志和信息源状态（可运行 test_sources.py 复测）。""".strip()

    try:
        result = subprocess.run(
            ['lark-cli', 'im', '+messages-send', '--as', 'bot',
             '--user-id', admin_user_id, '--text', text],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print("   📢 已私信告警给管理员")
            return True
        print(f"   ❌ 告警发送失败: {result.stderr}")
    except Exception as e:
        print(f"   ❌ 告警发送异常: {e}")
    return False


def safe_fetch(fetch_func, *args, source_name: str = "", max_retries: int = 2) -> List[NewsItem]:
    """
    安全采集：失败时自动重试，最终失败返回空列表
    """
    try:
        retry_func = with_retry(fetch_func, max_retries=max_retries)
        return retry_func(*args)
    except Exception as e:
        print(f"   ❌ {source_name} 采集失败: {e}")
        return []


def main():
    """主函数 - 采集原始数据并保存为 JSON"""
    print("🌙 AI一千零一夜 · 开始采集今夜素材...")

    config = load_config()
    keywords = config['keywords']
    sources = config['sources']
    retry_config = config.get('retry', {'max_retries': 2, 'retry_delay': 3})

    all_items = []

    # 1. Show HN（造物主阵地，重试 2 次）
    if sources.get('hackernews', {}).get('enabled'):
        print("📡 采集 Show HN...")
        items = safe_fetch(fetch_hackernews, keywords,
                          sources['hackernews'].get('min_points_bypass', 20),
                          source_name="Show HN",
                          max_retries=retry_config['max_retries'])
        print(f"   找到 {len(items)} 条")
        all_items.extend(items)

    # 2. Product Hunt（重试 2 次）
    if sources.get('producthunt', {}).get('enabled'):
        print("📡 采集 Product Hunt...")
        items = safe_fetch(fetch_producthunt, keywords, sources['producthunt'],
                          source_name="Product Hunt",
                          max_retries=retry_config['max_retries'])
        print(f"   找到 {len(items)} 条")
        all_items.extend(items)

    # 3. GitHub 新项目（重试 2 次）
    if sources.get('github', {}).get('enabled'):
        print("📡 采集 GitHub 新项目...")
        items = safe_fetch(fetch_github_trending, sources['github'],
                          source_name="GitHub",
                          max_retries=retry_config['max_retries'])
        print(f"   找到 {len(items)} 条")
        all_items.extend(items)

    # 4. HuggingFace（Spaces + Daily Papers，重试 2 次）
    if sources.get('huggingface', {}).get('enabled'):
        print("📡 采集 HuggingFace...")
        items = safe_fetch(fetch_huggingface, sources['huggingface'],
                          source_name="HuggingFace",
                          max_retries=retry_config['max_retries'])
        print(f"   找到 {len(items)} 条")
        all_items.extend(items)

    # 5. 即刻 AI 圈子（RSSHub 多实例回退，重试 1 次）
    if sources.get('jike', {}).get('enabled'):
        print("📡 采集 即刻 AI 圈子...")
        items = safe_fetch(fetch_jike, sources['jike'],
                          source_name="即刻",
                          max_retries=1)
        print(f"   找到 {len(items)} 条")
        all_items.extend(items)

    # 6. Reddit（RSS 方式，重试 1 次）
    if sources.get('reddit', {}).get('enabled'):
        print("📡 采集 Reddit...")
        items = safe_fetch(fetch_reddit, keywords, sources['reddit']['subreddits'],
                          source_name="Reddit",
                          max_retries=1)
        print(f"   找到 {len(items)} 条")
        all_items.extend(items)

    # 7. X (Twitter) 账号（API 优先 + nitter 回退，重试 1 次）
    if sources.get('twitter', {}).get('enabled'):
        print("📡 采集 X (Twitter) 账号...")
        items = safe_fetch(fetch_twitter, keywords, sources['twitter'],
                          source_name="X (Twitter)",
                          max_retries=1)
        print(f"   找到 {len(items)} 条")
        all_items.extend(items)

        # X 采集健康检查：全部账号失败 → 告警；部分失败且 0 条 → 也告警
        total = TWITTER_STATS['total_accounts']
        failed = TWITTER_STATS['failed_accounts']
        if total > 0:
            if failed >= total:
                send_admin_alert(config,
                    f"X 信息源采集全部失败（{failed}/{total} 个账号，方式：{TWITTER_STATS['method']}），"
                    f"twitterapi.io 和 nitter 可能都已失效。")
            elif failed > 0 and len(items) == 0:
                send_admin_alert(config,
                    f"X 信息源采集 0 条，且 {failed}/{total} 个账号采集失败（方式：{TWITTER_STATS['method']}），"
                    f"请确认采集途径是否部分失效。")

    # 8. KOL 博客与 Newsletter（重试 2 次）
    if sources.get('kol_blogs', {}).get('enabled'):
        print("📡 采集 KOL 博客...")
        items = safe_fetch(fetch_kol_blogs, keywords,
                          sources['kol_blogs'].get('feeds', []),
                          source_name="KOL 博客",
                          max_retries=retry_config['max_retries'])
        print(f"   找到 {len(items)} 条")
        all_items.extend(items)

    # 9. 播客 show notes（重试 1 次）
    if sources.get('podcasts', {}).get('enabled'):
        print("📡 采集 播客 show notes...")
        items = safe_fetch(fetch_podcasts, keywords, sources['podcasts'],
                          source_name="播客",
                          max_retries=1)
        print(f"   找到 {len(items)} 条")
        all_items.extend(items)

    # 去重
    print(f"\n🔍 去重前: {len(all_items)} 条")
    all_items = deduplicate_items(all_items)
    print(f"🔍 去重后: {len(all_items)} 条")

    # 过滤历史已推送/已考虑内容（已见过的永不重发；没见过比刚发生更重要）
    seen_urls = load_seen_urls()
    if seen_urls:
        before = len(all_items)
        all_items = [item for item in all_items if item.url not in seen_urls]
        print(f"🔍 过滤已推送后: {len(all_items)} 条（去掉 {before - len(all_items)} 条历史内容）")

    # 按分类整理（采集侧粗分类，供整理参考）
    categorized = {}
    for item in all_items:
        cat = item.category
        if cat not in categorized:
            categorized[cat] = []
        categorized[cat].append(asdict(item))

    # 按分数排序
    for cat in categorized:
        categorized[cat] = sorted(categorized[cat], key=lambda x: x['score'], reverse=True)

    # 遗珠库：往日高分落选条目，供质量闸门回捞（不计入 total_count）
    pearls = load_pearls()

    # 保存原始数据为 JSON，供 AI 整理使用
    today = datetime.now().strftime('%Y%m%d')
    raw_data = {
        'date': today,
        'total_count': len(all_items),
        'items': [asdict(item) for item in all_items],
        'categorized': categorized,
        'pearls': pearls
    }

    output_file = os.path.join(BASE_DIR, f"raw_news_{today}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 今夜素材采集完成！已保存到: {output_file}")
    print(f"   候选池: {len(all_items)} 条 · 遗珠库: {len(pearls)} 条")

    # 打印统计
    print("\n📊 分类统计:")
    for cat, items in categorized.items():
        print(f"   {cat}: {len(items)} 条")

    return raw_data


if __name__ == '__main__':
    main()
