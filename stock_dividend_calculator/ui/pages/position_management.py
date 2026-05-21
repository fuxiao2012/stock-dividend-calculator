"""持仓管理页面"""
import streamlit as st
import pandas as pd
import tempfile
from datetime import date as date_type, date
from services.account_service import AccountService
from services.portfolio_service import PortfolioService
from services.import_export_service import ImportExportService

acc_svc = AccountService()
port_svc = PortfolioService()
io_svc = ImportExportService()

# ── 金融风格自定义 CSS ──────────────────────────────────────────
st.markdown("""
<style>
    /* 全局字体 */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] {
        font-family: 'Inter', 'Microsoft YaHei', sans-serif;
    }

    /* 指标卡片样式 */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #1a2332 0%, #1e3a5f 100%);
        border-radius: 10px;
        padding: 16px 20px;
        color: #ffffff;
        box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    }
    [data-testid="stMetric"] label {
        color: #8899aa !important;
        font-size: 0.8rem;
        font-weight: 500;
        letter-spacing: 0.5px;
    }
    [data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: #ffffff !important;
        font-size: 1.6rem;
        font-weight: 700;
        font-family: 'Inter', 'Cascadia Code', monospace;
    }

    /* 按钮 */
    .stButton > button {
        border-radius: 6px;
        font-weight: 600;
        transition: all 0.2s;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }

    /* 容器卡片 */
    [data-testid="stForm"] {
        background: #f8f9fb;
        border: 1px solid #e1e4e8;
        border-radius: 10px;
        padding: 24px;
    }

    /* 表格优化 */
    [data-testid="stDataFrame"] {
        font-family: 'Inter', 'Microsoft YaHei', sans-serif;
        border-radius: 8px;
        overflow: hidden;
    }

    /* 侧边栏 */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a2332 0%, #16202e 100%);
    }
    [data-testid="stSidebar"] .stSelectbox label,
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] p {
        color: #ccd6dd !important;
    }

    /* 工具栏 */
    .toolbar-row {
        display: flex;
        align-items: center;
        background: #f0f2f5;
        border: 1px solid #dde1e6;
        border-radius: 8px;
        padding: 8px 16px;
        margin-bottom: 4px;
    }

    /* Tab 标签 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 6px 6px 0 0;
        font-weight: 600;
    }

    /* divider */
    hr {
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# ── 页面标题 ─────────────────────────────────────────────────────
col_t1, col_t2 = st.columns([4, 1])
with col_t1:
    st.title("📦 持仓管理")

# ── 账户检查 ─────────────────────────────────────────────────────
accounts = acc_svc.list_active()
if not accounts:
    st.warning("请先在「账户管理」中创建账户")
    st.stop()

account_options = {acc["account_name"]: acc["id"] for acc in accounts}
selected_account_name = st.sidebar.selectbox(
    "选择账户", list(account_options.keys()),
    key="pos_account_selector",
)
selected_account_id = account_options[selected_account_name]

# ── 侧边栏：当前账户摘要 ──────────────────────────────────────────
_positions_for_kpi = port_svc.list_all(selected_account_id)
from database.engine import DatabaseEngine as _DB
_price_lookup_for_kpi = {}
for code in {p["stock_code"] for p in _positions_for_kpi}:
    _row = _DB().fetch_one(
        "SELECT current_price FROM stocks WHERE stock_code=?",
        (code,),
    )
    if _row and _row["current_price"]:
        _price_lookup_for_kpi[code] = _row["current_price"]

total_market_value = sum(
    p["quantity"] * (_price_lookup_for_kpi.get(p["stock_code"], 0) or 0)
    for p in _positions_for_kpi if p["is_active"]
)
total_cost_value = sum(
    p["quantity"] * (p["cost_price"] or 0)
    for p in _positions_for_kpi if p["is_active"]
)
total_pnl = total_market_value - total_cost_value if total_market_value > 0 else 0

with st.sidebar:
    st.divider()
    summary = port_svc.get_summary(selected_account_id)
    unique_stocks = len({
        p["stock_code"] for p in _positions_for_kpi
        if p["is_active"]
    })
    st.caption(f"📊 活跃持仓 **{summary['total_positions']}** 笔 · **{unique_stocks}** 只")
    st.caption(f"💰 持仓市值 **¥{total_market_value:,.2f}**")

# ── 顶部摘要 KPI ──────────────────────────────────────────────────
kpi1, kpi2, kpi3, kpi4 = st.columns(4)
with kpi1:
    st.metric("持仓笔数", summary["total_positions"])
with kpi2:
    st.metric("持仓股票", unique_stocks)
with kpi3:
    st.metric("持仓总市值", f"¥{total_market_value:,.2f}")
with kpi4:
    pnl_pct = f"{total_pnl/total_cost_value*100:.1f}%" if total_cost_value > 0 else ""
    st.metric("浮动盈亏", f"¥{total_pnl:,.2f}", delta=pnl_pct if pnl_pct else None,
              delta_color="normal")

st.divider()

# ── 三个 Tab ──────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📝 新增持仓", "📋 持仓列表", "📤 批量导入"])

# ═══════════════════════════════════════════════════════════════════
# Tab 1: 新增持仓
# ═══════════════════════════════════════════════════════════════════
with tab1:
    with st.container(border=True):
        st.caption("填写以下信息添加新持仓")
        with st.form("add_position_form"):
            row1_col1, row1_col2 = st.columns(2)
            with row1_col1:
                stock_code = st.text_input("证券代码 *", placeholder="如: 000001", key="add_code")
            with row1_col2:
                stock_name = st.text_input("证券名称", placeholder="如: 平安银行", key="add_name")

            row2_col1, row2_col2, row2_col3 = st.columns(3)
            with row2_col1:
                quantity = st.number_input("持仓数量（股）*", min_value=1, value=100, step=100, key="add_qty")
            with row2_col2:
                cost_price = st.number_input("买入成本（元/股）", min_value=0.0, value=0.0, step=0.01, format="%.2f", key="add_cost")
            with row2_col3:
                buy_date = st.date_input("买入日期", key="add_date")

            notes = st.text_input("备注（可选）", placeholder="可填写买入理由等", key="add_notes")

            submitted = st.form_submit_button("✅ 添加持仓", type="primary", use_container_width=True)
            if submitted:
                if not stock_code.strip():
                    st.error("请输入证券代码")
                else:
                    try:
                        port_svc.add_position(
                            selected_account_id, stock_code.strip(), quantity,
                            stock_name.strip(), cost_price if cost_price > 0 else None,
                            buy_date.strftime("%Y-%m-%d") if buy_date else "", notes,
                        )
                        st.success(f"添加 {stock_code} 成功")
                        st.rerun()
                    except Exception as e:
                        st.error(f"添加失败: {e}")

# ═══════════════════════════════════════════════════════════════════
# Tab 2: 持仓列表
# ═══════════════════════════════════════════════════════════════════
with tab2:
    positions = port_svc.list_all(selected_account_id)
    if not positions:
        st.info("暂无持仓，请先添加或导入")
    else:
        # 查询现价
        from database.engine import DatabaseEngine as _DB
        price_lookup = {}
        for code in {p["stock_code"] for p in positions}:
            row_data = _DB().fetch_one(
                "SELECT current_price FROM stocks WHERE stock_code=?",
                (code,),
            )
            if row_data and row_data["current_price"]:
                price_lookup[code] = row_data["current_price"]

        # 构建数据表
        pos_data = []
        for p in positions:
            buy_date_val = None
            if p["buy_date"]:
                try:
                    buy_date_val = date_type.fromisoformat(p["buy_date"][:10])
                except Exception:
                    buy_date_val = None
            code = p["stock_code"]
            qty = p["quantity"]
            cost_each = p["cost_price"] if p["cost_price"] else 0.0
            price = price_lookup.get(code, 0) or 0
            market_value = round(qty * price, 2) if price > 0 else 0
            cost_total = round(qty * cost_each, 2)
            pnl = round(market_value - cost_total, 2)
            pos_data.append({
                "选中": False,
                "ID": p["id"],
                "证券代码": code,
                "证券名称": p["stock_name"],
                "持仓数量": qty,
                "买入成本": cost_each,
                "现价": price,
                "市值": market_value,
                "盈亏": pnl,
                "_买入日期_str": p["buy_date"] or "",
                "买入日期": buy_date_val,
                "状态": "持有" if p["is_active"] else "已卖出",
                "备注": p["notes"] or "",
            })
        df = pd.DataFrame(pos_data)
        display_cols = [c for c in df.columns if c != "_买入日期_str"]

        editor_key = f"pos_table_{selected_account_id}"
        toolbar = st.empty()

        edited_df = st.data_editor(
            df[display_cols],
            column_config={
                "选中": st.column_config.CheckboxColumn("", default=False, help="选中以进行批量操作"),
                "ID": st.column_config.NumberColumn("ID", disabled=True),
                "证券代码": st.column_config.TextColumn("证券代码", disabled=True),
                "证券名称": st.column_config.TextColumn("证券名称", disabled=True),
                "持仓数量": st.column_config.NumberColumn("持仓数量", min_value=1, step=100, format="%d"),
                "买入成本": st.column_config.NumberColumn("买入成本", min_value=0.0, step=0.01, format="¥%.2f"),
                "买入日期": st.column_config.DateColumn("买入日期", format="YYYY-MM-DD"),
                "现价": st.column_config.NumberColumn("现价", disabled=True, format="¥%.2f"),
                "市值": st.column_config.NumberColumn("市值", disabled=True, format="¥%.2f"),
                "盈亏": st.column_config.NumberColumn("盈亏", disabled=True, format="¥%.2f"),
                "状态": st.column_config.TextColumn("状态", disabled=True),
                "备注": st.column_config.TextColumn("备注", disabled=True),
            },
            hide_index=True,
            use_container_width=True,
            key=editor_key,
        )

        selected_ids = edited_df[edited_df["选中"] == True]["ID"].tolist()

        # 工具栏 —— 渲染在表格上方
        with toolbar.container():
            t_left, t_right = st.columns([1, 1])
            with t_left:
                btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])
                with btn_col1:
                    save_btn = st.button("💾 保存修改", type="primary", use_container_width=True)
                with btn_col2:
                    delete_btn = st.button("🗑 删除选中", use_container_width=True)
                with btn_col3:
                    sell_btn = st.button("📤 标记卖出", use_container_width=True)
            with t_right:
                st.markdown(
                    f"<div style='text-align:right;padding-top:12px;color:#8899aa;font-size:0.9rem'>"
                    f"已选 <b style='color:#ff6b6b'>{len(selected_ids)}</b> 条持仓</div>",
                    unsafe_allow_html=True,
                )

        # 保存修改
        if save_btn:
            changed = 0
            for i, row in edited_df.iterrows():
                pid = int(row["ID"])
                orig = df[df["ID"] == pid].iloc[0]
                new_qty = int(row["持仓数量"])
                new_cost = float(row["买入成本"])
                new_date_val = row["买入日期"]
                if pd.isna(new_date_val) or new_date_val is None:
                    new_date = ""
                elif hasattr(new_date_val, "strftime"):
                    new_date = new_date_val.strftime("%Y-%m-%d")
                else:
                    new_date = str(new_date_val)[:10]
                orig_date = orig["_买入日期_str"]
                if new_qty != int(orig["持仓数量"]) or abs(new_cost - float(orig["买入成本"])) > 0.001 or new_date != orig_date:
                    port_svc.update_position(pid, quantity=new_qty, cost_price=new_cost, buy_date=new_date)
                    changed += 1
            if changed:
                st.success(f"已保存 {changed} 条修改")
            else:
                st.info("无变更")
            st.rerun()

        # 批量删除
        if delete_btn and selected_ids:
            deleted = 0
            for pid in selected_ids:
                if port_svc.delete(int(pid)):
                    deleted += 1
            if deleted:
                st.success(f"已删除 {deleted} 条持仓")
            else:
                st.error("删除失败")
            st.rerun()
        elif delete_btn:
            st.warning("请先选中要删除的持仓")

        # 批量标记卖出
        if sell_btn and selected_ids:
            today = date.today().strftime("%Y-%m-%d")
            sold = 0
            for pid in selected_ids:
                if port_svc.mark_sold(int(pid), today):
                    sold += 1
            if sold:
                st.success(f"已标记 {sold} 条为卖出")
            else:
                st.error("标记失败")
            st.rerun()
        elif sell_btn:
            st.warning("请先选中要标记的持仓")

        # 导出
        st.divider()
        exp_col1, exp_col2, exp_col3 = st.columns([1, 1, 5])
        with exp_col1:
            fmt = st.selectbox("导出格式", ["csv", "xlsx"], key="export_fmt")
        with exp_col2:
            if st.button("📥 导出持仓", use_container_width=True):
                filepath = io_svc.export_positions(selected_account_id, fmt)
                with open(filepath, "rb") as f:
                    st.download_button(
                        "下载文件", f, file_name=filepath.split("/")[-1],
                        key=f"dl_{selected_account_id}",
                    )
                st.success(f"已导出到 {filepath}")

# ═══════════════════════════════════════════════════════════════════
# Tab 3: 批量导入
# ═══════════════════════════════════════════════════════════════════
with tab3:
    with st.container(border=True):
        st.caption("支持 CSV 或 Excel 文件，必须包含「证券代码」「持仓数量」列")
        st.caption("列名兼容：`股票代码`→`证券代码`、`持有数量`→`持仓数量`、`股票名称`→`证券名称`")

        update_mode = st.toggle(
            "更新模式：以证券代码匹配，更新已有持仓的数量和成本",
            value=False,
            help="关闭=追加新持仓；开启=按证券代码找到已有持仓并更新",
        )

        if "imported_file_key" not in st.session_state:
            st.session_state["imported_file_key"] = None

        uploaded = st.file_uploader(
            "选择文件", type=["csv", "xlsx", "xls"],
            key="position_file_uploader",
        )

        if uploaded:
            file_key = f"{uploaded.name}_{uploaded.size}_{update_mode}"
            if st.session_state["imported_file_key"] == file_key:
                st.info("该文件已导入，请上传新文件")
            else:
                with tempfile.NamedTemporaryFile(delete=False, suffix=uploaded.name) as tmp:
                    tmp.write(uploaded.getbuffer())
                    tmp_path = tmp.name
                try:
                    result = io_svc.import_positions(tmp_path, selected_account_id, update_mode=update_mode)
                    if result["errors"]:
                        st.warning(f"导入完成，{result.get('message', '')}")
                        for err in result["errors"]:
                            st.error(err)
                    else:
                        st.success(f"导入成功！{result.get('message', '')}")
                        st.session_state["imported_file_key"] = file_key
                except Exception as e:
                    st.error(f"导入失败: {e}")
