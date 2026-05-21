"""同步管理器：编排数据拉取、去重、日志记录"""
from datetime import datetime
from typing import Optional, Callable
import pandas as pd
from database.engine import DatabaseEngine
from .dividend_provider import DividendProvider, create_provider
from utils.exceptions import DataSyncError


class SyncManager:

    def __init__(self, provider: DividendProvider | None = None):
        self.provider = provider or create_provider("A")
        self.db = DatabaseEngine()

    def _has_existing_records(self, stock_code: str) -> bool:
        """检查 dividend_records 中是否已有该股票的分红数据"""
        row = self.db.fetch_one(
            "SELECT 1 FROM dividend_records WHERE stock_code=? LIMIT 1",
            (stock_code,),
        )
        return True if row else False

    def sync_stock(self, stock_code: str) -> dict:
        """同步单只股票的分红数据，并更新股票名称"""
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result = {"stock_code": stock_code, "status": "成功", "fetched": 0, "inserted": 0, "name_updated": False}
        current_year = datetime.now().year
        is_first_sync = not self._has_existing_records(stock_code)
        since_year = current_year - 5 if is_first_sync else current_year
        result["sync_scope"] = "近5年" if is_first_sync else "当年"
        try:
            if self._is_etf(stock_code):
                if is_first_sync:
                    years = [str(y) for y in range(current_year, current_year - 5, -1)]
                else:
                    years = [str(current_year)]
                df = self.provider.get_etf_dividend(stock_code, years=years)
            else:
                df = self.provider.get_dividend_detail(stock_code, since_year=since_year)
            result["fetched"] = len(df)
            if not df.empty:
                if self._is_etf(stock_code):
                    inserted = self._insert_etf_records(df)
                else:
                    inserted = self._insert_records(df)
                result["inserted"] = inserted
            result["name_updated"] = self._update_stock_name(stock_code)
        except DataSyncError as e:
            result["status"] = "失败"
            result["error"] = str(e)
        except Exception as e:
            result["status"] = "失败"
            result["error"] = str(e)

        self._log_sync("单只股票", stock_code, result, started_at)
        return result

    @staticmethod
    def _is_etf(code: str) -> bool:
        return str(code).startswith(("15", "51", "56", "58"))

    def sync_all(self, progress_callback: Optional[Callable] = None) -> dict:
        """全量同步所有持仓股票的分红数据（ETF 批量拉取，A股逐只拉取）"""
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stocks = self.db.fetch_all("SELECT DISTINCT stock_code FROM positions WHERE is_active = 1")
        all_codes = [row["stock_code"] for row in stocks]

        if not all_codes:
            return {"status": "成功", "total": 0, "succeeded": 0, "failed": 0, "results": []}

        # 分离 ETF 和 A 股
        etf_codes = [c for c in all_codes if self._is_etf(c)]
        stock_codes = [c for c in all_codes if not self._is_etf(c)]
        total = len(all_codes)
        results = []
        succeeded = 0
        failed = 0

        # ETF 批量同步
        if etf_codes:
            etf_results = self._sync_etf_batch(etf_codes, progress_callback, offset=0, total=total)
            results.extend(etf_results)

        # A 股逐只同步
        for i, code in enumerate(stock_codes):
            r = self.sync_stock(code)
            results.append(r)
            if progress_callback:
                progress_callback((len(etf_codes) + i + 1) / total)

        # 统计全部结果
        for r in results:
            if r["status"] == "成功":
                succeeded += 1
            else:
                failed += 1

        self._log_sync("全量", None, {
            "status": "成功" if failed == 0 else "失败",
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
        }, started_at)

        return {
            "status": "成功" if failed == 0 else "部分失败",
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        }

    def _sync_etf_batch(self, codes: list, progress_callback=None, offset=0, total=0) -> list:
        """批量同步所有 ETF：一次性拉取全市场数据，再按代码分发"""
        current_year = datetime.now().year
        # 判断是否需要5年数据：任一 ETF 是首次同步就需要
        need_full = any(not self._has_existing_records(c) for c in codes)
        if need_full:
            years = [str(y) for y in range(current_year, current_year - 5, -1)]
        else:
            years = [str(current_year)]

        all_data = self.provider.get_all_etf_dividends(years=years)
        results = []

        for i, code in enumerate(codes):
            started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            is_first = not self._has_existing_records(code)
            result = {"stock_code": code, "status": "成功", "fetched": 0, "inserted": 0,
                      "name_updated": False, "sync_scope": "近5年" if is_first else "当年"}
            try:
                if all_data.empty:
                    result["fetched"] = 0
                else:
                    subset = all_data[all_data["stock_code"] == code]
                    result["fetched"] = len(subset)
                    if not subset.empty:
                        result["inserted"] = self._insert_etf_records(subset)
                result["name_updated"] = self._update_stock_name(code)
            except DataSyncError as e:
                result["status"] = "失败"
                result["error"] = str(e)
            except Exception as e:
                result["status"] = "失败"
                result["error"] = str(e)

            self._log_sync("单只股票", code, result, started_at)
            results.append(result)
            if progress_callback and total:
                progress_callback((offset + i + 1) / total)

        return results

    def _insert_records(self, df: pd.DataFrame) -> int:
        """将 DataFrame 中的分红记录插入数据库（去重，含 NULL 安全处理）"""
        conn = DatabaseEngine.get_connection()
        inserted = 0
        for _, row in df.iterrows():
            try:
                code = row.get("stock_code")
                announce = self._safe_str(row.get("announce_date"))
                record = self._safe_str(row.get("record_date"))
                # 显式检查是否已存在（NULL-safe 比较）
                if record:
                    exist = conn.execute(
                        "SELECT 1 FROM dividend_records WHERE stock_code=? AND announce_date=? AND record_date=?",
                        (code, announce, record),
                    ).fetchone()
                else:
                    exist = conn.execute(
                        "SELECT 1 FROM dividend_records WHERE stock_code=? AND announce_date=? AND record_date IS NULL",
                        (code, announce),
                    ).fetchone()
                if exist:
                    continue
                cur = conn.execute("""
                    INSERT INTO dividend_records
                        (stock_code, announce_date, record_date, ex_dividend_date,
                         bonus_share_date, cash_per_10, bonus_shares_per_10,
                         cap_increase_per_10, progress)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    code, announce, record,
                    self._safe_str(row.get("ex_dividend_date")),
                    self._safe_str(row.get("bonus_share_date")),
                    self._safe_float(row.get("cash_per_10")),
                    self._safe_float(row.get("bonus_shares_per_10")),
                    self._safe_float(row.get("cap_increase_per_10")),
                    self._normalize_progress(self._safe_str(row.get("progress"))),
                ))
                if cur.rowcount and cur.rowcount > 0:
                    inserted += 1
            except Exception:
                continue
        conn.commit()
        return inserted

    def _log_sync(self, sync_type: str, stock_code: Optional[str], result: dict, started_at: str):
        conn = DatabaseEngine.get_connection()
        finished_at = datetime.now()
        started_dt = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
        duration = round((finished_at - started_dt).total_seconds(), 1)
        conn.execute("""
            INSERT INTO sync_log (sync_type, stock_code, status, records_fetched,
                                  records_inserted, error_message, started_at, finished_at,
                                  duration_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sync_type,
            stock_code,
            result.get("status", "失败"),
            result.get("fetched", 0),
            result.get("inserted", 0),
            result.get("error", ""),
            started_at,
            finished_at.strftime("%Y-%m-%d %H:%M:%S"),
            duration,
        ))
        conn.commit()

    @staticmethod
    def _normalize_progress(raw: str) -> str:
        if not raw:
            return "其他"
        for key in ["预案", "实施", "未通过", "已取消"]:
            if key in raw:
                return key
        return "其他"

    @staticmethod
    def _safe_str(val) -> Optional[str]:
        if val is None:
            return None
        try:
            if pd.isna(val):
                return None
        except (TypeError, ValueError):
            pass
        s = str(val)
        if s in ("NaT", "nan", "None", ""):
            return None
        return s

    @staticmethod
    def _safe_float(val) -> Optional[float]:
        try:
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return None
            return float(val)
        except (ValueError, TypeError):
            return None

    def _insert_etf_records(self, df: pd.DataFrame) -> int:
        """插入 ETF 分红记录（数据已由 provider 映射好）"""
        conn = DatabaseEngine.get_connection()
        inserted = 0
        etf_name = ""
        for _, row in df.iterrows():
            try:
                code = row.get("stock_code")
                announce = self._safe_str(row.get("record_date"))
                record = self._safe_str(row.get("record_date"))
                if not etf_name:
                    etf_name = str(row.get("stock_name", "")) if pd.notna(row.get("stock_name")) else ""
                # NULL-safe 去重检查
                if record:
                    exist = conn.execute(
                        "SELECT 1 FROM dividend_records WHERE stock_code=? AND announce_date=? AND record_date=?",
                        (code, announce, record),
                    ).fetchone()
                else:
                    exist = conn.execute(
                        "SELECT 1 FROM dividend_records WHERE stock_code=? AND announce_date=? AND record_date IS NULL",
                        (code, announce),
                    ).fetchone()
                if exist:
                    continue
                cur = conn.execute("""
                    INSERT INTO dividend_records
                        (stock_code, announce_date, record_date, ex_dividend_date,
                         bonus_share_date, cash_per_10, bonus_shares_per_10,
                         cap_increase_per_10, progress)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    code, announce, record,
                    self._safe_str(row.get("ex_dividend_date")),
                    self._safe_str(row.get("bonus_share_date")),
                    self._safe_float(row.get("cash_per_10")),
                    None, None, "实施",
                ))
                if cur.rowcount and cur.rowcount > 0:
                    inserted += 1
            except Exception:
                continue
        conn.commit()
        # 用 ETF 名称更新持仓和股票表
        if etf_name:
            self._apply_stock_name(code, etf_name)
        return inserted

    def _update_stock_name(self, stock_code: str) -> bool:
        """更新 stocks 和 positions 表中的股票名称"""
        name = None
        try:
            info = self.provider.get_stock_info(stock_code)
            name = info.get("name", "") if isinstance(info, dict) else ""
        except Exception:
            pass
        if not name:
            row = self.db.fetch_one(
                "SELECT stock_name FROM stocks WHERE stock_code = ? AND stock_name IS NOT NULL AND stock_name != ''",
                (stock_code,),
            )
            if row:
                name = row["stock_name"]
        if not name:
            return False
        return self._apply_stock_name(stock_code, name)

    def _apply_stock_name(self, stock_code: str, name: str) -> bool:
        """将股票名称写入 stocks 和 positions 表"""
        self.db.execute(
            "INSERT OR REPLACE INTO stocks (stock_code, stock_name, exchange) VALUES (?, ?, 'SZ')",
            (stock_code, name),
        )
        self.db.execute(
            "UPDATE positions SET stock_name = ? WHERE stock_code = ? AND (stock_name IS NULL OR stock_name = '' OR stock_name = 'nan')",
            (name, stock_code),
        )
        self.db.commit()
        return True
