#!/usr/bin/env python3
"""
测试所有信息源是否正常工作（与 config.json 启用的 9 路信息源一一对应）
"""
import json
import os
import requests
import feedparser
import time
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
}


def load_config():
    with open(os.path.join(BASE_DIR, 'config.json'), 'r', encoding='utf-8') as f:
        return json.load(f)


CONFIG = load_config()


def test_source(name, test_func, timeout=15):
    """测试单个信息源"""
    print(f"\n{'='*50}")
    print(f"测试: {name}")
    print(f"{'='*50}")

    start_time = time.time()
    try:
        result = test_func(timeout)
        elapsed = time.time() - start_time
        count = len(result) if result else 0
        print(f"✅ 成功! 耗时: {elapsed:.1f}s, 获取: {count} 条")
        if result and count > 0:
            print(f"   示例: {result[0]['title'][:60]}...")
        return True, result
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"❌ 失败! 耗时: {elapsed:.1f}s, 错误: {e}")
        return False, str(e)


def feed_items(url, timeout, limit=5):
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    return [{'title': e.get('title', ''), 'url': e.get('link', '')}
            for e in feed.entries[:limit]]


def test_show_hn(timeout):
    """Show HN（Algolia 搜索 API）"""
    since = int(time.time()) - 48 * 3600
    url = (f"https://hn.algolia.com/api/v1/search_by_date"
           f"?tags=show_hn&numericFilters=created_at_i>{since}&hitsPerPage=5")
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return [{'title': h.get('title', ''), 'url': h.get('url') or ''}
            for h in resp.json().get('hits', [])[:5]]


def test_producthunt(timeout):
    """Product Hunt 官方 RSS"""
    return feed_items(CONFIG['sources']['producthunt']['feed_url'], timeout)


def test_github(timeout):
    """GitHub 新项目搜索（带 created/stars 条件）"""
    cfg = CONFIG['sources']['github']
    since = (datetime.now() - timedelta(days=cfg['created_within_days'])).strftime('%Y-%m-%d')
    q = ' OR '.join(cfg['query_terms']) + f" created:>{since} stars:>{cfg['min_stars']}"
    resp = requests.get('https://api.github.com/search/repositories',
                        params={'q': q, 'sort': 'stars', 'order': 'desc', 'per_page': 5},
                        headers={'Accept': 'application/vnd.github.v3+json'}, timeout=timeout)
    resp.raise_for_status()
    return [{'title': r['full_name'], 'url': r['html_url']}
            for r in resp.json().get('items', [])[:5]]


def test_hf_spaces(timeout):
    """HuggingFace trending Spaces"""
    resp = requests.get('https://huggingface.co/api/spaces',
                        params={'sort': 'trendingScore', 'direction': -1, 'limit': 5, 'full': 'true'},
                        headers=BROWSER_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return [{'title': s.get('id', ''), 'url': f"https://huggingface.co/spaces/{s.get('id', '')}"}
            for s in resp.json()[:5]]


def test_hf_papers(timeout):
    """HuggingFace Daily Papers"""
    resp = requests.get('https://huggingface.co/api/daily_papers',
                        params={'limit': 5}, headers=BROWSER_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return [{'title': (p.get('paper') or {}).get('title') or p.get('title', ''),
             'url': f"https://huggingface.co/papers/{(p.get('paper') or {}).get('id', '')}"}
            for p in resp.json()[:5]]


def make_jike_test(topic):
    def test_jike(timeout):
        last_err = None
        for inst in CONFIG['sources']['jike']['rsshub_instances']:
            try:
                items = feed_items(f"{inst}/jike/topic/{topic['id']}", timeout)
                if items:
                    print(f"   （实例: {inst}）")
                    return items
            except Exception as e:
                last_err = e
        raise last_err or Exception('所有 RSSHub 实例均失败')
    return test_jike


def make_v2ex_test(node):
    def test_v2ex(timeout):
        resp = requests.get(f"https://www.v2ex.com/api/topics/show.json?node_name={node}",
                            headers=BROWSER_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return [{'title': t.get('title', ''), 'url': t.get('url', '')}
                for t in resp.json()[:5]]
    return test_v2ex


def make_reddit_test(subreddit):
    def test_reddit(timeout):
        url = f"https://www.reddit.com/r/{subreddit}/hot.rss?limit=5"
        try:
            return feed_items(url, timeout)
        except requests.HTTPError as e:
            # 与生产逻辑一致：429 是 IP 级限流，30 秒退避后重试一次
            if e.response is not None and e.response.status_code == 429:
                print("   ⚠️ 被限流，30 秒后重试...")
                time.sleep(30)
                return feed_items(url, timeout)
            raise
    return test_reddit


def first_twitter_account():
    groups = CONFIG['sources']['twitter']['account_groups']
    for group in groups.values():
        if group.get('accounts'):
            return group['accounts'][0]
    return 'op7418'


def test_twitter_api(timeout):
    """X (Twitter) via twitterapi.io（主途径）"""
    from fetch_news import load_env_var
    api_key = load_env_var('TWITTERAPI_IO_KEY')
    if not api_key:
        raise Exception('未配置 TWITTERAPI_IO_KEY（写入 .env 文件或环境变量）')
    account = first_twitter_account()
    resp = requests.get(
        'https://api.twitterapi.io/twitter/user/last_tweets',
        params={'userName': account},
        headers={'X-API-Key': api_key},
        timeout=timeout
    )
    resp.raise_for_status()
    data = resp.json()
    tweets = data.get('tweets') or data.get('data', {}).get('tweets') or []
    print(f"   （账号: @{account}）")
    return [{'title': (t.get('text') or '')[:80], 'url': t.get('url', '')} for t in tweets[:5]]


def test_twitter_nitter(timeout):
    """X (Twitter) via nitter（回退途径）"""
    account = first_twitter_account()
    last_err = None
    for inst in CONFIG['sources']['twitter']['nitter_instances']:
        try:
            items = feed_items(f"{inst}/{account}/rss", timeout)
            if items:
                print(f"   （实例: {inst}，账号: @{account}）")
                return items
        except Exception as e:
            last_err = e
    raise last_err or Exception('所有 nitter 实例均失败')


def make_feed_test(url):
    def test_feed(timeout):
        return feed_items(url, timeout)
    return test_feed


def main():
    print("🚀 开始测试所有信息源...")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    tests = [
        ("Show HN (Algolia)", test_show_hn),
        ("Product Hunt", test_producthunt),
        ("GitHub 新项目", test_github),
        ("HuggingFace Spaces", test_hf_spaces),
        ("HuggingFace Daily Papers", test_hf_papers),
    ]

    for topic in CONFIG['sources']['jike']['topics']:
        tests.append((f"即刻·{topic['name']} (RSSHub)", make_jike_test(topic)))

    for node in CONFIG['sources'].get('v2ex', {}).get('nodes', []):
        tests.append((f"V2EX {node}", make_v2ex_test(node)))

    for sub in CONFIG['sources']['reddit']['subreddits']:
        tests.append((f"Reddit r/{sub}", make_reddit_test(sub)))

    tests.append(("X (Twitter) via twitterapi.io", test_twitter_api))
    tests.append(("X (Twitter) via nitter (回退)", test_twitter_nitter))

    for feed_cfg in CONFIG['sources']['kol_blogs']['feeds']:
        tests.append((f"KOL·{feed_cfg['name']}", make_feed_test(feed_cfg['url'])))

    for feed_cfg in CONFIG['sources']['podcasts']['feeds']:
        tests.append((f"播客·{feed_cfg['name']}", make_feed_test(feed_cfg['url'])))

    results = {}
    for name, test_func in tests:
        success, result = test_source(name, test_func, timeout=15)
        results[name] = {'success': success, 'result': result}
        # Reddit 对连续请求限流严格，拉大间隔
        time.sleep(5 if name.startswith('Reddit') else 1)

    # 汇总
    print(f"\n\n{'='*60}")
    print("📊 测试结果汇总")
    print(f"{'='*60}")

    success_count = 0
    fail_count = 0

    for name, data in results.items():
        status = "✅" if data['success'] else "❌"
        if data['success']:
            success_count += 1
            count = len(data['result']) if data['result'] else 0
            print(f"{status} {name}: 成功 ({count} 条)")
        else:
            fail_count += 1
            print(f"{status} {name}: 失败 - {data['result']}")

    print(f"\n总计: {success_count} 成功, {fail_count} 失败")
    return fail_count


if __name__ == '__main__':
    exit(1 if main() else 0)
