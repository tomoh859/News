#!/usr/bin/env python3
"""ローカルWebサーバー: ギャラリー表示 + サイト管理API"""
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from scraper import fetch_all_articles
from generator import generate_gallery_html
from site_manager import load_sites, save_sites, detect_rss_feeds, pick_color
from config import load_email_settings, save_email_settings
from mailer import send_email, filter_recent_articles
from generator import generate_email_html

import os
PORT = int(os.environ.get("PORT", 8080))
articles_cache = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/" or path == "":
            self._serve_gallery()
        elif path == "/api/sites":
            self._json_response(load_sites())
        elif path == "/api/detect-rss":
            params = parse_qs(urlparse(self.path).query)
            url = params.get("url", [""])[0]
            if not url:
                self._json_response({"error": "urlパラメータが必要です"}, 400)
                return
            feeds = detect_rss_feeds(url)
            self._json_response({"feeds": feeds})
        elif path == "/api/refresh":
            self._refresh_articles()
            self._json_response({"count": len(articles_cache)})
        elif path == "/api/email":
            settings = load_email_settings()
            # パスワードはマスクして返す
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
        elif path == "/api/sites/update":
            self._update_site(body)
        elif path == "/api/email":
            self._update_email(body)
        elif path == "/api/email/test":
            self._test_email(body)
        else:
            self._text_response("Not Found", 404)

    def _serve_gallery(self):
        global articles_cache
        if not articles_cache:
            self._refresh_articles()
        html = generate_gallery_with_settings(articles_cache)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _refresh_articles(self):
        global articles_cache
        articles_cache = fetch_all_articles()

    def _add_site(self, body: dict):
        url = body.get("url", "")
        name = body.get("name", "")
        feed_url = body.get("feed_url", "")

        if not url and not feed_url:
            self._json_response({"error": "URLが必要です"}, 400)
            return

        sites = load_sites()
        parsed = urlparse(url if url.startswith("http") else "https://" + url)

        # 重複チェック
        check_domain = parsed.netloc or url
        for s in sites:
            if check_domain in s.get("url", ""):
                self._json_response({"error": f"{check_domain} は既に登録済みです"}, 409)
                return

        if feed_url:
            # RSS URLが直接指定された場合
            new_site = {
                "name": name or parsed.netloc,
                "type": "rss",
                "url": feed_url,
                "color": pick_color(sites),
                "icon": (name or parsed.netloc)[0].upper(),
            }
        else:
            # 自動検出結果を使う場合
            feeds = detect_rss_feeds(url)
            if feeds:
                feed = feeds[0]
                new_site = {
                    "name": name or feed["title"] or parsed.netloc,
                    "type": "rss",
                    "url": feed["url"],
                    "color": pick_color(sites),
                    "icon": (name or feed["title"] or parsed.netloc)[0].upper(),
                }
            else:
                new_site = {
                    "name": name or parsed.netloc,
                    "type": "scrape",
                    "url": url if url.startswith("http") else "https://" + url,
                    "color": pick_color(sites),
                    "icon": (name or parsed.netloc)[0].upper(),
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

    def _update_site(self, body: dict):
        index = body.get("index")
        if index is None:
            self._json_response({"error": "indexが必要です"}, 400)
            return
        sites = load_sites()
        if 0 <= index < len(sites):
            if "max_articles" in body:
                sites[index]["max_articles"] = max(1, min(100, int(body["max_articles"])))
            if "name" in body:
                sites[index]["name"] = body["name"]
            save_sites(sites)
            self._json_response({"ok": True, "site": sites[index]})
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
        global articles_cache
        if not articles_cache:
            self._refresh_articles()
        recent = filter_recent_articles(articles_cache, hours=24)
        if not recent:
            self._json_response({"error": "24時間以内の新着記事がありません"}, 400)
            return
        email_html = generate_email_html(recent)
        success, error_msg = send_email(email_html)
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

    def _text_response(self, text, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))

    def log_message(self, format, *args):
        pass  # アクセスログを抑制


def generate_gallery_with_settings(articles):
    """ギャラリーHTML + 設定パネル付きを生成"""
    from generator import generate_gallery_html
    html = generate_gallery_html(articles)

    settings_panel = r"""
<style>
  /* ── 設定ボタン ── */
  .settings-fab {
    position: fixed;
    bottom: 24px;
    right: 24px;
    width: 56px;
    height: 56px;
    border-radius: 50%;
    background: #37352f;
    color: white;
    border: none;
    font-size: 24px;
    cursor: pointer;
    box-shadow: 0 4px 12px rgba(0,0,0,0.25);
    z-index: 1000;
    transition: transform 0.2s;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .settings-fab:hover { transform: scale(1.1); }

  /* ── オーバーレイ ── */
  .settings-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.4);
    z-index: 1001;
  }
  .settings-overlay.open { display: block; }

  /* ── 設定パネル ── */
  .settings-panel {
    display: none;
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 560px;
    max-width: 90vw;
    max-height: 80vh;
    background: white;
    border-radius: 16px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.3);
    z-index: 1002;
    overflow: hidden;
    flex-direction: column;
  }
  .settings-panel.open { display: flex; }

  .settings-header {
    padding: 20px 24px;
    border-bottom: 1px solid #e8e5e0;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .settings-header h2 {
    font-size: 18px;
    font-weight: 700;
  }
  .settings-close {
    background: none;
    border: none;
    font-size: 20px;
    cursor: pointer;
    color: #9b9a97;
    padding: 4px 8px;
    border-radius: 4px;
  }
  .settings-close:hover { background: #f0efed; }

  .settings-body {
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
  }

  /* ── サイト一覧 ── */
  .site-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px;
    border-radius: 8px;
    margin-bottom: 8px;
    background: #f7f6f3;
  }
  .site-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .site-info { flex: 1; }
  .site-info .site-name { font-weight: 600; font-size: 14px; }
  .site-info .site-url { font-size: 12px; color: #9b9a97; word-break: break-all; }
  .site-info .site-type {
    display: inline-block;
    font-size: 11px;
    padding: 1px 6px;
    border-radius: 4px;
    background: #e8e5e0;
    margin-top: 2px;
  }
  .site-delete {
    background: none;
    border: none;
    color: #9b9a97;
    cursor: pointer;
    font-size: 18px;
    padding: 4px 8px;
    border-radius: 4px;
  }
  .site-delete:hover { background: #fee; color: #e74c3c; }
  .site-max {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }
  .site-max label {
    font-size: 11px;
    color: #9b9a97;
  }
  .site-max input {
    width: 48px;
    padding: 3px 6px;
    border: 1px solid #e0ddd8;
    border-radius: 6px;
    font-size: 13px;
    text-align: center;
    font-family: inherit;
    outline: none;
  }
  .site-max input:focus { border-color: #37352f; }

  /* ── 追加フォーム ── */
  .add-form {
    margin-top: 16px;
    padding: 16px;
    border: 2px dashed #e0ddd8;
    border-radius: 12px;
  }
  .add-form h3 { font-size: 14px; font-weight: 600; margin-bottom: 12px; }
  .add-row {
    display: flex;
    gap: 8px;
    margin-bottom: 8px;
  }
  .add-row input {
    flex: 1;
    padding: 8px 12px;
    border: 1px solid #e0ddd8;
    border-radius: 8px;
    font-size: 14px;
    font-family: inherit;
    outline: none;
  }
  .add-row input:focus { border-color: #37352f; }
  .add-btn {
    padding: 8px 20px;
    background: #37352f;
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-family: inherit;
    cursor: pointer;
    white-space: nowrap;
  }
  .add-btn:hover { background: #4a4a45; }
  .add-btn:disabled { background: #9b9a97; cursor: not-allowed; }
  .add-status {
    font-size: 13px;
    margin-top: 8px;
    min-height: 20px;
  }
  .add-status.error { color: #e74c3c; }
  .add-status.success { color: #34a853; }
  .add-status.loading { color: #787774; }

  /* ── リフレッシュボタン ── */
  .refresh-section {
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid #e8e5e0;
    display: flex;
    justify-content: center;
  }
  .refresh-btn {
    padding: 10px 24px;
    background: #1A73E8;
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-family: inherit;
    cursor: pointer;
  }
  .refresh-btn:hover { background: #1557b0; }
  .refresh-btn:disabled { background: #9b9a97; cursor: not-allowed; }

  /* ── メール設定 ── */
  .email-section {
    margin-top: 20px;
    padding-top: 20px;
    border-top: 1px solid #e8e5e0;
  }
  .email-section h3 {
    font-size: 15px;
    font-weight: 700;
    margin-bottom: 12px;
  }
  .email-field {
    margin-bottom: 10px;
  }
  .email-field label {
    display: block;
    font-size: 12px;
    color: #787774;
    margin-bottom: 4px;
    font-weight: 500;
  }
  .email-field input {
    width: 100%;
    padding: 8px 12px;
    border: 1px solid #e0ddd8;
    border-radius: 8px;
    font-size: 14px;
    font-family: inherit;
    outline: none;
  }
  .email-field input:focus { border-color: #37352f; }
  .email-recipients {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 6px;
  }
  .email-tag {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: #f0efed;
    padding: 4px 10px;
    border-radius: 16px;
    font-size: 13px;
  }
  .email-tag button {
    background: none;
    border: none;
    color: #9b9a97;
    cursor: pointer;
    font-size: 14px;
    padding: 0 2px;
  }
  .email-tag button:hover { color: #e74c3c; }
  .email-add-row {
    display: flex;
    gap: 8px;
    margin-top: 6px;
  }
  .email-add-row input { flex: 1; }
  .email-save-btn {
    padding: 8px 20px;
    background: #37352f;
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 13px;
    font-family: inherit;
    cursor: pointer;
    margin-top: 12px;
  }
  .email-save-btn:hover { background: #4a4a45; }
  .email-test-btn {
    padding: 8px 20px;
    background: #34A853;
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 13px;
    font-family: inherit;
    cursor: pointer;
    margin-top: 12px;
    margin-left: 8px;
  }
  .email-test-btn:hover { background: #2d8f47; }
  .email-test-btn:disabled, .email-save-btn:disabled { background: #9b9a97; cursor: not-allowed; }
  .email-status {
    font-size: 13px;
    margin-top: 8px;
    min-height: 20px;
  }
</style>

<!-- 設定ボタン（歯車） -->
<button class="settings-fab" onclick="toggleSettings()" title="サイト設定">
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <circle cx="12" cy="12" r="3"></circle>
    <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"></path>
  </svg>
</button>

<!-- オーバーレイ -->
<div class="settings-overlay" id="settingsOverlay" onclick="toggleSettings()"></div>

<!-- 設定パネル -->
<div class="settings-panel" id="settingsPanel">
  <div class="settings-header">
    <h2>サイト管理</h2>
    <button class="settings-close" onclick="toggleSettings()">&times;</button>
  </div>
  <div class="settings-body">
    <div id="sitesList"></div>

    <div class="add-form">
      <h3>+ サイトを追加</h3>
      <div class="add-row">
        <input type="text" id="addUrl" placeholder="サイトURL（例: techcrunch.com）">
      </div>
      <div class="add-row">
        <input type="text" id="addName" placeholder="表示名（空欄で自動検出）">
        <button class="add-btn" id="addBtn" onclick="addSite()">追加</button>
      </div>
      <div class="add-status" id="addStatus"></div>
    </div>

    <div class="refresh-section">
      <button class="refresh-btn" id="refreshBtn" onclick="refreshArticles()">
        記事を再取得して更新
      </button>
    </div>

    <!-- メール設定 -->
    <div class="email-section">
      <h3>メール設定</h3>
      <div class="email-field">
        <label>送信元Gmailアドレス</label>
        <input type="email" id="emailSender" placeholder="your-email@gmail.com">
      </div>
      <div class="email-field">
        <label>アプリパスワード（未変更なら空欄のまま）</label>
        <input type="password" id="emailPassword" placeholder="設定済み">
      </div>
      <div class="email-field">
        <label>送信先アドレス</label>
        <div class="email-recipients" id="recipientsList"></div>
        <div class="email-add-row">
          <input type="email" id="newRecipient" placeholder="送信先メールアドレスを入力">
          <button class="add-btn" onclick="addRecipient()">追加</button>
        </div>
      </div>
      <div>
        <button class="email-save-btn" id="emailSaveBtn" onclick="saveEmailSettings()">保存</button>
        <button class="email-test-btn" id="emailTestBtn" onclick="testEmail()">テスト送信</button>
      </div>
      <div class="email-status" id="emailStatus"></div>
      <div style="font-size:11px; color:#9b9a97; margin-top:8px;">
        ※ テスト送信は24時間以内の記事のみ送信します<br>
        ※ Gmailの場合は<a href="https://myaccount.google.com/apppasswords" target="_blank" style="color:#1A73E8;">アプリパスワード</a>が必要です
      </div>
    </div>
  </div>
</div>

<script>
function toggleSettings() {
  document.getElementById('settingsOverlay').classList.toggle('open');
  document.getElementById('settingsPanel').classList.toggle('open');
  if (document.getElementById('settingsPanel').classList.contains('open')) {
    loadSites();
    loadEmailSettings();
  }
}

async function loadSites() {
  const resp = await fetch('/api/sites');
  const sites = await resp.json();
  const container = document.getElementById('sitesList');
  container.innerHTML = sites.map((s, i) => `
    <div class="site-item">
      <div class="site-dot" style="background:${s.color}"></div>
      <div class="site-info">
        <div class="site-name">${s.name}</div>
        <div class="site-url">${s.url}</div>
        <span class="site-type">${s.type === 'rss' ? 'RSS' : 'スクレイピング'}</span>
      </div>
      <div class="site-max">
        <label>取得数</label>
        <input type="number" min="1" max="100" value="${s.max_articles || 30}"
               onchange="updateMaxArticles(${i}, this.value)" title="取得する記事数">
      </div>
      <button class="site-delete" onclick="deleteSite(${i}, '${s.name.replace(/'/g, "\\'")}')" title="削除">&times;</button>
    </div>
  `).join('');
}

async function updateMaxArticles(index, value) {
  await fetch('/api/sites/update', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({index, max_articles: parseInt(value)})
  });
}

async function deleteSite(index, name) {
  if (!confirm(name + ' を削除しますか？')) return;
  const resp = await fetch('/api/sites/delete', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({index})
  });
  const data = await resp.json();
  if (data.ok) loadSites();
}

async function addSite() {
  const url = document.getElementById('addUrl').value.trim();
  const name = document.getElementById('addName').value.trim();
  const status = document.getElementById('addStatus');
  const btn = document.getElementById('addBtn');

  if (!url) {
    status.className = 'add-status error';
    status.textContent = 'URLを入力してください';
    return;
  }

  btn.disabled = true;
  status.className = 'add-status loading';
  status.textContent = 'RSSフィードを検出中...';

  try {
    const resp = await fetch('/api/sites', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url, name})
    });
    const data = await resp.json();

    if (data.ok) {
      status.className = 'add-status success';
      status.textContent = '「' + data.site.name + '」を追加しました！（' +
        (data.site.type === 'rss' ? 'RSS' : 'スクレイピング') + '）';
      document.getElementById('addUrl').value = '';
      document.getElementById('addName').value = '';
      loadSites();
    } else {
      status.className = 'add-status error';
      status.textContent = data.error || '追加に失敗しました';
    }
  } catch (e) {
    status.className = 'add-status error';
    status.textContent = 'エラー: ' + e.message;
  }
  btn.disabled = false;
}

async function refreshArticles() {
  const btn = document.getElementById('refreshBtn');
  btn.disabled = true;
  btn.textContent = '取得中...';
  try {
    await fetch('/api/refresh');
    location.reload();
  } catch (e) {
    btn.textContent = 'エラー。再試行してください。';
    btn.disabled = false;
  }
}

// ── メール設定 ──
let emailRecipients = [];

async function loadEmailSettings() {
  const resp = await fetch('/api/email');
  const data = await resp.json();
  document.getElementById('emailSender').value = data.sender || '';
  document.getElementById('emailPassword').placeholder = data.password_set ? '設定済み（変更する場合のみ入力）' : 'アプリパスワードを入力';
  emailRecipients = data.recipients || [];
  renderRecipients();
}

function renderRecipients() {
  const container = document.getElementById('recipientsList');
  container.innerHTML = emailRecipients.map((r, i) => `
    <span class="email-tag">${r}<button onclick="removeRecipient(${i})">&times;</button></span>
  `).join('');
}

function addRecipient() {
  const input = document.getElementById('newRecipient');
  const email = input.value.trim();
  if (!email || !email.includes('@')) return;
  if (emailRecipients.includes(email)) return;
  emailRecipients.push(email);
  input.value = '';
  renderRecipients();
}

function removeRecipient(index) {
  emailRecipients.splice(index, 1);
  renderRecipients();
}

async function saveEmailSettings() {
  const status = document.getElementById('emailStatus');
  const sender = document.getElementById('emailSender').value.trim();
  const password = document.getElementById('emailPassword').value;

  const body = { sender, recipients: emailRecipients };
  if (password) body.password = password;

  try {
    const resp = await fetch('/api/email', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    const data = await resp.json();
    if (data.ok) {
      status.className = 'add-status success';
      status.textContent = 'メール設定を保存しました';
      document.getElementById('emailPassword').value = '';
      loadEmailSettings();
    }
  } catch (e) {
    status.className = 'add-status error';
    status.textContent = 'エラー: ' + e.message;
  }
}

async function testEmail() {
  const status = document.getElementById('emailStatus');
  const btn = document.getElementById('emailTestBtn');
  btn.disabled = true;
  status.className = 'add-status loading';
  status.textContent = '24時間以内の記事をメール送信中...';

  try {
    const resp = await fetch('/api/email/test', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({})
    });
    const data = await resp.json();
    if (data.ok) {
      status.className = 'add-status success';
      status.textContent = data.count + '件の記事を送信しました！';
    } else {
      status.className = 'add-status error';
      status.textContent = data.error || '送信に失敗しました';
    }
  } catch (e) {
    status.className = 'add-status error';
    status.textContent = 'エラー: ' + e.message;
  }
  btn.disabled = false;
}

// Enterキーで追加
document.addEventListener('DOMContentLoaded', () => {
  ['addUrl', 'addName'].forEach(id => {
    document.getElementById(id)?.addEventListener('keydown', e => {
      if (e.key === 'Enter') addSite();
    });
  });
  document.getElementById('newRecipient')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') addRecipient();
  });
});
</script>
"""

    # </body> の前に設定パネルを挿入
    html = html.replace("</body>", settings_panel + "\n</body>")
    return html


def run_server():
    print(f"\n🌐 サーバー起動: http://0.0.0.0:{PORT}")
    print(f"   Ctrl+C で停止\n")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 サーバー停止")
        server.server_close()


if __name__ == "__main__":
    run_server()
