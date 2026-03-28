"""メール送信: Gmail SMTP経由で24時間以内の記事のみ配信"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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
            # 日付がない記事は含める（取れたて＝新しい可能性が高い）
            recent.append(a)
            continue
        if a.published >= cutoff_str:
            recent.append(a)

    return recent


def send_email(html_body: str) -> bool:
    """HTMLメールを送信"""
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
    subject = f"📰 今朝のマーケティングニュース ({now.strftime('%m/%d')})"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    plain = "HTMLメールに対応したメーラーでご覧ください。"
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipients, msg.as_string())
        print(f"📧 メール送信完了! → {', '.join(recipients)}")
        return (True, "")
    except Exception as e:
        error_msg = str(e)
        print(f"❌ メール送信失敗: {error_msg}")
        return (False, error_msg)
