"""メール送信: 24時間以内の記事をHTMLファイル添付で配信"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timezone, timedelta

from config import load_email_settings

JST = timezone(timedelta(hours=9))


def filter_recent_articles(articles: list, hours: int = 24) -> list:
    """指定時間以内に公開された記事だけを返す"""
    now = datetime.now(JST)
    cutoff = now - timedelta(hours=hours)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    recent = []
    for a in articles:
        if not a.published:
            recent.append(a)
            continue
        if a.published >= cutoff_str:
            recent.append(a)

    return recent


def send_email(html_content: str, recent_articles: list = None) -> tuple[bool, str]:
    """HTMLファイルを添付し、本文に24時間以内の記事一覧を入れてメール送信"""
    settings = load_email_settings()

    sender = settings.get("sender", "")
    password = settings.get("password", "")
    recipients = settings.get("recipients", [])
    smtp_server = settings.get("smtp_server", "smtp.gmail.com")
    smtp_port = settings.get("smtp_port", 587)

    if not sender or not password:
        return (False, "送信元アドレスまたはアプリパスワードが未設定です")

    if not recipients:
        return (False, "送信先アドレスが未設定です")

    now = datetime.now(JST)
    date_str = now.strftime("%m/%d")
    filename = f"news_{now.strftime('%Y%m%d')}.html"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"📰 最新ニュース ({date_str})"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    # 本文HTML：24時間以内の記事をギャラリーカード形式で
    if recent_articles:
        cards = ""
        for a in recent_articles:
            img = f'<img src="{a.image_url}" width="100%" style="height:140px;object-fit:cover;display:block;" alt="">' if a.image_url else f'<div style="height:140px;background:{a.source_color};display:flex;align-items:center;justify-content:center;font-size:40px;font-weight:700;color:white;">{a.source_icon}</div>'
            date_tag = f'<div style="font-size:11px;color:#9b9a97;margin-top:4px;">{a.published}</div>' if a.published else ""
            summary_tag = f'<div style="font-size:12px;color:#787774;margin-top:4px;line-height:1.4;">{a.summary[:80]}...</div>' if a.summary else ""
            cards += f"""<div style="width:calc(50% - 8px);box-sizing:border-box;display:inline-block;vertical-align:top;margin-bottom:16px;">
  <a href="{a.url}" target="_blank" style="display:block;background:white;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.08);text-decoration:none;color:inherit;">
    {img}
    <div style="padding:10px 12px;">
      <div style="font-size:11px;font-weight:600;color:{a.source_color};margin-bottom:4px;">● {a.source}</div>
      <div style="font-size:13px;font-weight:600;color:#37352f;line-height:1.5;">{a.title}</div>
      {summary_tag}{date_tag}
    </div>
  </a>
</div>"""
        body_html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f7f6f3;font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans',sans-serif;">
<div style="max-width:680px;margin:0 auto;padding:24px;">
  <div style="background:linear-gradient(135deg,#2d3436,#636e72);color:white;padding:24px;border-radius:12px;margin-bottom:20px;">
    <div style="font-size:20px;font-weight:700;">📰 最新ニュース ({date_str})</div>
    <div style="font-size:13px;opacity:0.8;margin-top:6px;">24時間以内の新着記事 {len(recent_articles)}件</div>
  </div>
  <div style="font-size:0;">{cards}</div>
  <div style="text-align:center;margin-top:8px;padding:16px;background:white;border-radius:10px;font-size:13px;color:#787774;">
    📎 全記事は添付のHTMLファイルをブラウザで開いてご確認ください。
  </div>
</div>
</body></html>"""
    else:
        body_html = f"""<!DOCTYPE html><html><body style="font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans',sans-serif;padding:24px;">
  <p>本日({date_str})の最新ニュースをお届けします。</p>
  <p style="color:#787774;">📎 詳細は添付のHTMLファイルをブラウザで開いてご確認ください。</p>
</body></html>"""

    msg.attach(MIMEText(body_html, "html", "utf-8"))

    attachment = MIMEBase("text", "html")
    attachment.set_payload(html_content.encode("utf-8"))
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition",
        "attachment",
        filename=("utf-8", "", filename),
    )
    msg.attach(attachment)

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipients, msg.as_string())
        print(f"📧 メール送信完了! → {', '.join(recipients)}")
        print(f"   添付ファイル: {filename}")
        return (True, "")
    except Exception as e:
        error_msg = str(e)
        print(f"❌ メール送信失敗: {error_msg}")
        return (False, error_msg)
