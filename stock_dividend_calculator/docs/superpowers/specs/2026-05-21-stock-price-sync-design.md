# 股票/ETF 市价同步 — 设计文档

## Context

当前系统只有分红数据，缺少股票市价。用户在持仓管理页和总览页看不到当前市值和浮动盈亏。需要集成市价同步，在一次全量同步中同时获取分红和价格。

## 用户需求确认

- **数据类型**：最新市价（实时快照），不是历史日K线
- **存储位置**：`stocks` 表加字段
- **触发方式**：集成到现有数据同步流程（全量/单股）
- **覆盖范围**：A 股 + ETF 都要

## API 选型

| 类型 | API | 入参 | 返回 |
|------|-----|------|------|
| A 股市价 | `ak.stock_zh_a_spot_em()` | 无 | 全市场 ~5000 只 A 股实时行情 |
| ETF 市价 | `ak.fund_etf_spot_em()` | 无 | 全市场所有 ETF 实时行情 |

两个 API 均无参数，一次返回全市场数据，本地按持仓代码过滤。总共 2 次 API 调用，不随持仓数量增长。

## 具体改动

### 1. `database/schema.py` — stocks 表加字段

```sql
ALTER TABLE stocks ADD COLUMN current_price REAL;
ALTER TABLE stocks ADD COLUMN price_updated_at TEXT;
```

通过迁移方式添加，已有表自动兼容。

### 2. `data_sync/akshare_provider.py` — 新增两个方法

**`get_all_stock_prices() -> pd.DataFrame`**
- 调用 `ak.stock_zh_a_spot_em()`
- 返回列映射：`代码` → `stock_code`，`最新价` → `current_price`，`涨跌幅` → `change_pct`
- 保留其他有用字段：`成交量`、`换手率` 等

**`get_all_etf_prices() -> pd.DataFrame`**
- 调用 `ak.fund_etf_spot_em()`
- 返回列映射：基金代码 → `stock_code`，最新价 → `current_price`，涨跌幅 → `change_pct`

两个方法都带 `@api_retry` 装饰器 + 空 DataFrame 降级。

### 3. `data_sync/sync_manager.py` — 新增批量价格同步

**`_sync_stock_prices(codes)`**
- 调用 `provider.get_all_stock_prices()` 一次
- 按持仓代码过滤
- UPDATE `stocks SET current_price=?, price_updated_at=?` WHERE `stock_code=?`
- 只更新当前持仓的股票，不写全市场

**`_sync_etf_prices(codes)`**
- 调用 `provider.get_all_etf_prices()` 一次
- 同上逻辑，更新 ETF 对应 stocks 记录

### 4. `data_sync/sync_manager.py` — 修改 `sync_all()`

现有流程：
```
sync_all()
  ├── _sync_etf_batch()      ETF 分红
  └── sync_stock() × N       A 股分红
```

新流程：
```
sync_all()
  ├── _sync_etf_batch()      ETF 分红
  ├── sync_stock() × N       A 股分红
  ├── _sync_stock_prices()   A 股市价  ← 新增，1 次 API
  └── _sync_etf_prices()     ETF 市价  ← 新增，1 次 API
```

价格同步放在分红同步之后，进度回调计入总数。

### 5. UI 页面 — 展示市价和盈亏

**持仓管理页 (`position_management.py`) — Tab 2 表格**
- 新增列：现价（disabled）、市值（quantity × price）、盈亏（市值 - 成本总额）
- 盈亏列用 `st.column_config.NumberColumn` + 颜色（红涨绿跌）
- 摘要栏 KPI 新增「持仓总市值」替代「持仓总成本」

**总览页 (`dashboard.py`)**
- KPI 卡片新增「持仓总市值」
- 可选：显示总浮动盈亏

### 6. 单股同步 `sync_stock()` — 追加价格刷新

单股同步时也拉取该股的最新价格：
- A 股：调用 `stock_zh_a_spot_em` 全市场数据，只取该股
- ETF：调用 `fund_etf_spot_em` 全市场数据，只取该 ETF

（仍是一次 API 全市场拉取，本地过滤，单股不额外优化）

## 数据流示意

```
用户点击「全量同步」
  → sync_all()
    → 分红同步（现有逻辑，含首次/增量判断）
    → 价格同步（新增）
      → A 股：ak.stock_zh_a_spot_em() → filter(codes) → UPDATE stocks
      → ETF：ak.fund_etf_spot_em() → filter(codes) → UPDATE stocks
  → UI 刷新
    → st.metric("持仓总市值", total_market_value)
    → 表格显示现价、市值、盈亏
```

## 验证方式

1. 全量同步 → 检查 sync_log 新增价格相关日志
2. 数据库：`SELECT current_price FROM stocks` 确认有值
3. 持仓管理页：表格显示现价、市值、盈亏列
4. 总览页：KPI 显示持仓总市值
5. ETF 持仓：价格正确拉取并展示
