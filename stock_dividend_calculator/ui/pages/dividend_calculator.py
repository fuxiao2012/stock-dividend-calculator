"""分红计算页面"""
import streamlit as st
import pandas as pd
from datetime import datetime
from services.account_service import AccountService
from services.dividend_service import DividendCalculationService

acc_svc = AccountService()
div_svc = DividendCalculationService()

st.title("💰 分红计算")

# 筛选条件
col1, col2, col3 = st.columns(3)
with col1:
    accounts = acc_svc.list_active()
    account_options = {"全部账户": None}
    account_options.update({acc["account_name"]: acc["id"] for acc in accounts})
    selected_account = st.selectbox("选择账户", list(account_options.keys()))
    account_id = account_options[selected_account]

with col2:
    current_year = datetime.now().year
    year = st.selectbox("选择年份", [str(y) for y in range(current_year, 2019, -1)], index=0)

with col3:
    st.write("")
    st.write("")
    calculate_btn = st.button("开始计算", type="primary", use_container_width=True)

if calculate_btn:
    with st.spinner("正在计算分红..."):
        div_svc.calculate_all(year=int(year), account_id=account_id)
    st.success("分红计算完成！")
    st.rerun()

# 显示计算结果
stats = div_svc.get_total_stats(year=int(year), account_id=account_id)
yearly = div_svc.get_yearly_summary(year=int(year), account_id=account_id)
calcs = div_svc.get_calculations(year=int(year), account_id=account_id)

st.divider()

# 统计卡片
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("分红股票数", stats["stock_count"])
with c2:
    st.metric("分红笔数", stats["record_count"])
with c3:
    st.metric(f"{year}年税前合计", f"¥{stats['total_gross']:,.2f}")
with c4:
    st.metric(f"{year}年税后合计", f"¥{stats['total_net']:,.2f}")

# 按股票汇总
if not yearly.empty:
    st.subheader(f"📋 {year}年按股票汇总")
    display = yearly.copy()
    display["证券代码"] = display["stock_code"]
    display["证券名称"] = display["stock_name"]
    display["分红次数"] = display["dividend_count"]
    display["税前合计"] = display["total_gross"].apply(lambda x: f"¥{x:,.2f}")
    display["税后合计"] = display["total_net"].apply(lambda x: f"¥{x:,.2f}")
    st.dataframe(display[["证券代码", "证券名称", "分红次数", "税前合计", "税后合计"]],
                 use_container_width=True, hide_index=True)

# 明细
if not calcs.empty and "stock_code" in calcs.columns:
    st.subheader(f"📋 {year}年分红明细")

    def _report_period(row):
        ad = row.get("div_announce_date", "")
        if not ad or pd.isna(ad):
            return ""
        try:
            m = int(str(ad)[5:7])
            y = int(str(ad)[:4])
            return f"{y-1}年报" if m <= 6 else f"{y}中报"
        except Exception:
            return ""

    date_col = "ex_dividend_date" if "ex_dividend_date" in calcs.columns else "record_date"
    cols = ["stock_code", "stock_name", date_col, "cash_per_share",
            "hold_quantity", "gross_dividend", "tax_rate", "tax_amount", "net_dividend", "progress"]
    available = [c for c in cols if c in calcs.columns]
    display = calcs[available].copy()
    col_names = {
        "stock_code": "证券代码", "stock_name": "证券名称",
        "ex_dividend_date": "除权除息日", "record_date": "除权除息日",
        "cash_per_share": "每股派息", "hold_quantity": "持仓数量",
        "gross_dividend": "税前分红", "tax_rate": "税率", "tax_amount": "税额",
        "net_dividend": "税后分红", "progress": "进度",
    }
    display.rename(columns=col_names, inplace=True)
    if "div_announce_date" in calcs.columns:
        display["报告期"] = calcs.apply(_report_period, axis=1)
    st.dataframe(display, use_container_width=True, hide_index=True)
