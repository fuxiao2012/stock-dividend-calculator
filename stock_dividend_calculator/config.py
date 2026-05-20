"""全局配置"""
from pathlib import Path

ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "stock_dividend.db"
EXPORT_DIR = DATA_DIR / "exports"

DATA_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TAX_RATES = {
    "under_1_month": 0.20,
    "1month_to_1year": 0.10,
    "over_1_year": 0.00,
}

STREAMLIT_PAGE_CONFIG = {
    "page_title": "股票分红计算助手",
    "page_icon": "📊",
    "layout": "wide",
    "initial_sidebar_state": "expanded",
}

# 缓存 TTL (秒)
CACHE_TTL = 300
