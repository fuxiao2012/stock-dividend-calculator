"""数据库 Schema — DDL 建表语句"""
from database.engine import DatabaseEngine


def init_database():
    """初始化数据库，创建所有表和默认配置"""
    conn = DatabaseEngine.get_connection()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stocks (
            stock_code    TEXT PRIMARY KEY,
            stock_name    TEXT NOT NULL,
            exchange      TEXT NOT NULL CHECK(exchange IN ('SH','SZ','BJ')),
            listing_date  TEXT,
            is_active     INTEGER DEFAULT 1,
            created_at    TEXT DEFAULT (datetime('now','localtime')),
            updated_at    TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS dividend_records (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code              TEXT NOT NULL,
            announce_date           TEXT,
            record_date             TEXT,
            ex_dividend_date        TEXT,
            bonus_share_date        TEXT,
            cash_per_10             REAL,
            bonus_shares_per_10     REAL,
            cap_increase_per_10     REAL,
            progress                TEXT CHECK(progress IN ('预案','实施','未通过','已取消','其他')),
            plan_type               TEXT DEFAULT '分红' CHECK(plan_type IN ('分红','配股')),
            data_source             TEXT DEFAULT 'akshare',
            raw_json                TEXT,
            created_at              TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(stock_code, announce_date, record_date)
        );

        CREATE INDEX IF NOT EXISTS idx_div_stock     ON dividend_records(stock_code);
        CREATE INDEX IF NOT EXISTS idx_div_record_dt ON dividend_records(record_date);
        CREATE INDEX IF NOT EXISTS idx_div_ex_dt     ON dividend_records(ex_dividend_date);
        CREATE INDEX IF NOT EXISTS idx_div_progress  ON dividend_records(progress);

        CREATE TABLE IF NOT EXISTS accounts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            account_name    TEXT NOT NULL UNIQUE,
            account_type    TEXT NOT NULL DEFAULT '普通账户'
                            CHECK(account_type IN ('普通账户','融资融券账户')),
            broker          TEXT,
            notes           TEXT,
            is_active       INTEGER DEFAULT 1,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            updated_at      TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS positions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id      INTEGER NOT NULL,
            stock_code      TEXT NOT NULL,
            stock_name      TEXT,
            quantity        INTEGER NOT NULL CHECK(quantity > 0),
            cost_price      REAL,
            cost_total      REAL,
            buy_date        TEXT,
            sell_date       TEXT,
            notes           TEXT,
            is_active       INTEGER DEFAULT 1,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            updated_at      TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
            FOREIGN KEY (stock_code) REFERENCES stocks(stock_code)
        );

        CREATE INDEX IF NOT EXISTS idx_pos_account ON positions(account_id);
        CREATE INDEX IF NOT EXISTS idx_pos_stock   ON positions(stock_code);
        CREATE INDEX IF NOT EXISTS idx_pos_active  ON positions(is_active);

        CREATE TABLE IF NOT EXISTS dividend_calculations (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id             INTEGER NOT NULL,
            dividend_record_id      INTEGER NOT NULL,
            account_id              INTEGER NOT NULL,
            stock_code              TEXT NOT NULL,
            stock_name              TEXT,
            record_date             TEXT,
            cash_per_share          REAL,
            hold_quantity           INTEGER,
            gross_dividend          REAL,
            tax_rate                REAL DEFAULT 0.10,
            tax_amount              REAL,
            net_dividend            REAL,
            is_eligible             INTEGER DEFAULT 1,
            progress                TEXT DEFAULT '',
            calculation_date        TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(position_id, dividend_record_id),
            FOREIGN KEY (position_id) REFERENCES positions(id) ON DELETE CASCADE,
            FOREIGN KEY (dividend_record_id) REFERENCES dividend_records(id),
            FOREIGN KEY (account_id) REFERENCES accounts(id),
            FOREIGN KEY (stock_code) REFERENCES stocks(stock_code)
        );

        CREATE INDEX IF NOT EXISTS idx_calc_account  ON dividend_calculations(account_id);
        CREATE INDEX IF NOT EXISTS idx_calc_stock    ON dividend_calculations(stock_code);
        CREATE INDEX IF NOT EXISTS idx_calc_position ON dividend_calculations(position_id);
        CREATE INDEX IF NOT EXISTS idx_calc_record   ON dividend_calculations(dividend_record_id);

        CREATE TABLE IF NOT EXISTS sync_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_type       TEXT NOT NULL CHECK(sync_type IN ('全量','增量','单只股票')),
            stock_code      TEXT,
            status          TEXT NOT NULL CHECK(status IN ('运行中','成功','失败')),
            records_fetched INTEGER DEFAULT 0,
            records_inserted INTEGER DEFAULT 0,
            error_message   TEXT,
            started_at      TEXT,
            finished_at     TEXT,
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_sync_status ON sync_log(status);
        CREATE INDEX IF NOT EXISTS idx_sync_time   ON sync_log(created_at);

        CREATE TABLE IF NOT EXISTS import_export_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            op_type         TEXT NOT NULL CHECK(op_type IN ('导入','导出')),
            file_name       TEXT NOT NULL,
            file_format     TEXT NOT NULL CHECK(file_format IN ('csv','xlsx')),
            record_count    INTEGER DEFAULT 0,
            status          TEXT DEFAULT '成功',
            error_message   TEXT,
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS system_config (
            key             TEXT PRIMARY KEY,
            value           TEXT,
            description     TEXT,
            updated_at      TEXT DEFAULT (datetime('now','localtime'))
        );
    """)

    # 写入默认配置
    defaults = [
        ("tax_holding_month", "20", "持股1个月内税率(%)"),
        ("tax_holding_year", "10", "持股1月-1年税率(%)"),
        ("tax_holding_long", "0", "持股超1年税率(%)"),
        ("dividend_data_source", "akshare", "数据源"),
        ("db_version", "1", "数据库版本号"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO system_config(key, value, description) VALUES (?, ?, ?)",
        defaults,
    )

    # 数据库迁移
    try:
        conn.execute("ALTER TABLE dividend_calculations ADD COLUMN progress TEXT DEFAULT ''")
    except Exception:
        pass

    conn.commit()
