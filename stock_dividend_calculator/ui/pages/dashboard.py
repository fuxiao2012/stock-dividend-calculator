"""总览页面"""
import streamlit as st
import pandas as pd
from datetime import datetime
from config import CACHE_TTL
from services.account_service import AccountService
from services.portfolio_service import PortfolioService
from services.dividend_service import DividendCalculationService


@st.cache_data(ttl=CACHE_TTL)
def load_dashboard_data(year: str):
    div_svc = DividendCalculationService()
    port_svc = PortfolioService()
    acc_svc = AccountService()

    accounts = acc_svc.list_active()
    portfolio_summary = port_svc.get_summary()
    stats = div_svc.get_total_stats(year=int(year))
    monthly = div_svc.get_monthly_summary(year=int(year))

    # 按账户统计
    account_stats = []
    for acc in accounts:
        s = div_svc.get_total_stats(year=int(year), account_id=acc["id"])
        if s["total_gross"] > 0:
            account_stats.append({"账户": acc["account_name"], "税前分红": s["total_gross"], "税后分红": s["total_net"]})

    from database.engine import DatabaseEngine as _DB
    db = _DB()
    market_value = 0
    cost_value = 0
    positions = db.fetch_all("""
        SELECT p.quantity, p.cost_price, s.current_price
        FROM positions p
        LEFT JOIN stocks s ON p.stock_code = s.stock_code
        WHERE p.is_active = 1
    """)
    for p in positions:
        qty = p["quantity"]
        cost = p["cost_price"] or 0
        price = p["current_price"] or 0
        market_value += qty * price
        cost_value += qty * cost
    pnl = market_value - cost_value if market_value > 0 else 0

    return stats, portfolio_summary, monthly, account_stats, market_value, pnl


col1, col2 = st.columns([4, 1])
with col1:
    st.title("📊 数据总览")
with col2:
    year = str(st.selectbox("选择年份", [str(y) for y in range(2026, 2019, -1)], index=0))
stats, portfolio, monthly, account_stats, market_value, pnl = load_dashboard_data(year)

# KPI 卡片
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("持仓股票数", portfolio["total_positions"])
with col2:
    st.metric(f"{year}年税后分红", f"¥{stats['total_net']:,.2f}")
with col3:
    st.metric(f"{year}年税前分红", f"¥{stats['total_gross']:,.2f}")
with col4:
    st.metric("持仓总市值", f"¥{market_value:,.2f}")
with col5:
    st.metric("浮动盈亏", f"¥{pnl:,.2f}")

st.divider()

# 图表区
tab1, tab2, tab3 = st.tabs(["月度分布", "账户占比", "分红明细"])

with tab1:
    if not monthly.empty and monthly["total_net"].sum() > 0:
        monthly["月份"] = monthly["month"].astype(int)
        chart_df = monthly.set_index("月份")[["total_net"]]
        chart_df.columns = ["税后分红"]
        st.bar_chart(chart_df, use_container_width=True)
    else:
        st.info(f"暂无{year}年分红数据，请先同步数据并执行分红计算")

with tab2:
    if account_stats:
        import plotly.express as px
        df_acc = pd.DataFrame(account_stats)
        fig = px.pie(df_acc, values="税后分红", names="账户", title=f"{year}年各账户分红占比")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无账户分红数据")

with tab3:
    div_svc = DividendCalculationService()
    calcs = div_svc.get_calculations(year=int(year))
    if not calcs.empty and "stock_code" in calcs.columns:
        date_col = "ex_dividend_date" if "ex_dividend_date" in calcs.columns else "record_date"
        cols = ["stock_code", "stock_name", date_col, "hold_quantity",
                "cash_per_share", "gross_dividend", "net_dividend", "progress"]
        available = [c for c in cols if c in calcs.columns]
        display = calcs[available].copy()
        col_names = {"stock_code": "证券代码", "stock_name": "证券名称",
                     "ex_dividend_date": "除权除息日", "record_date": "除权除息日",
                     "hold_quantity": "持仓数量", "cash_per_share": "每股派息",
                     "gross_dividend": "税前分红", "net_dividend": "税后分红",
                     "progress": "进度"}
        display.rename(columns=col_names, inplace=True)
        if "div_announce_date" in calcs.columns:
            def _rp(row):
                ad = row.get("div_announce_date", "")
                if not ad or pd.isna(ad):
                    return ""
                try:
                    m = int(str(ad)[5:7])
                    y = int(str(ad)[:4])
                    return f"{y-1}年报" if m <= 6 else f"{y}中报"
                except Exception:
                    return ""
            display["报告期"] = calcs.apply(_rp, axis=1)
        st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        st.info(f"暂无{year}年分红明细")
