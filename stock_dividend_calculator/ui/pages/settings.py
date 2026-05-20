"""系统设置页面"""
import streamlit as st
from database.engine import DatabaseEngine

db = DatabaseEngine()

st.title("⚙️ 系统设置")

# 税率配置
st.subheader("💰 股息红利税率配置")
st.caption("根据A股个人所得税规则，持股时间越长税率越低")

taxes = db.fetch_all("SELECT * FROM system_config WHERE key LIKE 'tax_%'")
tax_map = {t["key"]: float(t["value"]) for t in taxes}

col1, col2, col3 = st.columns(3)
with col1:
    new_month = st.number_input(
        "持股 ≤ 1个月 税率 (%)",
        min_value=0.0, max_value=50.0,
        value=tax_map.get("tax_holding_month", 20.0),
        step=0.5,
        help="持股不超过1个月（约30天）卖出的税率"
    )
with col2:
    new_year = st.number_input(
        "持股 1月-1年 税率 (%)",
        min_value=0.0, max_value=50.0,
        value=tax_map.get("tax_holding_year", 10.0),
        step=0.5,
        help="持股1个月以上、1年以下卖出的税率"
    )
with col3:
    new_long = st.number_input(
        "持股 > 1年 税率 (%)",
        min_value=0.0, max_value=50.0,
        value=tax_map.get("tax_holding_long", 0.0),
        step=0.5,
        help="持股超过1年暂免征收个人所得税"
    )

if st.button("保存税率设置", type="primary"):
    db.execute(
        "UPDATE system_config SET value = ?, updated_at = datetime('now','localtime') WHERE key = ?",
        (str(new_month), "tax_holding_month"),
    )
    db.execute(
        "UPDATE system_config SET value = ?, updated_at = datetime('now','localtime') WHERE key = ?",
        (str(new_year), "tax_holding_year"),
    )
    db.execute(
        "UPDATE system_config SET value = ?, updated_at = datetime('now','localtime') WHERE key = ?",
        (str(new_long), "tax_holding_long"),
    )
    db.commit()
    st.success("税率配置已保存！下次计算时将应用新税率")
    st.cache_data.clear()

st.divider()

# 数据源设置
st.subheader("📡 数据源设置")
data_source = db.fetch_one(
    "SELECT value FROM system_config WHERE key = 'dividend_data_source'"
)

current_source = data_source["value"] if data_source else "akshare"
source_options = {"akshare (推荐)": "akshare"}

selected_source = st.selectbox(
    "数据源",
    list(source_options.keys()),
    index=list(source_options.values()).index(current_source) if current_source in source_options.values() else 0,
    help="选择分红数据的获取来源",
)

if selected_source and source_options[selected_source] != current_source:
    if st.button("切换数据源"):
        db.execute(
            "UPDATE system_config SET value = ? WHERE key = ?",
            (source_options[selected_source], "dividend_data_source"),
        )
        db.commit()
        st.success(f"数据源已切换为 {selected_source}")
        st.rerun()

st.divider()

# 导出报告
st.subheader("📥 导出分红报告")
from services.import_export_service import ImportExportService
io_svc = ImportExportService()

col1, col2 = st.columns(2)
with col1:
    export_year = st.selectbox("导出年份", [str(y) for y in range(2026, 2019, -1)], key="export_year")
with col2:
    export_fmt = st.selectbox("导出格式", ["xlsx", "csv"], key="export_format")

if st.button("导出分红报告"):
    try:
        filepath = io_svc.export_dividend_report(int(export_year), fmt=export_fmt)
        with open(filepath, "rb") as f:
            st.download_button(
                "下载报告", f, file_name=filepath.split("/")[-1],
            )
        st.success(f"报告已生成: {filepath}")
    except Exception as e:
        st.error(f"导出失败: {e}")

st.divider()

# 关于
st.subheader("📌 关于")
st.markdown(f"""
- **股票分红计算助手** v1.0
- 数据源: akshare（东方财富、新浪财经等公开数据）
- 支持市场: A股（沪深北）
- 数据库: SQLite (本地存储)
- 数据库路径: `data/stock_dividend.db`
""")
