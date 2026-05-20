"""数据同步页面"""
import streamlit as st
import pandas as pd
from datetime import datetime
from data_sync.sync_manager import SyncManager
from database.engine import DatabaseEngine

db = DatabaseEngine()

st.title("🔄 数据同步")

# 同步状态
sync_logs = db.fetch_all(
    "SELECT * FROM sync_log ORDER BY created_at DESC LIMIT 5"
)

st.subheader("📊 同步状态")

if sync_logs:
    last = sync_logs[0]
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("上次同步", last["created_at"][:10] if last["created_at"] else "-")
    with col2:
        st.metric("上次状态", last["status"])
    with col3:
        st.metric("获取记录", last["records_fetched"])
    with col4:
        st.metric("新增记录", last["records_inserted"])

    # 数据概况
    div_count = db.fetch_one("SELECT COUNT(*) as cnt FROM dividend_records")
    stock_count = db.fetch_one("SELECT COUNT(*) as cnt FROM stocks")
    c1, c2 = st.columns(2)
    with c1:
        st.metric("分红记录总数", div_count["cnt"] if div_count else 0)
    with c2:
        st.metric("已缓存股票数", stock_count["cnt"] if stock_count else 0)
else:
    st.info("暂无同步记录")

st.divider()

# 同步操作
col1, col2 = st.columns(2)

with col1:
    st.subheader("🔄 全量同步")
    st.caption("同步所有持仓股票的分红数据")
    if st.button("开始全量同步", type="primary", use_container_width=True):
        mgr = SyncManager()
        progress_bar = st.progress(0)
        status_text = st.empty()

        def update_progress(pct):
            progress_bar.progress(pct)
            status_text.text(f"同步进度: {pct*100:.0f}%")

        with st.spinner("正在同步..."):
            result = mgr.sync_all(progress_callback=update_progress)

        if result["status"] == "成功":
            st.success(f"全量同步完成！共 {result['succeeded']} 只股票")
        else:
            st.warning(f"同步完成，{result['succeeded']} 成功, {result['failed']} 失败")
            for r in result.get("results", []):
                if r["status"] == "失败":
                    st.error(f"{r['stock_code']}: {r.get('error', '未知错误')}")

with col2:
    st.subheader("🔍 单股同步")
    st.caption("同步指定证券代码的分红数据")
    stock_code = st.text_input("证券代码", placeholder="如: 000001")
    if st.button("同步单只股票", use_container_width=True):
        if not stock_code.strip():
            st.error("请输入证券代码")
        else:
            mgr = SyncManager()
            with st.spinner(f"正在同步 {stock_code}..."):
                result = mgr.sync_stock(stock_code.strip())
            if result["status"] == "成功":
                st.success(f"{stock_code} 同步成功！获取 {result['fetched']} 条，新增 {result['inserted']} 条")
            else:
                st.error(f"同步失败: {result.get('error', '未知错误')}")

# 同步日志
st.divider()
st.subheader("📋 同步日志")
all_logs = db.fetch_all("SELECT * FROM sync_log ORDER BY created_at DESC LIMIT 50")
if all_logs:
    log_data = [{
        "时间": log["created_at"], "类型": log["sync_type"],
        "股票": log["stock_code"] or "全部", "状态": log["status"],
        "获取": log["records_fetched"], "新增": log["records_inserted"],
    } for log in all_logs]
    st.dataframe(pd.DataFrame(log_data), use_container_width=True, hide_index=True)
