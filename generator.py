"""HTMLギャラリー生成: Notionギャラリービュー風のカードUI"""
from datetime import datetime, timezone, timedelta
from pathlib import Path

from jinja2 import Template

from config import OUTPUT_DIR

JST = timezone(timedelta(hours=9))

GALLERY_TEMPLATE = Template(r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&display=swap');

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: 'Noto Sans JP', -apple-system, BlinkMacSystemFont, sans-serif;
    background: #f7f6f3;
    color: #37352f;
    line-height: 1.6;
  }

  /* ── ヘッダー ── */
  .header {
    background: linear-gradient(135deg, #2d3436 0%, #636e72 100%);
    color: white;
    padding: 40px 32px 32px;
  }
  .header h1 {
    font-size: 28px;
    font-weight: 700;
    margin-bottom: 8px;
  }
  .header .date {
    font-size: 14px;
    opacity: 0.8;
  }
  .header .stats {
    display: flex;
    gap: 24px;
    margin-top: 16px;
    font-size: 13px;
  }
  .header .stats span {
    background: rgba(255,255,255,0.15);
    padding: 4px 12px;
    border-radius: 12px;
  }

  /* ── フィルター ── */
  .filters {
    padding: 16px 32px;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    background: white;
    border-bottom: 1px solid #e8e5e0;
    position: sticky;
    top: 0;
    z-index: 10;
  }
  .filter-btn {
    padding: 6px 16px;
    border-radius: 20px;
    border: 1px solid #e0ddd8;
    background: white;
    cursor: pointer;
    font-size: 13px;
    font-family: inherit;
    transition: all 0.2s;
  }
  .filter-btn:hover { background: #f0efed; }
  .filter-btn.active {
    background: #37352f;
    color: white;
    border-color: #37352f;
  }
  .filter-divider {
    width: 1px;
    height: 24px;
    background: #e0ddd8;
    margin: 0 4px;
  }

  /* ── ギャラリーグリッド ── */
  .gallery {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 20px;
    padding: 24px 32px 48px;
    max-width: 1400px;
    margin: 0 auto;
  }

  /* ── カード ── */
  .card {
    background: white;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    transition: all 0.25s ease;
    cursor: pointer;
    text-decoration: none;
    color: inherit;
    display: block;
  }
  .card:hover {
    box-shadow: 0 8px 24px rgba(0,0,0,0.12);
    transform: translateY(-3px);
  }

  /* サムネイル */
  .card-image {
    width: 100%;
    height: 200px;
    object-fit: cover;
    display: block;
    background: #e8e5e0;
  }
  .card-placeholder {
    width: 100%;
    height: 200px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 64px;
    font-weight: 700;
    color: white;
  }

  /* カード本文 */
  .card-body {
    padding: 16px;
  }
  .card-source {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    font-weight: 500;
    margin-bottom: 8px;
  }
  .card-source .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
  }
  .card-title {
    font-size: 15px;
    font-weight: 600;
    line-height: 1.5;
    margin-bottom: 8px;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .card-summary {
    font-size: 13px;
    color: #787774;
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    margin-bottom: 8px;
  }
  .card-meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 12px;
    color: #9b9a97;
  }
  .card-category {
    background: #f0efed;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
  }

  /* ── レスポンシブ ── */
  @media (max-width: 768px) {
    .header { padding: 24px 16px 20px; }
    .header h1 { font-size: 22px; }
    .filters { padding: 12px 16px; }
    .gallery {
      grid-template-columns: 1fr;
      padding: 16px;
      gap: 16px;
    }
  }

  /* ── 記事なし ── */
  .no-articles {
    grid-column: 1 / -1;
    text-align: center;
    padding: 48px;
    color: #9b9a97;
    font-size: 15px;
  }
</style>
</head>
<body>

<div class="header">
  <h1>{{ title }}</h1>
  <div class="date">{{ generated_at }}</div>
  <div class="stats">
    {% for source, count in source_counts.items() %}
    <span>{{ source }}: {{ count }}件</span>
    {% endfor %}
    <span>合計: {{ total }}件</span>
  </div>
</div>

<div class="filters" id="filters">
  <button class="filter-btn active" data-filter="date" data-value="all">すべて</button>
  <button class="filter-btn" data-filter="date" data-value="recent">24時間以内</button>
  <button class="filter-btn" data-filter="date" data-value="older">24時間以前</button>
  <div class="filter-divider"></div>
  <button class="filter-btn active" data-filter="source" data-value="all">全メディア</button>
  {% for source in sources %}
  <button class="filter-btn" data-filter="source" data-value="{{ source }}">{{ source }}</button>
  {% endfor %}
</div>

<div class="gallery" id="gallery">
  {% for article in articles %}
  <a class="card" href="{{ article.url }}" target="_blank"
     data-source="{{ article.source }}" data-published="{{ article.published }}" data-published-iso="{{ article.published_iso }}">
    {% if article.image_url %}
    <img class="card-image" src="{{ article.image_url }}"
         alt="" loading="lazy"
         onerror="this.outerHTML='<div class=\'card-placeholder\' style=\'background:{{ article.source_color }}\'>{{ article.source_icon }}</div>'">
    {% else %}
    <div class="card-placeholder" style="background: {{ article.source_color }}">
      {{ article.source_icon }}
    </div>
    {% endif %}
    <div class="card-body">
      <div class="card-source">
        <span class="dot" style="background: {{ article.source_color }}"></span>
        {{ article.source }}
      </div>
      <div class="card-title">{{ article.title }}</div>
      {% if article.summary %}
      <div class="card-summary">{{ article.summary }}</div>
      {% endif %}
      <div class="card-meta">
        <span>{{ article.published }}</span>
        {% if article.category %}
        <span class="card-category">{{ article.category }}</span>
        {% endif %}
      </div>
    </div>
  </a>
  {% endfor %}
</div>

<script>
const now = new Date();
const cutoff = new Date(now.getTime() - 24 * 60 * 60 * 1000);
let currentDate = 'all';
let currentSource = 'all';

function applyFilters() {
  document.querySelectorAll('.card').forEach(function(card) {
    var pubIso = card.getAttribute('data-published-iso') || '';
    var src = card.getAttribute('data-source') || '';

    var dateOk = true;
    if (currentDate !== 'all') {
      var pubDate = pubIso ? new Date(pubIso) : null;
      if (!pubDate || isNaN(pubDate.getTime())) {
        dateOk = (currentDate === 'recent');
      } else {
        var isRecent = pubDate.getTime() >= cutoff.getTime();
        dateOk = (currentDate === 'recent') ? isRecent : !isRecent;
      }
    }

    var sourceOk = (currentSource === 'all') || (src === currentSource);

    card.style.display = (dateOk && sourceOk) ? '' : 'none';
  });
}

document.getElementById('filters').addEventListener('click', function(e) {
  var btn = e.target;
  while (btn && !btn.classList.contains('filter-btn')) btn = btn.parentElement;
  if (!btn) return;
  var filterType = btn.getAttribute('data-filter');
  var value = btn.getAttribute('data-value');
  if (filterType === 'date') {
    currentDate = value;
    document.querySelectorAll('[data-filter="date"]').forEach(function(b) { b.classList.remove('active'); });
  } else if (filterType === 'source') {
    currentSource = value;
    document.querySelectorAll('[data-filter="source"]').forEach(function(b) { b.classList.remove('active'); });
  }
  btn.classList.add('active');
  applyFilters();
});
</script>

</body>
</html>
""")


def generate_gallery_html(articles: list, for_email: bool = False) -> str:
    """ギャラリーHTMLを生成"""
    now = datetime.now(JST)
    sources = list(dict.fromkeys(a.source for a in articles))
    source_counts = {}
    for a in articles:
        source_counts[a.source] = source_counts.get(a.source, 0) + 1

    return GALLERY_TEMPLATE.render(
        title="今朝のマーケティングニュース",
        generated_at=now.strftime("%Y年%m月%d日 %H:%M 更新"),
        articles=articles,
        sources=sources,
        source_counts=source_counts,
        total=len(articles),
    )


EMAIL_TEMPLATE = Template(r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body { margin:0; padding:0; background:#f7f6f3; font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans',sans-serif; }
  .card-grid { display:flex; flex-wrap:wrap; gap:16px; padding:20px 24px; }
  .card { width:calc(50% - 8px); box-sizing:border-box; background:white; border-radius:12px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.08); text-decoration:none; color:inherit; display:block; }
  .card img { width:100%; height:160px; object-fit:cover; display:block; }
  .card-placeholder { width:100%; height:160px; display:flex; align-items:center; justify-content:center; font-size:48px; font-weight:700; color:white; }
  .card-body { padding:12px; }
  .card-source { font-size:11px; font-weight:600; margin-bottom:6px; }
  .card-title { font-size:14px; font-weight:600; line-height:1.5; margin-bottom:6px; color:#37352f; }
  .card-summary { font-size:12px; color:#787774; line-height:1.4; margin-bottom:6px; }
  .card-date { font-size:11px; color:#9b9a97; }
  @media (max-width:600px) {
    .card { width:100%; }
  }
</style>
</head>
<body>

<table width="100%" cellpadding="0" cellspacing="0" style="background:#f7f6f3; padding:24px 0;">
<tr><td align="center">
<table width="680" cellpadding="0" cellspacing="0" style="background:white; border-radius:12px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1); max-width:100%;">

  <!-- ヘッダー -->
  <tr><td style="background:linear-gradient(135deg,#2d3436,#636e72); color:white; padding:28px 24px;">
    <div style="font-size:22px; font-weight:700;">{{ title }}</div>
    <div style="font-size:13px; opacity:0.8; margin-top:6px;">{{ generated_at }} ｜ {{ total }}件の新着記事</div>
  </td></tr>

  <!-- ギャラリーグリッド -->
  <tr><td>
    <div class="card-grid">
    {% for article in articles %}
      <a class="card" href="{{ article.url }}" target="_blank">
        {% if article.image_url %}
        <img src="{{ article.image_url }}" alt="">
        {% else %}
        <div class="card-placeholder" style="background:{{ article.source_color }};">{{ article.source_icon }}</div>
        {% endif %}
        <div class="card-body">
          <div class="card-source" style="color:{{ article.source_color }};">● {{ article.source }}</div>
          <div class="card-title">{{ article.title }}</div>
          {% if article.summary %}
          <div class="card-summary">{{ article.summary[:80] }}...</div>
          {% endif %}
          {% if article.published %}
          <div class="card-date">{{ article.published }}</div>
          {% endif %}
        </div>
      </a>
    {% endfor %}
    </div>
  </td></tr>

  <!-- フッター -->
  <tr><td style="padding:16px 24px; text-align:center; font-size:12px; color:#9b9a97; border-top:1px solid #f0efed;">
    最新ニュース | 自動配信
  </td></tr>

</table>
</td></tr>
</table>

</body>
</html>
""")


def generate_email_html(articles: list, html_path: str = "") -> str:
    """メール用HTMLを生成"""
    now = datetime.now(JST)
    return EMAIL_TEMPLATE.render(
        title="今朝のマーケティングニュース",
        generated_at=now.strftime("%Y年%m月%d日(%a)"),
        articles=articles,
        total=len(articles),
        html_path=html_path,
    )


def save_gallery(articles: list) -> Path:
    """ギャラリーHTMLをファイルに保存"""
    html = generate_gallery_html(articles)
    path = OUTPUT_DIR / "gallery.html"
    path.write_text(html, encoding="utf-8")
    print(f"📄 ギャラリー保存: {path}")
    return path
