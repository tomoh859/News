"""記事スクレイパー: RSS取得 + 電通報スクレイピング + OGP画像取得"""
import re
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field

import feedparser
import requests
from bs4 import BeautifulSoup

from config import load_sites, DEFAULT_MAX_ARTICLES

JST = timezone(timedelta(hours=9))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


@dataclass
class Article:
    title: str
    url: str
    source: str
    source_color: str
    source_icon: str
    published: str = ""
    published_iso: str = ""
    summary: str = ""
    image_url: str = ""
    category: str = ""


def fetch_rss(site: dict) -> list[Article]:
    """RSSフィードから記事を取得"""
    try:
        resp = SESSION.get(site["url"], timeout=15)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as e:
        print(f"  [ERROR] {site['name']} RSS取得失敗: {e}")
        return []

    max_articles = site.get("max_articles", DEFAULT_MAX_ARTICLES)
    articles = []
    for entry in feed.entries[:max_articles]:
        # 日付
        published = ""
        published_iso = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            dt = datetime(*entry.published_parsed[:6])
            published = dt.strftime("%Y-%m-%d")
            published_iso = dt.strftime("%Y-%m-%dT%H:%M:%S")
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            dt = datetime(*entry.updated_parsed[:6])
            published = dt.strftime("%Y-%m-%d")
            published_iso = dt.strftime("%Y-%m-%dT%H:%M:%S")

        # 概要
        summary = ""
        if hasattr(entry, "summary"):
            summary = BeautifulSoup(entry.summary, "html.parser").get_text()[:150]

        # RSS内の画像
        image_url = ""
        if hasattr(entry, "media_content") and entry.media_content:
            image_url = entry.media_content[0].get("url", "")
        elif hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            image_url = entry.media_thumbnail[0].get("url", "")
        elif hasattr(entry, "enclosures") and entry.enclosures:
            for enc in entry.enclosures:
                if enc.get("type", "").startswith("image"):
                    image_url = enc.get("href", "")
                    break

        # カテゴリ
        category = ""
        if hasattr(entry, "tags") and entry.tags:
            category = entry.tags[0].get("term", "")

        articles.append(Article(
            title=entry.get("title", "無題"),
            url=entry.get("link", ""),
            source=site["name"],
            source_color=site["color"],
            source_icon=site["icon"],
            published=published,
            published_iso=published_iso,
            summary=summary,
            image_url=image_url,
            category=category,
        ))

    return articles


def scrape_dentsuho(site: dict) -> list[Article]:
    """電通報をスクレイピング"""
    max_articles = site.get("max_articles", DEFAULT_MAX_ARTICLES)
    articles = []
    try:
        resp = SESSION.get(site["url"], timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        seen_urls = set()
        for a_tag in soup.select("a[href*='/articles/']"):
            href = a_tag.get("href", "")
            if not href or "/articles/" not in href:
                continue
            if not href.startswith("http"):
                href = "https://dentsu-ho.com" + href
            if href in seen_urls:
                continue
            seen_urls.add(href)

            title_el = a_tag.select_one("h2, h3, h4, .title, p")
            title = title_el.get_text(strip=True) if title_el else a_tag.get_text(strip=True)
            if not title or len(title) < 5:
                continue

            img_el = a_tag.select_one("img")
            image_url = ""
            if img_el:
                image_url = img_el.get("src", "") or img_el.get("data-src", "")

            # 日付取得: span.text-locale-muted から YYYY/MM/DD を探す
            published = ""
            for span in a_tag.select("span.text-locale-muted"):
                text = span.get_text(strip=True)
                m = re.match(r"(\d{4}/\d{2}/\d{2})", text)
                if m:
                    try:
                        dt = datetime.strptime(m.group(1), "%Y/%m/%d")
                        published = dt.strftime("%Y-%m-%d")
                    except ValueError:
                        pass
                    break

            articles.append(Article(
                title=title[:100],
                url=href,
                source=site["name"],
                source_color=site["color"],
                source_icon=site["icon"],
                published=published,
                image_url=image_url,
            ))

            if len(articles) >= max_articles:
                break

    except Exception as e:
        print(f"  [ERROR] 電通報スクレイピング失敗: {e}")

    return articles


def fetch_ogp_image(url: str) -> str:
    """記事ページからOGP画像を取得"""
    try:
        resp = SESSION.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # og:image
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og["content"]

        # twitter:image
        tw = soup.find("meta", attrs={"name": "twitter:image"})
        if tw and tw.get("content"):
            return tw["content"]

    except Exception:
        pass
    return ""


def fetch_all_articles_for_sites(sites: list[dict]) -> list[Article]:
    """指定サイトリストから記事を取得"""
    all_articles = []

    for site in sites:
        print(f"📡 {site['name']} を取得中...")
        if site["type"] == "rss":
            articles = fetch_rss(site)
        elif site["type"] == "scrape":
            articles = scrape_dentsuho(site)
        else:
            continue

        for art in articles:
            if not art.image_url:
                print(f"  🖼  OGP取得: {art.title[:30]}...")
                art.image_url = fetch_ogp_image(art.url)

        print(f"  ✅ {len(articles)}件取得")
        all_articles.extend(articles)

    all_articles.sort(key=lambda a: a.published or "0000-00-00", reverse=True)
    return all_articles


def fetch_all_articles() -> list[Article]:
    """全サイトから記事を取得"""
    all_articles = []

    for site in load_sites():
        print(f"📡 {site['name']} を取得中...")
        if site["type"] == "rss":
            articles = fetch_rss(site)
        elif site["type"] == "scrape":
            articles = scrape_dentsuho(site)
        else:
            continue

        # 画像がない記事はOGPから取得
        for art in articles:
            if not art.image_url:
                print(f"  🖼  OGP取得: {art.title[:30]}...")
                art.image_url = fetch_ogp_image(art.url)

        print(f"  ✅ {len(articles)}件取得")
        all_articles.extend(articles)

    # 日付でソート（新しい順、日付なしは末尾）
    all_articles.sort(key=lambda a: a.published or "0000-00-00", reverse=True)
    return all_articles


if __name__ == "__main__":
    articles = fetch_all_articles()
    for a in articles:
        img = "🖼" if a.image_url else "  "
        print(f"  {img} [{a.source}] {a.title[:50]} ({a.published})")
    print(f"\n合計: {len(articles)}件")
