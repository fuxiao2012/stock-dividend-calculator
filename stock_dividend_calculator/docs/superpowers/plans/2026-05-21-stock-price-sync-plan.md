# 股票/ETF 市价同步 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在数据同步中集成 A 股和 ETF 的最新市价拉取，并在持仓管理和总览页展示市值和盈亏。

**Architecture:** 利用 `ak.stock_zh_a_spot_em()` 和 `ak.fund_etf_spot_em()` 全市场 API（均无参数），2 次调用覆盖全部持仓。价格存入 `stocks.current_price` 字段。UI 层从 stocks 表读取价格，计算市值 = 数量 × 现价。

**Tech Stack:** Python 3, Streamlit, SQLite, akshare, pandas

**Spec:** `docs/superpowers/specs/2026-05-21-stock-price-sync-design.md`

---

### Task 1: stocks 表添加价格字段

**Files:**
- Modify: `stock_dividend_calculator/database/schema.py:156-162`

在 `init_database()` 的迁移区添加两个 ALTER TABLE。

- [ ] **Step 1: 添加迁移代码**

在 `schema.py` 的 `init_database()` 函数末尾，commit 之前添加：

```python
    # 价格字段
    try:
        conn.execute("ALTER TABLE stocks ADD COLUMN current_price REAL")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE stocks ADD COLUMN price_updated_at TEXT")
    except Exception:
        pass
```

位置：在 `ALTER TABLE sync_log ADD COLUMN duration_seconds` 的 try/except 块之后，`conn.commit()` 之前。

- [ ] **Step 2: 验证迁移**

```bash
cd "d:/工作/CBF开发/Stock/stock_dividend_calculator"
C:/Users/85433/AppData/Local/Programs/Python/Python314/python.exe -c "
from database.schema import init_database
init_database()
from database.engine import DatabaseEngine
db = DatabaseEngine()
cols = db.fetch_all(\"PRAGMA table_info(stocks)\")
for c in cols:
    print(c['name'], c['type'])
" 2>&1
```

Expected: 输出包含 `current_price REAL` 和 `price_updated_at TEXT`。

- [ ] **Step 3: 提交**

```bash
cd "d:/工作/CBF开发/Stock"
git add stock_dividend_calculator/database/schema.py
git commit -m "feat: stocks 表新增 current_price / price_updated_at 字段"
```

---

### Task 2: Provider 新增价格获取方法

**Files:**
- Modify: `stock_dividend_calculator/data_sync/akshare_provider.py`

在 `AkshareDividendProvider` 类中新增两个方法。放在 `get_all_etf_dividends` 方法之后，`get_etf_dividend` 方法之前。

- [ ] **Step 1: 新增 `get_all_stock_prices()`**

```python
    @api_retry(max_retries=2, delay=2.0)
    def get_all_stock_prices(self) -> pd.DataFrame:
        """获取全市场 A 股实时行情（东方财富）"""
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            if df.empty:
                return df
            cols = df.columns.tolist()
            result = pd.DataFrame()
            result["stock_code"] = df[cols[0]].astype(str).str.strip()
            result["stock_name"] = df[cols[1]].astype(str)
            result["current_price"] = pd.to_numeric(df[cols[2]], errors="coerce")
            result["change_pct"] = pd.to_numeric(df[cols[5]], errors="coerce")
            return result
        except Exception as e:
            raise DataSyncError(f"获取A股市价失败: {e}") from e
```

column index 说明（基于 `stock_zh_a_spot_em` 实际返回）：
- 0: 代码
- 1: 名称
- 2: 最新价
- 5: 涨跌幅

- [ ] **Step 2: 新增 `get_all_etf_prices()`**

```python
    @api_retry(max_retries=2, delay=2.0)
    def get_all_etf_prices(self) -> pd.DataFrame:
        """获取全市场 ETF 实时行情（东方财富）"""
        try:
            import akshare as ak
            df = ak.fund_etf_spot_em()
            if df.empty:
                return df
            cols = df.columns.tolist()
            result = pd.DataFrame()
            result["stock_code"] = df[cols[0]].astype(str).str.strip()
            result["stock_name"] = df[cols[1]].astype(str)
            result["current_price"] = pd.to_numeric(df[cols[2]], errors="coerce")
            result["change_pct"] = pd.to_numeric(df[cols[5]], errors="coerce")
            return result
        except Exception as e:
            raise DataSyncError(f"获取ETF市价失败: {e}") from e
```

- [ ] **Step 3: 验证方法可调用**

```bash
cd "d:/工作/CBF开发/Stock/stock_dividend_calculator"
C:/Users/85433/AppData/Local/Programs/Python/Python314/python.exe -c "
from data_sync.akshare_provider import AkshareDividendProvider
p = AkshareDividendProvider()
df1 = p.get_all_stock_prices()
print('Stocks:', len(df1), 'rows, columns:', list(df1.columns))
df2 = p.get_all_etf_prices()
print('ETFs:', len(df2), 'rows, columns:', list(df2.columns))
" 2>&1
```

Expected: stocks > 5000 rows, ETFs > 500 rows, both have columns `stock_code`, `stock_name`, `current_price`, `change_pct`。

- [ ] **Step 4: 提交**

```bash
cd "d:/工作/CBF开发/Stock"
git add stock_dividend_calculator/data_sync/akshare_provider.py
git commit -m "feat: provider 新增 get_all_stock_prices / get_all_etf_prices"
```

---

### Task 3: SyncManager 新增批量价格同步方法

**Files:**
- Modify: `stock_dividend_calculator/data_sync/sync_manager.py`

在 `_sync_etf_batch` 方法后，`_insert_records` 方法前，新增两个方法。

- [ ] **Step 1: 新增 `_sync_stock_prices(codes)`**

```python
    def _sync_stock_prices(self, codes: list) -> int:
        """批量同步 A 股市价，返回更新行数"""
        try:
            df = self.provider.get_all_stock_prices()
            if df.empty:
                return 0
            conn = DatabaseEngine.get_connection()
            updated = 0
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for _, row in df.iterrows():
                code = row["stock_code"]
                if code not in codes:
                    continue
                price = row["current_price"]
                if pd.isna(price):
                    continue
                conn.execute(
                    "UPDATE stocks SET current_price=?, price_updated_at=? WHERE stock_code=?",
                    (float(price), now, code),
                )
                updated += 1
            conn.commit()
            return updated
        except Exception:
            return 0
```

- [ ] **Step 2: 新增 `_sync_etf_prices(codes)`**

```python
    def _sync_etf_prices(self, codes: list) -> int:
        """批量同步 ETF 市价，返回更新行数"""
        try:
            df = self.provider.get_all_etf_prices()
            if df.empty:
                return 0
            conn = DatabaseEngine.get_connection()
            updated = 0
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for _, row in df.iterrows():
                code = row["stock_code"]
                if code not in codes:
                    continue
                price = row["current_price"]
                if pd.isna(price):
                    continue
                conn.execute(
                    "UPDATE stocks SET current_price=?, price_updated_at=? WHERE stock_code=?",
                    (float(price), now, code),
                )
                updated += 1
            conn.commit()
            return updated
        except Exception:
            return 0
```

- [ ] **Step 3: 提交**

```bash
cd "d:/工作/CBF开发/Stock"
git add stock_dividend_calculator/data_sync/sync_manager.py
git commit -m "feat: SyncManager 新增 _sync_stock_prices / _sync_etf_prices"
```

---

### Task 4: 修改 sync_all() 集成价格同步

**Files:**
- Modify: `stock_dividend_calculator/data_sync/sync_manager.py:63-112`

在 `sync_all()` 中，A 股分红同步完成后、统计结果前，插入价格同步调用。

- [ ] **Step 1: 修改 sync_all()**

在现有代码：
```python
        # A 股逐只同步
        for i, code in enumerate(stock_codes):
            r = self.sync_stock(code)
            results.append(r)
            if progress_callback:
                progress_callback((len(etf_codes) + i + 1) / total)

        # 统计全部结果
```

改为（在 A 股循环后、统计前插入价格同步）：

```python
        # A 股逐只同步
        for i, code in enumerate(stock_codes):
            r = self.sync_stock(code)
            results.append(r)
            if progress_callback:
                progress_callback((len(etf_codes) + i + 1) / total)

        # 批量同步市价
        price_updated = 0
        if stock_codes:
            price_updated += self._sync_stock_prices(stock_codes)
        if etf_codes:
            price_updated += self._sync_etf_prices(etf_codes)

        # 统计全部结果
```

- [ ] **Step 2: 修改 sync_all() 日志 — 记录价格更新数**

在 `_log_sync` 调用中，result dict 增加价格信息：

```python
        self._log_sync("全量", None, {
            "status": "成功" if failed == 0 else "失败",
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
        }, started_at)
```

改为：

```python
        price_msg = f"，价格已更新 {price_updated} 只" if price_updated else ""
        self._log_sync("全量", None, {
            "status": "成功" if failed == 0 else "失败",
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "error": price_msg,
        }, started_at)
```

- [ ] **Step 3: 提交**

```bash
cd "d:/工作/CBF开发/Stock"
git add stock_dividend_calculator/data_sync/sync_manager.py
git commit -m "feat: sync_all 集成市价同步（A股+ETF）"
```

---

### Task 5: 单股同步添加价格刷新

**Files:**
- Modify: `stock_dividend_calculator/data_sync/sync_manager.py:24-57`

修改 `sync_stock()`，在分红数据同步成功后追加该股的价格更新。

- [ ] **Step 1: 修改 sync_stock()**

在 `sync_stock()` 的 try 块末尾（`result["name_updated"] = ...` 之后），添加价格刷新：

```python
            # 刷新该股最新价格
            try:
                if self._is_etf(stock_code):
                    df = self.provider.get_all_etf_prices()
                else:
                    df = self.provider.get_all_stock_prices()
                if not df.empty:
                    row = df[df["stock_code"] == stock_code]
                    if not row.empty:
                        price = float(row.iloc[0]["current_price"])
                        if not pd.isna(price):
                            conn = DatabaseEngine.get_connection()
                            conn.execute(
                                "UPDATE stocks SET current_price=?, price_updated_at=? WHERE stock_code=?",
                                (price, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), stock_code),
                            )
                            conn.commit()
            except Exception:
                pass
```

位置：在 `result["name_updated"] = self._update_stock_name(stock_code)` 之后，`except DataSyncError` 之前。

- [ ] **Step 2: 提交**

```bash
cd "d:/工作/CBF开发/Stock"
git add stock_dividend_calculator/data_sync/sync_manager.py
git commit -m "feat: 单股同步追加价格刷新"
```

---

### Task 6: 持仓管理页 — 展示市价、市值、盈亏

**Files:**
- Modify: `stock_dividend_calculator/ui/pages/position_management.py`

- [ ] **Step 1: 构建持仓数据时加入价格信息**

在 Tab 2 构建 `pos_data` 列表时，从 stocks 表查询价格。在 `positions = port_svc.list_all(selected_account_id)` 之前添加：

```python
        from database.engine import DatabaseEngine as _DB
        price_lookup = {}
        for code in {p["stock_code"] for p in positions}:
            row_data = _DB().fetch_one(
                "SELECT current_price FROM stocks WHERE stock_code=?",
                (code,),
            )
            if row_data and row_data["current_price"]:
                price_lookup[code] = row_data["current_price"]
```

在构建 `pos_data` dict 时增加价格相关字段：

```python
            code = p["stock_code"]
            qty = p["quantity"]
            cost_each = p["cost_price"] if p["cost_price"] else 0.0
            price = price_lookup.get(code, 0) or 0
            market_value = qty * price
            cost_total = qty * cost_each
            pnl = market_value - cost_total if market_value > 0 else None
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
```

- [ ] **Step 2: 更新 column_config**

在 `st.data_editor` 的 `column_config` 中新增三列：

```python
                "现价": st.column_config.NumberColumn("现价", disabled=True, format="¥%.2f"),
                "市值": st.column_config.NumberColumn("市值", disabled=True, format="¥%.2f"),
                "盈亏": st.column_config.NumberColumn("盈亏", disabled=True, format="¥%.2f"),
```

- [ ] **Step 3: 更新摘要 KPI — 用市值替代总成本**

在顶部 KPI 栏（`kpi1, kpi2, kpi3`），将 `持仓总成本` 改为 `持仓总市值`：

```python
    total_market_value = sum(
        p["quantity"] * (price_lookup.get(p["stock_code"], 0) or 0)
        for p in positions if p["is_active"]
    )
    total_cost_value = sum(
        p["quantity"] * (p["cost_price"] or 0)
        for p in positions if p["is_active"]
    )
    total_pnl = total_market_value - total_cost_value if total_market_value > 0 else 0

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
with kpi1:
    st.metric("持仓笔数", summary["total_positions"])
with kpi2:
    st.metric("持仓股票", unique_stocks)
with kpi3:
    st.metric("持仓总市值", f"¥{total_market_value:,.2f}")
with kpi4:
    pnl_color = "inverse" if total_pnl >= 0 else "normal"
    st.metric("浮动盈亏", f"¥{total_pnl:,.2f}", delta=f"{total_pnl/total_cost_value*100:.1f}%" if total_cost_value > 0 else None, delta_color=pnl_color)
```

- [ ] **Step 4: 更新侧边栏摘要**

将侧边栏的「持仓成本」改为「持仓市值」：

```python
    st.caption(f"💰 持仓市值 **¥{total_market_value:,.2f}**")
```

- [ ] **Step 5: 提交**

```bash
cd "d:/工作/CBF开发/Stock"
git add stock_dividend_calculator/ui/pages/position_management.py
git commit -m "feat: 持仓管理页展示现价/市值/浮动盈亏"
```

---

### Task 7: 总览页 — 展示持仓总市值

**Files:**
- Modify: `stock_dividend_calculator/ui/pages/dashboard.py`

- [ ] **Step 1: PortfolioService 新增获取市值的方法**

如果 `get_summary` 未包含市值，在 `PortfolioService` 或直接在 dashboard 中计算：

在 `load_dashboard_data` 返回前添加：

```python
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
```

在 `return` 中增加 `market_value, pnl`。

- [ ] **Step 2: 在 KPI 卡片中展示**

将现有 4 列 KPI 改为：

```python
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
```

（需要更新 `load_dashboard_data` 返回值和调用处接收 market_value, pnl）

- [ ] **Step 3: 提交**

```bash
cd "d:/工作/CBF开发/Stock"
git add stock_dividend_calculator/ui/pages/dashboard.py
git commit -m "feat: 总览页展示持仓总市值和浮动盈亏"
```

---

### Task 8: 端到端测试

- [ ] **Step 1: 重启 Streamlit**

```bash
cd "d:/工作/CBF开发/Stock"
powershell -Command "Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force"
sleep 3
rm -f stock_dividend_calculator/data/stock_dividend.db-shm stock_dividend_calculator/data/stock_dividend.db-wal
C:/Users/85433/AppData/Local/Programs/Python/Python314/python.exe -m streamlit run stock_dividend_calculator/app.py --server.port 8502 --server.headless true &
```

- [ ] **Step 2: 验证流程**

1. 打开 http://localhost:8502 → 数据同步页
2. 点击「全量同步」→ 等待完成
3. 打开「持仓管理」→ 确认表格显示现价、市值、盈亏列
4. 打开「总览」→ 确认 KPI 显示持仓总市值和浮动盈亏
5. 查询数据库确认价格写入：
   ```bash
   cd "d:/工作/CBF开发/Stock/stock_dividend_calculator"
   C:/Users/85433/AppData/Local/Programs/Python/Python314/python.exe -c "
   from database.engine import DatabaseEngine
   db = DatabaseEngine()
   rows = db.fetch_all('SELECT stock_code, stock_name, current_price, price_updated_at FROM stocks WHERE current_price IS NOT NULL LIMIT 10')
   for r in rows: print(dict(r))
   "
   ```

- [ ] **Step 3: 最终提交**

```bash
cd "d:/工作/CBF开发/Stock"
git add -A
git commit -m "chore: 端到端测试通过"
```
