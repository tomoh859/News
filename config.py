"""設定ファイル"""
import json
from pathlib import Path

# 出力先
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# サイト設定を sites.json から読み込む
SITES_FILE = BASE_DIR / "sites.json"

def load_sites() -> list[dict]:
    if SITES_FILE.exists():
        return json.loads(SITES_FILE.read_text("utf-8"))
    return []

SITES = load_sites()

# メール設定を email_settings.json から読み込む
EMAIL_FILE = BASE_DIR / "email_settings.json"

def load_email_settings() -> dict:
    if EMAIL_FILE.exists():
        return json.loads(EMAIL_FILE.read_text("utf-8"))
    return {}

def save_email_settings(settings: dict):
    EMAIL_FILE.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

# 取得する記事数（サイトごとに未指定の場合のデフォルト）
DEFAULT_MAX_ARTICLES = 30
