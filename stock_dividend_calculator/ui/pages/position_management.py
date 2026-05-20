"""持仓管理页面"""
import streamlit as st
import pandas as pd
import tempfile
from services.account_service import AccountService
from services.portfolio_service import PortfolioService
from services.import_export_service import ImportExportService

acc_svc = AccountService()
port_svc = PortfolioService()
io_svc = ImportExportService()

st.title("📦 持仓管理")

accounts = acc_svc.list_active()
if not accounts:
    st.warning("请先在「账户管理」中创建账户")
    st.stop()

account_options = {acc["account_name"]: acc["id"] for acc in accounts}
selected_account_name = st.sidebar.selectbox("选择账户", list(account_options.keys()))
selected_account_id = account_options[selected_account_name]

tab1, tab2, tab3 = st.tabs(["新增持仓", "持仓列表", "批量导入"])

with tab1:
    with st.form("add_position_form"):
        stock_code = st.text_input("证券代码 *", placeholder="如: 000001")
        stock_name = st.text_input("证券名称", placeholder="如: 平安银行")
        quantity = st.number_input("持仓数量（股）*", min_value=1, value=100, step=100)
        cost_price = st.number_input("买入成本（元/股）", min_value=0.0, value=0.0, step=0.01)
        buy_date = st.date_input("买入日期")
        notes = st.text_input("备注（可选）")
        submitted = st.form_submit_button("添加持仓")
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

with tab2:
    positions = port_svc.list_all(selected_account_id)
    if not positions:
        st.info("暂无持仓")
    else:
        # 构建数据表：原始数值用于对比变更
        from datetime import date as date_type
        pos_data = []
        for p in positions:
            buy_date = None
            if p["buy_date"]:
                try:
                    buy_date = date_type.fromisoformat(p["buy_date"][:10])
                except Exception:
                    buy_date = None
            pos_data.append({
                "选中": False,
                "ID": p["id"],
                "证券代码": p["stock_code"],
                "证券名称": p["stock_name"],
                "持仓数量": p["quantity"],
                "买入成本": p["cost_price"] if p["cost_price"] else 0.0,
                "_买入日期_str": p["buy_date"] or "",
                "买入日期": buy_date,
                "状态": "持有" if p["is_active"] else "已卖出",
                "备注": p["notes"] or "",
            })
        df = pd.DataFrame(pos_data)

        display_cols = [c for c in df.columns if c != "_买入日期_str"]
        edited_df = st.data_editor(
            df[display_cols],
            column_config={
                "选中": st.column_config.CheckboxColumn("选中", default=False),
                "ID": st.column_config.NumberColumn("ID", disabled=True),
                "证券代码": st.column_config.TextColumn("证券代码", disabled=True),
                "证券名称": st.column_config.TextColumn("证券名称", disabled=True),
                "持仓数量": st.column_config.NumberColumn("持仓数量", min_value=1, step=100),
                "买入成本": st.column_config.NumberColumn("买入成本", min_value=0.0, step=0.01, format="¥%.2f"),
                "买入日期": st.column_config.DateColumn("买入日期", format="YYYY-MM-DD"),
                "状态": st.column_config.TextColumn("状态", disabled=True),
                "备注": st.column_config.TextColumn("备注", disabled=True),
            },
            hide_index=True,
            use_container_width=True,
            key=f"pos_table_{selected_account_id}",
        )

        # 保存修改
        if st.button("💾 保存修改", type="primary"):
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

        # 批量操作
        selected_ids = edited_df[edited_df["选中"] == True]["ID"].tolist()
        st.caption(f"已选 {len(selected_ids)} 条持仓")

        batch_col1, batch_col2, batch_col3 = st.columns(3)
        with batch_col1:
            if st.button("🗑 批量删除选中", disabled=len(selected_ids) == 0):
                deleted = 0
                for pid in selected_ids:
                    if port_svc.delete(int(pid)):
                        deleted += 1
                st.success(f"已删除 {deleted} 条持仓")
                st.rerun()
        with batch_col2:
            if st.button("📤 批量标记卖出", disabled=len(selected_ids) == 0):
                from datetime import date
                today = date.today().strftime("%Y-%m-%d")
                sold = 0
                for pid in selected_ids:
                    if port_svc.mark_sold(int(pid), today):
                        sold += 1
                st.success(f"已标记 {sold} 条为卖出")
                st.rerun()
        with batch_col3:
            if st.button("🔄 取消所有选中"):
                st.rerun()

        # 导出
        st.divider()
        exp_col1, exp_col2 = st.columns(2)
        with exp_col1:
            fmt = st.selectbox("导出格式", ["csv", "xlsx"], key="export_fmt")
        with exp_col2:
            if st.button("导出持仓"):
                filepath = io_svc.export_positions(selected_account_id, fmt)
                with open(filepath, "rb") as f:
                    st.download_button("下载文件", f, file_name=filepath.split("/")[-1])
                st.success(f"已导出到 {filepath}")

with tab3:
    st.subheader("批量导入持仓")
    st.caption("支持 CSV 或 Excel 文件，必须包含「证券代码」「持仓数量」列")

    update_mode = st.toggle("更新模式：以证券代码匹配，更新已有持仓的数量和成本", value=False,
                            help="关闭=追加新持仓；开启=按证券代码找到已有持仓并更新")

    if "imported_file_key" not in st.session_state:
        st.session_state["imported_file_key"] = None

    uploaded = st.file_uploader("选择文件", type=["csv", "xlsx", "xls"],
                                key="position_file_uploader")
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
