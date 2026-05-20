"""分红时间表页面"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from services.dividend_service import DividendCalculationService

div_svc = DividendCalculationService()

st.title("📅 分红时间表")

# 日期范围选择
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("开始日期", datetime.now().date())
with col2:
    end_date = st.date_input("结束日期", (datetime.now() + timedelta(days=90)).date())

# 获取近期分红事件
all_calcs = div_svc.get_upcoming_schedule(limit=200)

if all_calcs.empty:
    st.info("暂无分红计算数据，请先在「分红计算」页面执行计算")
else:
    # 筛选日期范围
    all_calcs["ex_dividend_date_parsed"] = pd.to_datetime(
        all_calcs["ex_dividend_date"], errors="coerce"
    )
    mask = (all_calcs["ex_dividend_date_parsed"] >= pd.Timestamp(start_date)) & \
           (all_calcs["ex_dividend_date_parsed"] <= pd.Timestamp(end_date))
    filtered = all_calcs[mask]

    if filtered.empty:
        st.info(f"{start_date} 至 {end_date} 期间暂无分红事件")
    else:
        st.subheader(f"📋 {start_date} 至 {end_date} 分红事件")

        cols = ["stock_code", "stock_name", "ex_dividend_date", "record_date",
                "cash_per_share", "hold_quantity", "gross_dividend", "net_dividend"]
        available = [c for c in cols if c in filtered.columns]
        display = filtered[available].copy()
        col_names = {
            "stock_code": "证券代码", "stock_name": "证券名称",
            "ex_dividend_date": "除权除息日", "record_date": "股权登记日",
            "cash_per_share": "每股派息", "hold_quantity": "持仓数量",
            "gross_dividend": "税前分红", "net_dividend": "税后分红",
        }
        display.rename(columns={k: v for k, v in col_names.items() if k in display.columns}, inplace=True)
        display = display.sort_values(by="除权除息日" if "除权除息日" in display.columns else display.columns[0])

        # 合计行
        total_gross = display["税前分红"].sum() if "税前分红" in display.columns else 0
        total_net = display["税后分红"].sum() if "税后分红" in display.columns else 0

        st.dataframe(display, use_container_width=True, hide_index=True)

        c1, c2 = st.columns(2)
        with c1:
            st.metric("期间税前分红合计", f"¥{total_gross:,.2f}")
        with c2:
            st.metric("期间税后分红合计", f"¥{total_net:,.2f}")

# 按月视图
st.divider()
st.subheader("📊 月度分红预测")
year = st.selectbox("选择年份", [str(y) for y in range(2026, 2019, -1)], key="schedule_year")
monthly = div_svc.get_monthly_summary(year=int(year))
if not monthly.empty and monthly["total_net"].sum() > 0:
    monthly["月份"] = monthly["month"].astype(int)
    chart_df = monthly.set_index("月份")[["total_net"]]
    chart_df.columns = ["税后分红"]
    st.bar_chart(chart_df, use_container_width=True)

    st.dataframe(monthly.drop(columns=["month"]).rename(columns={
        "total_gross": "税前分红", "total_net": "税后分红", "count": "笔数"
    }), use_container_width=True, hide_index=True)
else:
    st.info("暂无该年度分红数据")
