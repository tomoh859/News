#!/usr/bin/env python3
"""ローカルWebサーバー: セットアップページ + パーソナルギャラリー"""
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from scraper import fetch_all_articles_for_sites, fetch_all_articles
from generator import generate_gallery_html
from site_manager import load_sites, save_sites, detect_rss_feeds, pick_color
from config import load_email_settings, save_email_settings
from mailer import send_email, filter_recent_articles

PORT = int(os.environ.get("PORT", 8080))

# サイトIDごとの記事キャッシュ
articles_cache = {}
cache_lock = threading.Lock()
last_refresh_time = None


def refresh_all_cache():
    """全サイトの記事を取得してキャッシュを更新"""
    global articles_cache, last_refresh_time
    from datetime import datetime, timezone, timedelta
    JST = timezone(timedelta(hours=9))

    print(f"🔄 全記事キャッシュを更新中...")
    all_sites = load_sites()
    new_cache = {}
    articles = fetch_all_articles_for_sites(all_sites)
    for site in all_sites:
        sid = site.get("id", "")
        new_cache[sid] = [a for a in articles if a.source == site["name"]]

    with cache_lock:
        articles_cache = new_cache
        last_refresh_time = datetime.now(JST)

    print(f"✅ キャッシュ更新完了: {len(articles)}件 ({last_refresh_time.strftime('%H:%M')})")


def schedule_daily_refresh():
    """毎朝7時にキャッシュを自動更新するスケジューラー"""
    from datetime import datetime, timezone, timedelta
    JST = timezone(timedelta(hours=9))

    def scheduler_loop():
        while True:
            now = datetime.now(JST)
            # 次の7:00を計算
            tomorrow_7am = now.replace(hour=7, minute=0, second=0, microsecond=0)
            if now >= tomorrow_7am:
                tomorrow_7am += timedelta(days=1)
            wait_seconds = (tomorrow_7am - now).total_seconds()

            print(f"⏰ 次回更新: {tomorrow_7am.strftime('%Y-%m-%d %H:%M')} ({int(wait_seconds//3600)}時間{int((wait_seconds%3600)//60)}分後)")
            import time
            time.sleep(wait_seconds)

            try:
                refresh_all_cache()
            except Exception as e:
                print(f"❌ 定時更新失敗: {e}")

    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/" or path == "":
            self._serve_app()
        elif path == "/api/articles":
            site_ids_str = params.get("sites", [""])[0]
            self._serve_articles(site_ids_str)
        elif path == "/api/sites":
            self._json_response(load_sites())
        elif path == "/api/detect-rss":
            url = params.get("url", [""])[0]
            if not url:
                self._json_response({"error": "urlパラメータが必要です"}, 400)
                return
            feeds = detect_rss_feeds(url)
            self._json_response({"feeds": feeds})
        elif path == "/api/email":
            settings = load_email_settings()
            safe = dict(settings)
            if safe.get("password"):
                safe["password_set"] = True
                safe["password"] = ""
            else:
                safe["password_set"] = False
            self._json_response(safe)
        else:
            self._text_response("Not Found", 404)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()

        if path == "/api/sites":
            self._add_site(body)
        elif path == "/api/sites/delete":
            self._delete_site(body)
        elif path == "/api/email":
            self._update_email(body)
        elif path == "/api/email/test":
            self._test_email(body)
        else:
            self._text_response("Not Found", 404)

    def _serve_app(self):
        """SPA: 全機能を1つのページで提供"""
        sites = load_sites()
        html = generate_app_page(sites)
        self._html_response(html)

    def _serve_articles(self, site_ids_str: str):
        """API: 指定サイトの記事をJSON返却"""
        if not site_ids_str:
            self._json_response({"error": "sitesパラメータが必要です"}, 400)
            return

        site_ids = [s.strip() for s in site_ids_str.split(",") if s.strip()]
        all_sites = load_sites()
        selected = [s for s in all_sites if s.get("id") in site_ids]

        if not selected:
            self._json_response({"error": "該当サイトなし"}, 404)
            return

        articles = []
        sites_to_fetch = []
        with cache_lock:
            for site in selected:
                sid = site["id"]
                if sid in articles_cache:
                    articles.extend(articles_cache[sid])
                else:
                    sites_to_fetch.append(site)

        if sites_to_fetch:
            new_articles = fetch_all_articles_for_sites(sites_to_fetch)
            with cache_lock:
                for site in sites_to_fetch:
                    sid = site["id"]
                    articles_cache[sid] = [a for a in new_articles if a.source == site["name"]]
            articles.extend(new_articles)

        articles.sort(key=lambda a: a.published or "0000-00-00", reverse=True)

        data = [{
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "source_color": a.source_color,
            "source_icon": a.source_icon,
            "published": a.published,
            "published_iso": a.published_iso,
            "summary": a.summary,
            "image_url": a.image_url,
            "category": a.category,
        } for a in articles]

        self._json_response({"articles": data, "count": len(data)})

    def _add_site(self, body: dict):
        url = body.get("url", "")
        name = body.get("name", "")
        site_id = body.get("id", "")

        if not url:
            self._json_response({"error": "URLが必要です"}, 400)
            return

        sites = load_sites()
        parsed_url = urlparse(url if url.startswith("http") else "https://" + url)

        # 重複チェック
        for s in sites:
            if parsed_url.netloc in s.get("url", ""):
                self._json_response({"error": f"{parsed_url.netloc} は既に登録済みです"}, 409)
                return

        # RSS自動検出
        feeds = detect_rss_feeds(url)
        if feeds:
            feed = feeds[0]
            auto_name = name or feed["title"] or parsed_url.netloc
            new_site = {
                "id": site_id or parsed_url.netloc.split(".")[0],
                "name": auto_name,
                "type": "rss",
                "url": feed["url"],
                "color": pick_color(sites),
                "icon": auto_name[0].upper() if auto_name else "?",
            }
        else:
            auto_name = name or parsed_url.netloc
            new_site = {
                "id": site_id or parsed_url.netloc.split(".")[0],
                "name": auto_name,
                "type": "scrape",
                "url": url if url.startswith("http") else "https://" + url,
                "color": pick_color(sites),
                "icon": auto_name[0].upper() if auto_name else "?",
            }

        sites.append(new_site)
        save_sites(sites)
        self._json_response({"ok": True, "site": new_site})

    def _delete_site(self, body: dict):
        index = body.get("index")
        if index is None:
            self._json_response({"error": "indexが必要です"}, 400)
            return
        sites = load_sites()
        if 0 <= index < len(sites):
            removed = sites.pop(index)
            save_sites(sites)
            self._json_response({"ok": True, "removed": removed["name"]})
        else:
            self._json_response({"error": "無効なインデックスです"}, 400)

    def _update_email(self, body: dict):
        settings = load_email_settings()
        if "sender" in body:
            settings["sender"] = body["sender"]
        if "password" in body and body["password"]:
            settings["password"] = body["password"]
        if "recipients" in body:
            settings["recipients"] = [r.strip() for r in body["recipients"] if r.strip()]
        if "smtp_server" in body:
            settings["smtp_server"] = body["smtp_server"]
        if "smtp_port" in body:
            settings["smtp_port"] = int(body["smtp_port"])
        save_email_settings(settings)
        self._json_response({"ok": True})

    def _test_email(self, body: dict):
        site_ids = body.get("sites", [])
        all_sites = load_sites()
        if site_ids:
            selected = [s for s in all_sites if s.get("id") in site_ids]
        else:
            selected = all_sites
        articles = fetch_all_articles_for_sites(selected)
        recent = filter_recent_articles(articles, hours=24)
        if not recent:
            self._json_response({"error": "24時間以内の新着記事がありません"}, 400)
            return
        gallery_html = generate_gallery_html(recent)
        success, error_msg = send_email(gallery_html)
        if success:
            self._json_response({"ok": True, "count": len(recent)})
        else:
            self._json_response({"error": f"送信失敗: {error_msg}"}, 500)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    def _json_response(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _html_response(self, html, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _text_response(self, text, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))

    def log_message(self, format, *args):
        pass


def generate_app_page(sites: list) -> str:
    """SPA: ギャラリー + 設定を1ページで提供。サイト選択はlocalStorageに保存。"""
    sites_json = json.dumps(sites, ensure_ascii=False)
    default_ids = json.dumps([s["id"] for s in sites])

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>最新ニュース</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&display=swap');
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family:'Noto Sans JP',-apple-system,BlinkMacSystemFont,sans-serif;
    background:#f7f6f3; color:#37352f; line-height:1.6;
  }}
  .header {{
    background:linear-gradient(135deg,#2d3436,#636e72);
    color:white; padding:40px 32px 32px;
  }}
  .header h1 {{ font-size:28px; font-weight:700; margin-bottom:8px; }}
  .header .date {{ font-size:14px; opacity:0.8; }}
  .header .stats {{ display:flex; gap:16px; margin-top:16px; font-size:13px; flex-wrap:wrap; }}
  .header .stats span {{
    background:rgba(255,255,255,0.15); padding:4px 12px; border-radius:12px;
  }}
  .filters {{
    padding:16px 32px; display:flex; align-items:center; gap:8px; flex-wrap:wrap;
    background:white; border-bottom:1px solid #e8e5e0; position:sticky; top:0; z-index:10;
  }}
  .filter-btn {{
    padding:6px 16px; border-radius:20px; border:1px solid #e0ddd8;
    background:white; cursor:pointer; font-size:13px; font-family:inherit; transition:all 0.2s;
  }}
  .filter-btn:hover {{ background:#f0efed; }}
  .filter-btn.active {{ background:#37352f; color:white; border-color:#37352f; }}
  .filter-divider {{ width:1px; height:24px; background:#e0ddd8; margin:0 4px; }}
  .gallery {{
    display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
    gap:20px; padding:24px 32px 48px; max-width:1400px; margin:0 auto;
  }}
  .card {{
    background:white; border-radius:12px; overflow:hidden;
    box-shadow:0 1px 3px rgba(0,0,0,0.08); transition:all 0.25s ease;
    cursor:pointer; text-decoration:none; color:inherit; display:block;
  }}
  .card:hover {{ box-shadow:0 8px 24px rgba(0,0,0,0.12); transform:translateY(-3px); }}
  .card-image {{ width:100%; height:200px; object-fit:cover; display:block; background:#e8e5e0; }}
  .card-placeholder {{
    width:100%; height:200px; display:flex; align-items:center; justify-content:center;
    font-size:64px; font-weight:700; color:white;
  }}
  .card-body {{ padding:16px; }}
  .card-source {{ display:inline-flex; align-items:center; gap:6px; font-size:12px; font-weight:500; margin-bottom:8px; }}
  .card-source .dot {{ width:8px; height:8px; border-radius:50%; display:inline-block; }}
  .card-title {{
    font-size:15px; font-weight:600; line-height:1.5; margin-bottom:8px;
    display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden;
  }}
  .card-summary {{
    font-size:13px; color:#787774; line-height:1.5;
    display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; margin-bottom:8px;
  }}
  .card-meta {{ display:flex; align-items:center; justify-content:space-between; font-size:12px; color:#9b9a97; }}
  .card-category {{ background:#f0efed; padding:2px 8px; border-radius:4px; font-size:11px; }}
  .loading {{ text-align:center; padding:80px; color:#9b9a97; font-size:15px; }}

  /* 設定パネル */
  .settings-fab {{
    position:fixed; bottom:24px; right:24px; width:56px; height:56px; border-radius:50%;
    background:#37352f; color:white; border:none; font-size:24px; cursor:pointer;
    box-shadow:0 4px 12px rgba(0,0,0,0.25); z-index:1000; transition:transform 0.2s;
    display:flex; align-items:center; justify-content:center;
  }}
  .settings-fab:hover {{ transform:scale(1.1); }}
  .settings-overlay {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.4); z-index:1001; }}
  .settings-overlay.open {{ display:block; }}
  .settings-panel {{
    display:none; position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
    width:580px; max-width:90vw; max-height:85vh; background:white; border-radius:16px;
    box-shadow:0 20px 60px rgba(0,0,0,0.3); z-index:1002; overflow:hidden; flex-direction:column;
  }}
  .settings-panel.open {{ display:flex; }}
  .settings-header {{
    padding:20px 24px; border-bottom:1px solid #e8e5e0;
    display:flex; justify-content:space-between; align-items:center;
  }}
  .settings-header h2 {{ font-size:18px; font-weight:700; }}
  .settings-close {{
    background:none; border:none; font-size:20px; cursor:pointer; color:#9b9a97;
    padding:4px 8px; border-radius:4px;
  }}
  .settings-close:hover {{ background:#f0efed; }}
  .settings-body {{ padding:20px 24px; overflow-y:auto; flex:1; }}
  .settings-section {{ margin-bottom:20px; }}
  .settings-section h3 {{ font-size:15px; font-weight:700; margin-bottom:12px; }}
  .site-item {{
    display:flex; align-items:center; gap:12px;
    padding:10px 12px; border-radius:8px; margin-bottom:6px; background:#f7f6f3;
  }}
  .site-item .dot {{ width:10px; height:10px; border-radius:50%; flex-shrink:0; }}
  .site-item .info {{ flex:1; }}
  .site-item .name {{ font-size:14px; font-weight:600; }}
  .site-item .type {{ font-size:11px; color:#9b9a97; }}
  .site-item .check {{ width:18px; height:18px; accent-color:#37352f; }}
  .add-form {{ padding:12px; border:2px dashed #e0ddd8; border-radius:10px; margin-top:10px; }}
  .add-row {{ display:flex; gap:8px; }}
  .add-row input {{
    flex:1; padding:8px 12px; border:1px solid #e0ddd8;
    border-radius:8px; font-size:14px; font-family:inherit; outline:none;
  }}
  .add-row input:focus {{ border-color:#37352f; }}
  .btn {{
    padding:8px 16px; border:none; border-radius:8px;
    font-size:13px; font-family:inherit; cursor:pointer; white-space:nowrap;
  }}
  .btn-dark {{ background:#37352f; color:white; }}
  .btn-dark:hover {{ background:#4a4a45; }}
  .btn-green {{ background:#34A853; color:white; }}
  .btn-green:hover {{ background:#2d8f47; }}
  .btn-blue {{ background:#1A73E8; color:white; }}
  .btn-blue:hover {{ background:#1557b0; }}
  .btn:disabled {{ background:#9b9a97 !important; cursor:not-allowed; }}
  .status {{ font-size:12px; margin-top:6px; min-height:18px; }}
  .status.error {{ color:#e74c3c; }}
  .status.success {{ color:#34a853; }}
  .status.loading {{ color:#787774; }}
  .email-field {{ margin-bottom:10px; }}
  .email-field label {{ display:block; font-size:12px; color:#787774; margin-bottom:4px; font-weight:500; }}
  .email-field input {{
    width:100%; padding:8px 12px; border:1px solid #e0ddd8;
    border-radius:8px; font-size:14px; font-family:inherit; outline:none;
  }}
  .email-field input:focus {{ border-color:#37352f; }}
  .email-tags {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }}
  .email-tag {{
    display:inline-flex; align-items:center; gap:4px;
    background:#f0efed; padding:4px 10px; border-radius:16px; font-size:13px;
  }}
  .email-tag button {{
    background:none; border:none; color:#9b9a97; cursor:pointer; font-size:14px; padding:0 2px;
  }}
  .email-tag button:hover {{ color:#e74c3c; }}
  @media (max-width:768px) {{
    .header {{ padding:24px 16px 20px; }}
    .header h1 {{ font-size:22px; }}
    .filters {{ padding:12px 16px; }}
    .gallery {{ grid-template-columns:1fr; padding:16px; gap:16px; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>最新ニュース</h1>
  <div class="date" id="dateInfo">読み込み中...</div>
  <div class="stats" id="statsInfo"></div>
</div>

<div class="filters" id="filters">
  <button class="filter-btn active" data-filter="date" data-value="all">すべて</button>
  <button class="filter-btn" data-filter="date" data-value="recent">24時間以内</button>
  <button class="filter-btn" data-filter="date" data-value="older">24時間以前</button>
  <div class="filter-divider"></div>
  <button class="filter-btn active" data-filter="source" data-value="all">全メディア</button>
</div>

<div class="gallery" id="gallery">
  <div class="loading">記事を読み込み中...</div>
</div>

<!-- 設定ボタン -->
<button class="settings-fab" onclick="toggleSettings()" title="設定">
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <circle cx="12" cy="12" r="3"></circle>
    <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"></path>
  </svg>
</button>
<div class="settings-overlay" id="settingsOverlay" onclick="toggleSettings()"></div>
<div class="settings-panel" id="settingsPanel">
  <div class="settings-header">
    <h2>設定</h2>
    <button class="settings-close" onclick="toggleSettings()">&times;</button>
  </div>
  <div class="settings-body">
    <div class="settings-section">
      <h3>表示サイト</h3>
      <div id="sitesList"></div>
      <div class="add-form">
        <div class="add-row">
          <input type="text" id="addUrl" placeholder="サイトURLを入力して追加">
          <button class="btn btn-dark" onclick="addSite()">追加</button>
        </div>
        <div class="status" id="addStatus"></div>
      </div>
      <div style="margin-top:12px; text-align:center;">
        <button class="btn btn-blue" onclick="applyAndReload()">この設定で記事を更新</button>
      </div>
    </div>
    <div class="settings-section" style="padding-top:20px; border-top:1px solid #e8e5e0;">
      <h3>送信先リスト</h3>
      <div class="email-field">
        <div class="email-tags" id="recipientsList"></div>
        <div class="add-row" style="margin-top:8px;">
          <input type="email" id="newRecipient" placeholder="メールアドレスを入力">
          <button class="btn btn-dark" onclick="addRecipient()">追加</button>
        </div>
      </div>
      <div style="margin-top:12px;">
        <button class="btn btn-dark" onclick="saveEmailSettings()">保存</button>
        <button class="btn btn-green" style="margin-left:8px;" id="emailTestBtn" onclick="testEmail()">テスト送信</button>
      </div>
      <div class="status" id="emailStatus"></div>
    </div>
  </div>
</div>

<script>
const ALL_SITES = {sites_json};
const DEFAULT_IDS = {default_ids};
const now = new Date();
const cutoff = new Date(now.getTime() - 24 * 60 * 60 * 1000);
let currentDate = 'all';
let currentSource = 'all';
let allArticles = [];

// ── localStorage でサイト選択を管理 ──
function getSelectedIds() {{
  const saved = localStorage.getItem('selectedSites');
  if (saved) return JSON.parse(saved);
  return DEFAULT_IDS;
}}
function saveSelectedIds(ids) {{
  localStorage.setItem('selectedSites', JSON.stringify(ids));
}}

// ── 記事読み込み ──
async function loadArticles() {{
  const ids = getSelectedIds();
  document.getElementById('gallery').innerHTML = '<div class="loading">記事を読み込み中...</div>';
  try {{
    const resp = await fetch('/api/articles?sites=' + ids.join(','));
    const data = await resp.json();
    allArticles = data.articles || [];
    renderGallery();
    renderHeader();
    renderSourceFilters();
  }} catch(e) {{
    document.getElementById('gallery').innerHTML = '<div class="loading">読み込みエラー</div>';
  }}
}}

function renderHeader() {{
  const now = new Date();
  document.getElementById('dateInfo').textContent =
    now.getFullYear()+'年'+(now.getMonth()+1)+'月'+now.getDate()+'日 更新';
  const counts = {{}};
  allArticles.forEach(a => {{ counts[a.source] = (counts[a.source]||0)+1; }});
  document.getElementById('statsInfo').innerHTML =
    Object.entries(counts).map(([k,v]) => `<span>${{k}}: ${{v}}件</span>`).join('') +
    `<span>合計: ${{allArticles.length}}件</span>`;
}}

function renderSourceFilters() {{
  const sources = [...new Set(allArticles.map(a => a.source))];
  const container = document.querySelector('.filters');
  // 既存のソースボタンを削除
  container.querySelectorAll('[data-filter="source"]').forEach(b => b.remove());
  // 全メディアボタン + 各ソースボタンを追加
  const allBtn = document.createElement('button');
  allBtn.className = 'filter-btn active';
  allBtn.dataset.filter = 'source';
  allBtn.textContent = '全メディア';
  allBtn.dataset.value = 'all';
  container.appendChild(allBtn);
  sources.forEach(src => {{
    const btn = document.createElement('button');
    btn.className = 'filter-btn';
    btn.dataset.filter = 'source';
    btn.dataset.value = src;
    btn.textContent = src;
    container.appendChild(btn);
  }});
}}

function renderGallery() {{
  const gallery = document.getElementById('gallery');
  if (allArticles.length === 0) {{
    gallery.innerHTML = '<div class="loading">記事がありません</div>';
    return;
  }}
  gallery.innerHTML = allArticles.map(a => `
    <a class="card" href="${{a.url}}" target="_blank"
       data-source="${{a.source}}" data-published="${{a.published}}" data-published-iso="${{a.published_iso}}">
      ${{a.image_url
        ? `<img class="card-image" src="${{a.image_url}}" alt="" loading="lazy"
             onerror="this.outerHTML='<div class=\\'card-placeholder\\' style=\\'background:${{a.source_color}}\\'>${{a.source_icon}}</div>'">`
        : `<div class="card-placeholder" style="background:${{a.source_color}}">${{a.source_icon}}</div>`
      }}
      <div class="card-body">
        <div class="card-source">
          <span class="dot" style="background:${{a.source_color}}"></span>${{a.source}}
        </div>
        <div class="card-title">${{a.title}}</div>
        ${{a.summary ? `<div class="card-summary">${{a.summary}}</div>` : ''}}
        <div class="card-meta">
          <span>${{a.published}}</span>
          ${{a.category ? `<span class="card-category">${{a.category}}</span>` : ''}}
        </div>
      </div>
    </a>
  `).join('');
  applyFilters();
}}

// ── フィルター ──
function applyFilters() {{
  document.querySelectorAll('.card').forEach(card => {{
    const pubIso = card.dataset.publishedIso || '';
    const src = card.dataset.source || '';
    let dateOk = true;
    if (currentDate !== 'all') {{
      if (!pubIso) {{
        dateOk = currentDate === 'recent';
      }} else {{
        const pubDate = new Date(pubIso);
        const isRecent = pubDate >= cutoff;
        dateOk = currentDate === 'recent' ? isRecent : !isRecent;
      }}
    }}
    let sourceOk = currentSource === 'all' || src === currentSource;
    card.style.display = (dateOk && sourceOk) ? '' : 'none';
  }});
}}
document.getElementById('filters').addEventListener('click', function(e) {{
  var btn = e.target;
  while (btn && !btn.classList.contains('filter-btn')) btn = btn.parentElement;
  if (!btn) return;
  var filterType = btn.getAttribute('data-filter');
  var value = btn.getAttribute('data-value');
  if (filterType === 'date') {{
    currentDate = value;
    document.querySelectorAll('[data-filter="date"]').forEach(function(b) {{ b.classList.remove('active'); }});
  }} else if (filterType === 'source') {{
    currentSource = value;
    document.querySelectorAll('[data-filter="source"]').forEach(function(b) {{ b.classList.remove('active'); }});
  }}
  btn.classList.add('active');
  applyFilters();
}});

// ── 設定パネル ──
function toggleSettings() {{
  document.getElementById('settingsOverlay').classList.toggle('open');
  document.getElementById('settingsPanel').classList.toggle('open');
  if (document.getElementById('settingsPanel').classList.contains('open')) {{
    renderSiteSettings();
    loadEmailSettings();
  }}
}}

function renderSiteSettings() {{
  const selected = getSelectedIds();
  document.getElementById('sitesList').innerHTML = ALL_SITES.map((s,i) => `
    <div class="site-item">
      <span class="dot" style="background:${{s.color}}"></span>
      <div class="info">
        <div class="name">${{s.name}}</div>
        <div class="type">${{s.type === 'rss' ? 'RSS' : 'スクレイピング'}}</div>
      </div>
      <input type="checkbox" class="check site-check" value="${{s.id}}"
             ${{selected.includes(s.id) ? 'checked' : ''}}>
    </div>
  `).join('');
}}

function applyAndReload() {{
  const checked = [...document.querySelectorAll('.site-check:checked')].map(cb => cb.value);
  if (checked.length === 0) {{ alert('少なくとも1つ選択してください'); return; }}
  saveSelectedIds(checked);
  toggleSettings();
  loadArticles();
}}

async function addSite() {{
  const urlInput = document.getElementById('addUrl');
  const status = document.getElementById('addStatus');
  const url = urlInput.value.trim();
  if (!url) {{ status.className='status error'; status.textContent='URLを入力'; return; }}
  status.className='status loading'; status.textContent='RSS検出中...';
  try {{
    const resp = await fetch('/api/sites', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{url}})
    }});
    const data = await resp.json();
    if (data.ok) {{
      status.className='status success';
      status.textContent='「'+data.site.name+'」を追加！';
      urlInput.value='';
      ALL_SITES.push(data.site);
      const ids = getSelectedIds();
      ids.push(data.site.id);
      saveSelectedIds(ids);
      renderSiteSettings();
    }} else {{
      status.className='status error'; status.textContent=data.error||'追加失敗';
    }}
  }} catch(e) {{ status.className='status error'; status.textContent='エラー: '+e.message; }}
}}

// ── メール設定 ──
let emailRecipients = [];
async function loadEmailSettings() {{
  const resp = await fetch('/api/email');
  const data = await resp.json();
  emailRecipients = data.recipients || [];
  renderRecipients();
}}
function renderRecipients() {{
  document.getElementById('recipientsList').innerHTML = emailRecipients.map((r,i) =>
    `<span class="email-tag">${{r}}<button onclick="removeRecipient(${{i}})">&times;</button></span>`
  ).join('');
}}
function addRecipient() {{
  const input = document.getElementById('newRecipient');
  const email = input.value.trim();
  if (!email || !email.includes('@') || emailRecipients.includes(email)) return;
  emailRecipients.push(email); input.value=''; renderRecipients();
}}
function removeRecipient(i) {{ emailRecipients.splice(i,1); renderRecipients(); }}
async function saveEmailSettings() {{
  const body = {{ recipients: emailRecipients }};
  const resp = await fetch('/api/email', {{
    method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify(body)
  }});
  const data = await resp.json();
  const status = document.getElementById('emailStatus');
  if (data.ok) {{
    status.className='status success'; status.textContent='保存しました';
    loadEmailSettings();
  }}
}}
async function testEmail() {{
  const status = document.getElementById('emailStatus');
  const btn = document.getElementById('emailTestBtn');
  btn.disabled=true; status.className='status loading'; status.textContent='送信中...';
  const ids = getSelectedIds();
  try {{
    const resp = await fetch('/api/email/test', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{sites:ids}})
    }});
    const data = await resp.json();
    if (data.ok) {{ status.className='status success'; status.textContent=data.count+'件送信！'; }}
    else {{ status.className='status error'; status.textContent=data.error; }}
  }} catch(e) {{ status.className='status error'; status.textContent='エラー: '+e.message; }}
  btn.disabled=false;
}}

document.getElementById('addUrl')?.addEventListener('keydown',e=>{{ if(e.key==='Enter') addSite(); }});
document.getElementById('newRecipient')?.addEventListener('keydown',e=>{{ if(e.key==='Enter') addRecipient(); }});

// 起動
loadArticles();
</script>
</body>
</html>"""


def run_server():
    print(f"\n🌐 サーバー起動: http://0.0.0.0:{PORT}")
    print(f"   Ctrl+C で停止\n")

    print("📡 起動時の記事取得中...")
    try:
        refresh_all_cache()
    except Exception as e:
        print(f"⚠️  起動時取得失敗（アクセス時に再試行します）: {e}")

    schedule_daily_refresh()

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 サーバー停止")
        server.server_close()


if __name__ == "__main__":
    run_server()
