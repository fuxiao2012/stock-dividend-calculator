"""股票分红计算助手 — Streamlit 入口"""
import streamlit as st
import threading
from config import STREAMLIT_PAGE_CONFIG
from database.schema import init_database
from database.engine import DatabaseEngine

st.set_page_config(**STREAMLIT_PAGE_CONFIG)

# 全局初始化
if "db_initialized" not in st.session_state:
    init_database()
    DatabaseEngine.get_connection()
    st.session_state["db_initialized"] = True


def _background_sync_and_calculate():
    """后台线程：同步分红数据 + 市价 + 计算分红"""
    from data_sync.sync_manager import _set_sync_flag
    db = DatabaseEngine()
    positions = db.fetch_all("SELECT 1 FROM positions WHERE is_active = 1 LIMIT 1")
    if not positions:
        return
    _set_sync_flag(True)
    try:
        from data_sync.sync_manager import SyncManager
        SyncManager().sync_all()
    except Exception:
        pass
    try:
        from services.dividend_service import DividendCalculationService
        DividendCalculationService().calculate_all()
    except Exception:
        pass
    finally:
        _set_sync_flag(False)


# 启动时后台自动同步（每会话执行一次，不阻塞页面渲染）
if "auto_sync_done" not in st.session_state:
    st.session_state["auto_sync_done"] = False

if not st.session_state["auto_sync_done"]:
    st.session_state["auto_sync_done"] = True
    threading.Thread(target=_background_sync_and_calculate, daemon=True).start()

# 导航
pages = {
    "数据概览": [
        st.Page("ui/pages/dashboard.py", title="总览", icon="📊"),
    ],
    "账户与持仓": [
        st.Page("ui/pages/account_management.py", title="账户管理", icon="👤"),
        st.Page("ui/pages/position_management.py", title="持仓管理", icon="📦"),
    ],
    "分红分析": [
        st.Page("ui/pages/dividend_calculator.py", title="分红计算", icon="💰"),
        st.Page("ui/pages/dividend_schedule.py", title="分红时间表", icon="📅"),
    ],
    "数据管理": [
        st.Page("ui/pages/data_sync.py", title="数据同步", icon="🔄"),
        st.Page("ui/pages/settings.py", title="系统设置", icon="⚙️"),
    ],
}

pg = st.navigation(pages, position="sidebar")
pg.run()
