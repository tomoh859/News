#!/usr/bin/env python3
"""
マーケティングニュース朝キュレーション
- 登録サイトから記事を取得
- Notionギャラリー風HTMLを生成
- メール送信（オプション）

使い方:
  python main.py                     # 記事取得 & ギャラリー表示
  python main.py --mail              # メールも送信
  python main.py sites               # 登録サイト一覧
  python main.py add <URL> [名前]    # サイト追加（RSS自動検出）
  python main.py remove <名前or番号> # サイト削除
"""
import sys
import webbrowser

from scraper import fetch_all_articles
from generator import save_gallery, generate_email_html
from mailer import send_email, filter_recent_articles
from site_manager import list_sites, add_site, remove_site


def show_help():
    print("📰 マーケティングニュース キュレーター")
    print()
    print("使い方:")
    print("  python main.py                     記事取得 & ギャラリー表示")
    print("  python main.py --mail              メールも送信")
    print("  python main.py --no-open           ブラウザを開かない")
    print("  python main.py sites               登録サイト一覧")
    print("  python main.py add <URL> [名前]    サイト追加（RSS自動検出）")
    print("  python main.py remove <名前or番号> サイト削除")


def main():
    args = sys.argv[1:]

    # サイト管理コマンド
    if args and args[0] == "sites":
        list_sites()
        return

    if args and args[0] == "add":
        if len(args) < 2:
            print("❌ URLを指定してください: python main.py add <URL> [名前]")
            return
        name = args[2] if len(args) >= 3 else None
        add_site(args[1], name)
        return

    if args and args[0] == "remove":
        if len(args) < 2:
            print("❌ サイト名or番号を指定してください: python main.py remove <名前or番号>")
            return
        remove_site(args[1])
        return

    if args and args[0] in ("help", "--help", "-h"):
        show_help()
        return

    # 記事取得モード
    send_mail = "--mail" in args
    no_open = "--no-open" in args

    print("=" * 50)
    print("📰 マーケティングニュース キュレーター")
    print("=" * 50)
    print()

    # 1. 記事取得
    articles = fetch_all_articles()

    if not articles:
        print("\n⚠️  記事が取得できませんでした。ネットワーク接続を確認してください。")
        sys.exit(1)

    print(f"\n📊 合計 {len(articles)} 件の記事を取得\n")

    # 2. ギャラリーHTML生成 & 保存
    gallery_path = save_gallery(articles)

    # 3. ブラウザで開く
    if not no_open:
        print("🌐 ブラウザでギャラリーを開きます...")
        webbrowser.open(f"file://{gallery_path.resolve()}")

    # 4. メール送信（24時間以内の記事のみ）
    if send_mail:
        recent = filter_recent_articles(articles, hours=24)
        if recent:
            print(f"\n📧 24時間以内の記事 {len(recent)}件 をメール送信中...")
            email_html = generate_email_html(recent, str(gallery_path.resolve()))
            success, error_msg = send_email(email_html)
            if not success:
                print(f"  ❌ {error_msg}")
        else:
            print("\n📭 24時間以内の新着記事がないため、メール送信をスキップしました")
    else:
        print("\n💡 メール送信するには: python main.py --mail")

    print("\n✅ 完了!")


if __name__ == "__main__":
    main()
