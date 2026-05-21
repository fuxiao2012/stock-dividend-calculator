# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

股票分红计算助手 — Streamlit 数据仪表盘应用，帮助投资者跟踪 A 股和 ETF 的分红方案，基于持仓数量自动计算预计分红金额。

## 启动与运行

```bash
# 安装依赖
C:\Users\85433\AppData\Local\Programs\Python\Python314\python.exe -m pip install -r requirements.txt

# 启动应用
C:\Users\85433\AppData\Local\Programs\Python\Python314\python.exe -m streamlit run app.py

# 停止服务（清理锁文件）
powershell -Command "Stop-Process -Name python -Force -ErrorAction SilentlyContinue"
rm -f data/stock_dividend.db-shm data/stock_dividend.db-wal
```

启动后在 `http://localhost:8502` 访问。典型流程：创建账户 → 添加持仓（手动或 CSV 导入）→ 数据同步 → 分红计算 → 查看结果/导出报告。

## 架构

```
app.py                          # Streamlit 入口，7 页面导航
├── database/
│   ├── engine.py               # SQLite 连接（@st.cache_resource 缓存，WAL 模式）
│   └── schema.py               # 建表 DDL + 迁移（含 init_database 入口）
├── data_sync/
│   ├── dividend_provider.py    # DividendProvider 抽象基类 + create_provider 工厂
│   ├── akshare_provider.py     # A 股（stock_history_dividend_detail）+ ETF（fund_fh_em）
│   └── sync_manager.py         # 同步编排：ETF/A 股分流、NULL-safe 去重、名称更新
├── services/
│   ├── account_service.py      # 账户 CRUD
│   ├── portfolio_service.py    # 持仓 CRUD（cost_total 自动计算）
│   ├── dividend_service.py     # 分红计算（税率 20%/10%/0%，预案/实施分流）
│   └── import_export_service.py# CSV/Excel 导入导出
├── ui/pages/                   # 7 个 Streamlit 页面
│   ├── dashboard.py            # 总览（KPI 卡片 + 图表 + 明细表）
│   ├── account_management.py   # 账户增删改
│   ├── position_management.py  # 持仓管理 + 批量导入/导出
│   ├── dividend_calculator.py  # 分红计算 + 按股票汇总
│   ├── dividend_schedule.py    # 分红时间表 + 月度柱状图
│   ├── data_sync.py            # 手动同步（全量/单股 + 进度条）
│   └── settings.py             # 税率配置 + 报告导出
└── utils/
    ├── retry.py                # @api_retry 装饰器（指数退避 + 降级返回空 DataFrame）
    └── exceptions.py           # DataSyncError, ValidationError, ImportError2
```

## 关键数据流

1. **数据同步**: `SyncManager.sync_stock()` → 检测 ETF（代码 15/51/56/58 开头）→ ETF 走 `get_etf_dividend()`（调用 `ak.fund_fh_em`），A 股走 `get_dividend_detail()`（调用 `ak.stock_history_dividend_detail`）→ NULL-safe 去重 → INSERT → 更新 stocks/positions 名称
2. **分红计算**: `DividendCalculationService.calculate_all()` → 遍历活跃持仓 → 按 stock_code 匹配 dividend_records → 判断资格（买入日期 ≤ 股权登记日）、持股天数 → 税率（除息日为空则 0%）→ INSERT OR REPLACE 到 dividend_calculations
3. **数据展示**: `get_calculations()` LEFT JOIN dividend_records 获取 ex_dividend_date、公告日期 → 推导报告期 → 页面展示

## 数据库核心表

- **dividend_records**: 分红原始数据，`cash_per_10` 为每 10 股派息金额。取数据后去重再入库
- **positions**: 用户持仓，`cost_total` 在更新 qty/cost_price 时由 Python 计算后显式写入（SQLite UPDATE 中 SET 表达式基于原始行值，不能依赖 SQL 计算）
- **dividend_calculations**: 计算结果，`UNIQUE(position_id, dividend_record_id)` 防止重复

## 常见陷阱

- **akshare 列名**: `stock_history_dividend_detail` 返回 `派息`（Unicode 0x6d3e, 0x606f）不是 `股息`（0x80a1, 0x606f）
- **sqlite3.Row 陷阱**: `pd.DataFrame(sqlite3.Row)` → 列名丢失成数字，必须 `pd.DataFrame([dict(r) for r in rows])`。Row 没有 `.get()` 方法，需用 `"key" in row` 检查键存在性再取 `row["key"]`
- **NULL 去重**: SQLite 中 `UNIQUE(col_with_nulls)` 对 NULL 失效，必须用显式 SELECT 检查。`_safe_str()` 将 NaT/nan 转为 None
- **Streamlit file_uploader**: 上传后调用 `st.rerun()` 会导致无限循环重新导入，必须用 `st.session_state` 记录已处理文件的标识（name_size）
- **数据库锁**: 非 Streamlit 环境测试时需先停止 Streamlit。**重启前必须先 checkpoint**：`PRAGMA wal_checkpoint(TRUNCATE)` 将 WAL 写入合并到主 DB，否则 force kill + 删 WAL 文件会导致数据丢失
- **ETF 分红来源**: A 股走 `stock_history_dividend_detail`，ETF（15/51/56/58 开头）走 `fund_fh_em`，ETF 每份分红 × 10 = cash_per_10
- **5 年限制**: `sync_stock` 中 `since_year = datetime.now().year - 5`，A 股 API 过滤 announce_date，ETF API 默认查近 5 年
- **预案税率**: `_calc_one` 中若 `ex_date` 为空（预案无除息日）→ tax_rate=0，net=gross
- **A 股市价 API 选型**: 东方财富 A 股接口（`stock_zh_a_spot_em`、`stock_zh_a_hist`）均被网络阻断（ConnectionError），Sina `stock_zh_a_spot` 有严格频率限制（第二次调用即返回 HTML）。**腾讯 `stock_zh_a_hist_tx` 是目前唯一可靠的 A 股价源**，需要 `sh`/`sz` 前缀（6/9 开头→`sh`，0/3 开头→`sz`），返回 `close` 列作为 `current_price`
- **.gitignore 路径**: gitignore 规则相对于仓库根目录匹配。`data/exports/` 只匹配根下的 `data/exports/`，不匹配 `stock_dividend_calculator/data/exports/`。子目录下的路径需写完整路径如 `stock_dividend_calculator/data/`，或用 `**/exports/`。每条规则加完后必须跑 `git status` 验证文件被正确忽略
- **Worktree 路径陷阱**: `EnterWorktree` 后 CWD 切换到 worktree 副本路径（如 `.claude/worktrees/sync-duration/`），但 `Edit`/`Write` 工具使用绝对路径时容易误指回原始仓库，导致改动落在 master 而非 worktree 分支。进入 worktree 后先用 `pwd` 确认当前路径，所有文件操作使用 worktree 下的路径
