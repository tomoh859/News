#!/usr/bin/env python3
"""
ビルドスクリプト: 全サイトの記事を取得してJSON + HTMLを生成
GitHub Actionsから毎朝実行される
"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

from scraper import fetch_all_articles
from site_manager import load_sites

JST = timezone(timedelta(hours=9))
DOCS_DIR = Path(__file__).parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)


def build():
    now = datetime.now(JST)
    print(f"🕐 ビルド開始: {now.strftime('%Y-%m-%d %H:%M')}")

    # 1. 全サイトの記事を取得
    articles = fetch_all_articles()
    print(f"📊 合計 {len(articles)} 件の記事を取得")

    # 2. サイト一覧
    sites = load_sites()

    # 3. 記事をJSON化
    articles_data = [{
        "title": a.title,
        "url": a.url,
        "source": a.source,
        "source_color": a.source_color,
        "source_icon": a.source_icon,
        "published": a.published,
        "summary": a.summary,
        "image_url": a.image_url,
        "category": a.category,
    } for a in articles]

    # 4. JSONファイル出力（Power Automate用）
    data = {
        "generated_at": now.isoformat(),
        "generated_date": now.strftime("%Y-%m-%d"),
        "sites": sites,
        "articles": articles_data,
        "count": len(articles_data),
    }
    json_path = DOCS_DIR / "articles.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📄 JSON保存: {json_path}")

    # 5. HTMLファイル出力（GitHub Pages用）
    html = generate_static_html(sites, articles_data, now)
    html_path = DOCS_DIR / "index.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"📄 HTML保存: {html_path}")

    print("✅ ビルド完了!")


def generate_static_html(sites, articles, now):
    """全記事データを埋め込んだ静的HTMLを生成"""
    sites_json = json.dumps(sites, ensure_ascii=False)
    articles_json = json.dumps(articles, ensure_ascii=False)
    default_ids = json.dumps([s["id"] for s in sites])
    generated_at = now.strftime("%Y年%m月%d日 %H:%M 更新")

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>マーケティングニュース</title>
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
  .header .stats span {{ background:rgba(255,255,255,0.15); padding:4px 12px; border-radius:12px; }}
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
    background:#37352f; color:white; border:none; cursor:pointer;
    box-shadow:0 4px 12px rgba(0,0,0,0.25); z-index:1000; transition:transform 0.2s;
    display:flex; align-items:center; justify-content:center;
  }}
  .settings-fab:hover {{ transform:scale(1.1); }}
  .settings-overlay {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.4); z-index:1001; }}
  .settings-overlay.open {{ display:block; }}
  .settings-panel {{
    display:none; position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
    width:520px; max-width:90vw; max-height:80vh; background:white; border-radius:16px;
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
  .site-item {{
    display:flex; align-items:center; gap:12px;
    padding:10px 12px; border-radius:8px; margin-bottom:6px; background:#f7f6f3;
  }}
  .site-item .dot {{ width:10px; height:10px; border-radius:50%; flex-shrink:0; }}
  .site-item .info {{ flex:1; }}
  .site-item .name {{ font-size:14px; font-weight:600; }}
  .site-item .type {{ font-size:11px; color:#9b9a97; }}
  .site-item .check {{ width:18px; height:18px; accent-color:#37352f; }}
  .apply-btn {{
    display:block; width:100%; margin-top:16px; padding:14px;
    background:#37352f; color:white; border:none; border-radius:10px;
    font-size:15px; font-weight:600; font-family:inherit; cursor:pointer; text-align:center;
  }}
  .apply-btn:hover {{ background:#4a4a45; }}
  .hint {{ font-size:12px; color:#9b9a97; margin-top:8px; text-align:center; }}
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
  <h1>マーケティングニュース</h1>
  <div class="date">{generated_at}</div>
  <div class="stats" id="statsInfo"></div>
</div>

<div class="filters" id="filtersBar">
  <button class="filter-btn active" data-filter="date" onclick="filterByDate('all')">すべて</button>
  <button class="filter-btn" data-filter="date" onclick="filterByDate('today')">本日</button>
  <button class="filter-btn" data-filter="date" onclick="filterByDate('older')">昨日以前</button>
  <div class="filter-divider"></div>
</div>

<div class="gallery" id="gallery"></div>

<button class="settings-fab" onclick="toggleSettings()" title="設定">
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <circle cx="12" cy="12" r="3"></circle>
    <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"></path>
  </svg>
</button>
<div class="settings-overlay" id="settingsOverlay" onclick="toggleSettings()"></div>
<div class="settings-panel" id="settingsPanel">
  <div class="settings-header">
    <h2>表示サイトを選択</h2>
    <button class="settings-close" onclick="toggleSettings()">&times;</button>
  </div>
  <div class="settings-body">
    <div id="sitesList"></div>
    <button class="apply-btn" onclick="applyAndReload()">この設定で表示を更新</button>
    <div class="hint">設定はこのブラウザに保存されます（URLは変わりません）</div>
  </div>
</div>

<script>
const ALL_SITES = {sites_json};
const ALL_ARTICLES = {articles_json};
const DEFAULT_IDS = {default_ids};
const today = new Date().toISOString().slice(0,10);
let currentDate = 'all';
let currentSource = 'all';

function getSelectedIds() {{
  const saved = localStorage.getItem('selectedSites');
  if (saved) return JSON.parse(saved);
  return DEFAULT_IDS;
}}
function saveSelectedIds(ids) {{ localStorage.setItem('selectedSites', JSON.stringify(ids)); }}

function getFilteredArticles() {{
  const ids = getSelectedIds();
  const selectedNames = ALL_SITES.filter(s => ids.includes(s.id)).map(s => s.name);
  return ALL_ARTICLES.filter(a => selectedNames.includes(a.source));
}}

function render() {{
  const articles = getFilteredArticles();
  renderStats(articles);
  renderSourceFilters(articles);
  renderGallery(articles);
}}

function renderStats(articles) {{
  const counts = {{}};
  articles.forEach(a => {{ counts[a.source] = (counts[a.source]||0)+1; }});
  document.getElementById('statsInfo').innerHTML =
    Object.entries(counts).map(([k,v]) => `<span>${{k}}: ${{v}}件</span>`).join('') +
    `<span>合計: ${{articles.length}}件</span>`;
}}

function renderSourceFilters(articles) {{
  const bar = document.getElementById('filtersBar');
  bar.querySelectorAll('[data-filter="source"]').forEach(b => b.remove());
  const sources = [...new Set(articles.map(a => a.source))];
  const allBtn = document.createElement('button');
  allBtn.className = 'filter-btn active'; allBtn.dataset.filter = 'source';
  allBtn.textContent = '全メディア'; allBtn.onclick = () => filterBySource('all');
  bar.appendChild(allBtn);
  sources.forEach(src => {{
    const btn = document.createElement('button');
    btn.className = 'filter-btn'; btn.dataset.filter = 'source';
    btn.textContent = src; btn.onclick = () => filterBySource(src);
    bar.appendChild(btn);
  }});
}}

function renderGallery(articles) {{
  const gallery = document.getElementById('gallery');
  if (!articles.length) {{ gallery.innerHTML = '<div class="loading">表示する記事がありません</div>'; return; }}
  gallery.innerHTML = articles.map(a => `
    <a class="card" href="${{a.url}}" target="_blank" data-source="${{a.source}}" data-published="${{a.published}}">
      ${{a.image_url
        ? `<img class="card-image" src="${{a.image_url}}" alt="" loading="lazy"
             onerror="this.outerHTML='<div class=\\'card-placeholder\\' style=\\'background:${{a.source_color}}\\'>${{a.source_icon}}</div>'">`
        : `<div class="card-placeholder" style="background:${{a.source_color}}">${{a.source_icon}}</div>`}}
      <div class="card-body">
        <div class="card-source"><span class="dot" style="background:${{a.source_color}}"></span>${{a.source}}</div>
        <div class="card-title">${{a.title}}</div>
        ${{a.summary ? `<div class="card-summary">${{a.summary}}</div>` : ''}}
        <div class="card-meta">
          <span>${{a.published}}</span>
          ${{a.category ? `<span class="card-category">${{a.category}}</span>` : ''}}
        </div>
      </div>
    </a>
  `).join('');
}}

function applyFilters() {{
  document.querySelectorAll('.card').forEach(card => {{
    const pub = card.dataset.published || '';
    const src = card.dataset.source || '';
    let dateOk = currentDate === 'all' || (currentDate === 'today' ? pub === today : pub !== today && pub !== '');
    let sourceOk = currentSource === 'all' || src === currentSource;
    card.style.display = (dateOk && sourceOk) ? '' : 'none';
  }});
}}
function filterByDate(v) {{
  currentDate = v;
  document.querySelectorAll('[data-filter="date"]').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  applyFilters();
}}
function filterBySource(v) {{
  currentSource = v;
  document.querySelectorAll('[data-filter="source"]').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  applyFilters();
}}

function toggleSettings() {{
  document.getElementById('settingsOverlay').classList.toggle('open');
  document.getElementById('settingsPanel').classList.toggle('open');
  if (document.getElementById('settingsPanel').classList.contains('open')) renderSiteSettings();
}}
function renderSiteSettings() {{
  const selected = getSelectedIds();
  document.getElementById('sitesList').innerHTML = ALL_SITES.map(s => `
    <div class="site-item">
      <span class="dot" style="background:${{s.color}}"></span>
      <div class="info">
        <div class="name">${{s.name}}</div>
        <div class="type">${{s.type === 'rss' ? 'RSS' : 'スクレイピング'}}</div>
      </div>
      <input type="checkbox" class="check site-check" value="${{s.id}}" ${{selected.includes(s.id)?'checked':''}}>
    </div>
  `).join('');
}}
function applyAndReload() {{
  const checked = [...document.querySelectorAll('.site-check:checked')].map(cb => cb.value);
  if (!checked.length) {{ alert('少なくとも1つ選択してください'); return; }}
  saveSelectedIds(checked);
  toggleSettings();
  currentSource = 'all';
  render();
}}

render();
</script>
</body>
</html>"""


if __name__ == "__main__":
    build()
