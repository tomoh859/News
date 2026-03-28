"""サイト管理: URLからRSSフィード自動検出 & サイト登録"""
import json
import random
from pathlib import Path
from urllib.parse import urlparse

import requests
import feedparser
from bs4 import BeautifulSoup

SITES_FILE = Path(__file__).parent / "sites.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}

# サイトごとに色を割り振るためのパレット
COLORS = [
    "#FF6B35", "#1A73E8", "#34A853", "#9B59B6", "#E74C3C",
    "#F39C12", "#1ABC9C", "#E91E63", "#3F51B5", "#009688",
    "#FF5722", "#795548", "#607D8B", "#8BC34A", "#00BCD4",
]


def load_sites() -> list[dict]:
    """sites.json を読み込む"""
    if SITES_FILE.exists():
        return json.loads(SITES_FILE.read_text("utf-8"))
    return []


def save_sites(sites: list[dict]):
    """sites.json に保存"""
    SITES_FILE.write_text(
        json.dumps(sites, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def detect_rss_feeds(url: str) -> list[dict]:
    """URLからRSSフィードを自動検出する"""
    found = []

    # URLを正規化
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ❌ ページ取得失敗: {e}")
        return []

    content_type = resp.headers.get("content-type", "")

    # 1) URL自体がRSSフィードの場合
    if "xml" in content_type or "rss" in content_type or "atom" in content_type:
        feed = feedparser.parse(resp.content)
        if feed.entries:
            title = feed.feed.get("title", parsed.netloc)
            found.append({"url": url, "title": title, "count": len(feed.entries)})
            return found

    # 2) HTMLページからRSSリンクを探す
    soup = BeautifulSoup(resp.text, "html.parser")
    rss_links = soup.find_all("link", type=lambda t: t and ("rss" in t or "atom" in t))

    for link in rss_links:
        href = link.get("href", "")
        if not href:
            continue
        if not href.startswith("http"):
            if href.startswith("/"):
                href = base_url + href
            else:
                href = base_url + "/" + href
        title = link.get("title", "")

        # フィードの中身を確認
        try:
            feed_resp = requests.get(href, headers=HEADERS, timeout=10)
            feed = feedparser.parse(feed_resp.content)
            if feed.entries:
                if not title:
                    title = feed.feed.get("title", parsed.netloc)
                found.append({"url": href, "title": title, "count": len(feed.entries)})
        except Exception:
            found.append({"url": href, "title": title or "不明", "count": 0})

    # 3) よくあるRSSパスを試す
    if not found:
        common_paths = [
            "/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml",
            "/index.xml", "/rss/index.xml", "/feeds/posts/default",
        ]
        for path in common_paths:
            feed_url = base_url + path
            try:
                feed_resp = requests.get(feed_url, headers=HEADERS, timeout=5)
                if feed_resp.status_code == 200:
                    feed = feedparser.parse(feed_resp.content)
                    if feed.entries:
                        title = feed.feed.get("title", parsed.netloc)
                        found.append({"url": feed_url, "title": title, "count": len(feed.entries)})
                        break
            except Exception:
                continue

    return found


def pick_color(sites: list[dict]) -> str:
    """既存サイトと被らない色を選ぶ"""
    used = {s.get("color") for s in sites}
    available = [c for c in COLORS if c not in used]
    return random.choice(available) if available else random.choice(COLORS)


def add_site(url: str, name: str = None) -> bool:
    """サイトを追加する（RSS自動検出 or スクレイピング）"""
    sites = load_sites()

    # 重複チェック
    parsed = urlparse(url if url.startswith("http") else "https://" + url)
    for s in sites:
        if parsed.netloc in s.get("url", ""):
            print(f"  ⚠️  {parsed.netloc} は既に登録済みです")
            return False

    print(f"\n🔍 {url} のRSSフィードを検出中...")
    feeds = detect_rss_feeds(url)

    if feeds:
        # RSSが見つかった
        if len(feeds) == 1:
            feed = feeds[0]
        else:
            print(f"\n  複数のフィードが見つかりました:")
            for i, f in enumerate(feeds):
                print(f"    [{i+1}] {f['title']} ({f['count']}件) - {f['url']}")
            try:
                choice = input(f"  番号を選択 [1-{len(feeds)}] (Enter=1): ").strip()
                idx = int(choice) - 1 if choice.isdigit() else 0
            except EOFError:
                idx = 0
                print(f"  → 自動で [1] を選択")
            feed = feeds[max(0, min(idx, len(feeds) - 1))]

        site_name = name or feed["title"] or parsed.netloc
        color = pick_color(sites)
        icon = site_name[0].upper() if site_name else "?"

        new_site = {
            "name": site_name,
            "type": "rss",
            "url": feed["url"],
            "color": color,
            "icon": icon,
        }
        print(f"  ✅ RSS検出: {feed['title']} ({feed['count']}件)")
    else:
        # RSS未検出 → スクレイピングで登録
        site_name = name or parsed.netloc
        color = pick_color(sites)
        icon = site_name[0].upper()

        new_site = {
            "name": site_name,
            "type": "scrape",
            "url": url if url.startswith("http") else "https://" + url,
            "color": color,
            "icon": icon,
        }
        print(f"  ⚠️  RSSが見つかりませんでした。スクレイピングモードで登録します。")

    sites.append(new_site)
    save_sites(sites)
    print(f"\n  🎉 「{new_site['name']}」を追加しました！ (タイプ: {new_site['type']})")
    return True


def remove_site(name_or_index: str) -> bool:
    """サイトを削除する"""
    sites = load_sites()

    if name_or_index.isdigit():
        idx = int(name_or_index) - 1
        if 0 <= idx < len(sites):
            removed = sites.pop(idx)
            save_sites(sites)
            print(f"  🗑  「{removed['name']}」を削除しました")
            return True
        print(f"  ❌ 番号が範囲外です (1-{len(sites)})")
        return False

    for i, s in enumerate(sites):
        if name_or_index.lower() in s["name"].lower():
            removed = sites.pop(i)
            save_sites(sites)
            print(f"  🗑  「{removed['name']}」を削除しました")
            return True

    print(f"  ❌ 「{name_or_index}」に一致するサイトが見つかりません")
    return False


def list_sites():
    """登録済みサイト一覧を表示"""
    sites = load_sites()
    if not sites:
        print("  登録サイトなし")
        return

    print(f"\n📋 登録サイト一覧 ({len(sites)}件)")
    print("-" * 60)
    for i, s in enumerate(sites, 1):
        mode = "RSS" if s["type"] == "rss" else "スクレイピング"
        print(f"  [{i}] {s['name']}  ({mode})")
        print(f"      {s['url']}")
    print()


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("使い方:")
        print("  python site_manager.py list                  # 一覧表示")
        print("  python site_manager.py add <URL> [名前]      # サイト追加")
        print("  python site_manager.py remove <名前or番号>   # サイト削除")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "list":
        list_sites()
    elif cmd == "add" and len(sys.argv) >= 3:
        url = sys.argv[2]
        name = sys.argv[3] if len(sys.argv) >= 4 else None
        add_site(url, name)
    elif cmd == "remove" and len(sys.argv) >= 3:
        remove_site(sys.argv[2])
    else:
        print("不明なコマンドです。引数なしで実行するとヘルプが表示されます。")
