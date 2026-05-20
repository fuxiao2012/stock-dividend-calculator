"""分红计算服务 — 核心业务逻辑"""
from datetime import datetime, date
from typing import Optional
import pandas as pd
from database.engine import DatabaseEngine


class DividendCalculationService:

    def __init__(self):
        self.db = DatabaseEngine()
        self._tax_rates = self._load_tax_rates()

    def _load_tax_rates(self) -> dict:
        rows = self.db.fetch_all(
            "SELECT key, value FROM system_config WHERE key LIKE 'tax_%'"
        )
        rates = {}
        for row in rows:
            rates[row["key"]] = float(row["value"]) / 100.0
        return rates

    def _get_tax_rate_config(self) -> tuple:
        """返回 (<=1月, 1月-1年, >1年) 税率"""
        return (
            self._tax_rates.get("tax_holding_month", 0.20),
            self._tax_rates.get("tax_holding_year", 0.10),
            self._tax_rates.get("tax_holding_long", 0.00),
        )

    # ------------------------------------------------------------------
    # 核心计算
    # ------------------------------------------------------------------

    def calculate_for_position(self, position_id: int, dividend_record_id: int) -> dict | None:
        """计算单笔持仓 × 单次分红"""
        pos = self.db.fetch_one("SELECT * FROM positions WHERE id = ?", (position_id,))
        div = self.db.fetch_one("SELECT * FROM dividend_records WHERE id = ?", (dividend_record_id,))
        if not pos or not div:
            return None

        cash_per_10 = div["cash_per_10"] or 0
        if cash_per_10 <= 0:
            return None
        result = self._calc_one(pos, div)
        if result:
            self._save_calculation(result)
        return result

    def calculate_all(self, year: Optional[int] = None,
                      account_id: Optional[int] = None) -> pd.DataFrame:
        """全量计算所有持仓与分红记录的匹配"""
        positions = self.db.fetch_all("SELECT * FROM positions WHERE is_active = 1")
        if not positions:
            return pd.DataFrame()

        results = []
        for pos in positions:
            if account_id and pos["account_id"] != account_id:
                continue
            query = """SELECT * FROM dividend_records
                       WHERE stock_code = ?
                         AND cash_per_10 IS NOT NULL AND cash_per_10 > 0
                         AND (progress IS NULL OR progress NOT IN ('未通过', '已取消'))"""
            params = [pos["stock_code"]]
            if year:
                query += """ AND (
                    strftime('%Y', record_date) = ? OR (
                        record_date IS NULL AND strftime('%Y', COALESCE(ex_dividend_date, announce_date)) = ?
                    )
                )"""
                params.extend([str(year), str(year)])
            divs = self.db.fetch_all(query, tuple(params))
            for div in divs:
                r = self._calc_one(pos, div)
                if r:
                    self._save_calculation(r)
                    results.append(r)

        return pd.DataFrame(results)

    def _calc_one(self, pos, div) -> dict | None:
        buy_date = pos["buy_date"]
        record_date = div["record_date"]
        ex_date = div["ex_dividend_date"]
        announce_date = div["announce_date"]
        sell_date = pos["sell_date"]
        progress = div["progress"] or ""

        cash_per_10 = div["cash_per_10"] or 0
        if cash_per_10 <= 0:
            return None

        is_eligible = self._is_eligible(buy_date, record_date, sell_date)
        cash_per_share = cash_per_10 / 10.0
        quantity = pos["quantity"]
        gross = round(quantity * cash_per_share, 2)
        hold_days = self._estimate_hold_days(buy_date, record_date, sell_date)
        if ex_date:
            tax_rate = self._calculate_tax_rate(hold_days)
            tax_amount = round(gross * tax_rate, 2)
            net = round(gross - tax_amount, 2)
        else:
            tax_rate = 0
            tax_amount = 0
            net = gross

        # 用股权登记日做日期基准，无则用除权除息日或公告日期
        effective_date = record_date or ex_date or announce_date or ""

        return {
            "position_id": pos["id"],
            "dividend_record_id": div["id"],
            "account_id": pos["account_id"],
            "stock_code": pos["stock_code"],
            "stock_name": pos["stock_name"] or "",
            "record_date": effective_date,
            "cash_per_share": cash_per_share,
            "hold_quantity": quantity,
            "gross_dividend": gross,
            "tax_rate": tax_rate,
            "tax_amount": tax_amount,
            "net_dividend": net,
            "is_eligible": 1 if is_eligible else 0,
            "progress": progress,
            "calculation_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _save_calculation(self, result: dict):
        self.db.execute(
            """INSERT OR REPLACE INTO dividend_calculations
               (position_id, dividend_record_id, account_id, stock_code, stock_name,
                record_date, cash_per_share, hold_quantity, gross_dividend,
                tax_rate, tax_amount, net_dividend, is_eligible, progress, calculation_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (result["position_id"], result["dividend_record_id"], result["account_id"],
             result["stock_code"], result["stock_name"], result["record_date"],
             result["cash_per_share"], result["hold_quantity"], result["gross_dividend"],
             result["tax_rate"], result["tax_amount"], result["net_dividend"],
             result["is_eligible"], result.get("progress", ""), result["calculation_date"]),
        )
        self.db.commit()

    # ------------------------------------------------------------------
    # 查询与统计
    # ------------------------------------------------------------------

    def get_calculations(self, year: Optional[int] = None,
                         account_id: Optional[int] = None) -> pd.DataFrame:
        query = """SELECT dc.*, dr.ex_dividend_date, dr.announce_date as div_announce_date
                   FROM dividend_calculations dc
                   LEFT JOIN dividend_records dr ON dc.dividend_record_id = dr.id
                   WHERE 1=1"""
        params = []
        if year:
            query += " AND strftime('%Y', dc.record_date) = ?"
            params.append(str(year))
        if account_id:
            query += " AND dc.account_id = ?"
            params.append(account_id)
        rows = self.db.fetch_all(query + " ORDER BY dc.record_date DESC", tuple(params))
        return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()

    def get_yearly_summary(self, year: int, account_id: Optional[int] = None) -> pd.DataFrame:
        query = """SELECT stock_code, stock_name,
                   COUNT(*) as dividend_count,
                   SUM(gross_dividend) as total_gross,
                   SUM(net_dividend) as total_net
                   FROM dividend_calculations
                   WHERE strftime('%Y', record_date) = ? AND is_eligible = 1"""
        params = [str(year)]
        if account_id:
            query += " AND account_id = ?"
            params.append(account_id)
        query += " GROUP BY stock_code ORDER BY total_net DESC"
        rows = self.db.fetch_all(query, tuple(params))
        return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()

    def get_monthly_summary(self, year: int, account_id: Optional[int] = None) -> pd.DataFrame:
        query = """SELECT strftime('%m', record_date) as month,
                   SUM(gross_dividend) as total_gross,
                   SUM(net_dividend) as total_net,
                   COUNT(*) as count
                   FROM dividend_calculations
                   WHERE strftime('%Y', record_date) = ? AND is_eligible = 1"""
        params = [str(year)]
        if account_id:
            query += " AND account_id = ?"
            params.append(account_id)
        query += " GROUP BY month ORDER BY month"
        rows = self.db.fetch_all(query, tuple(params))
        return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()

    def get_upcoming_schedule(self, limit: int = 20) -> pd.DataFrame:
        """获取近期将发生的分红事件（按除权除息日排序）"""
        rows = self.db.fetch_all(
            """SELECT dc.*, dr.ex_dividend_date, dr.announce_date
               FROM dividend_calculations dc
               JOIN dividend_records dr ON dc.dividend_record_id = dr.id
               WHERE dc.is_eligible = 1
               ORDER BY dr.ex_dividend_date ASC
               LIMIT ?""",
            (limit,),
        )
        return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()

    def get_total_stats(self, year: Optional[int] = None,
                        account_id: Optional[int] = None) -> dict:
        """获取分红总计统计"""
        query = """SELECT SUM(gross_dividend) as total_gross,
                   SUM(net_dividend) as total_net,
                   COUNT(*) as record_count,
                   COUNT(DISTINCT stock_code) as stock_count
                   FROM dividend_calculations
                   WHERE is_eligible = 1"""
        params = []
        if year:
            query += " AND strftime('%Y', record_date) = ?"
            params.append(str(year))
        if account_id:
            query += " AND account_id = ?"
            params.append(account_id)
        row = self.db.fetch_one(query, tuple(params))
        if row:
            return {
                "total_gross": row["total_gross"] or 0,
                "total_net": row["total_net"] or 0,
                "record_count": row["record_count"],
                "stock_count": row["stock_count"],
            }
        return {"total_gross": 0, "total_net": 0, "record_count": 0, "stock_count": 0}

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _calculate_tax_rate(self, hold_days: int) -> float:
        """A股股息红利差别化个人所得税"""
        rate_1m, rate_1y, rate_long = self._get_tax_rate_config()
        if hold_days <= 30:
            return rate_1m
        elif hold_days <= 365:
            return rate_1y
        return rate_long

    def _estimate_hold_days(self, buy_date: str | None, record_date: str | None,
                            sell_date: str | None = None) -> int:
        """估算截止到股权登记日的持股天数"""
        if not buy_date or not record_date:
            return 0
        try:
            bd = datetime.strptime(buy_date[:10], "%Y-%m-%d")
            rd = datetime.strptime(record_date[:10], "%Y-%m-%d")
            if sell_date:
                sd = datetime.strptime(sell_date[:10], "%Y-%m-%d")
                return (min(sd, rd) - bd).days
            return (rd - bd).days
        except ValueError:
            return 0

    def _is_eligible(self, buy_date: str | None, record_date: str | None,
                     sell_date: str | None = None) -> bool:
        """判断持仓是否能享受本次分红（record_date 为空则视为预告阶段，默认享受）"""
        if not record_date:
            return True
        try:
            rd = datetime.strptime(record_date[:10], "%Y-%m-%d")
        except ValueError:
            return True  # NaT 等无效日期也视为预告
        if buy_date:
            try:
                bd = datetime.strptime(buy_date[:10], "%Y-%m-%d")
                if bd > rd:
                    return False
            except ValueError:
                pass
        if sell_date:
            try:
                sd = datetime.strptime(sell_date[:10], "%Y-%m-%d")
                if sd < rd:
                    return False
            except ValueError:
                pass
        return True
