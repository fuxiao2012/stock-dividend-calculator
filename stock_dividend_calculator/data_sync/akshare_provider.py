"""A股分红数据提供者 — akshare 实现"""
import pandas as pd
from typing import Optional
from .dividend_provider import DividendProvider
from utils.retry import api_retry
from utils.exceptions import DataSyncError

# akshare 返回的中文字段映射
COLUMN_MAP = {
    "公告日期": "announce_date",
    "送股": "bonus_shares_per_10",
    "转增": "cap_increase_per_10",
    "派息": "cash_per_10",
    "进度": "progress",
    "除权除息日": "ex_dividend_date",
    "股权登记日": "record_date",
    "红股上市日": "bonus_share_date",
}


class AkshareDividendProvider(DividendProvider):

    @api_retry(max_retries=3, delay=2.0)
    def get_dividend_detail(self, stock_code: str, since_year: int = None) -> pd.DataFrame:
        try:
            import akshare as ak
            from datetime import datetime
            df = ak.stock_history_dividend_detail(symbol=stock_code, indicator="分红")
            if df.empty:
                return df
            df["stock_code"] = stock_code
            existing_cols = {c: COLUMN_MAP[c] for c in COLUMN_MAP if c in df.columns}
            df = df.rename(columns=existing_cols)
            # 近 N 年过滤
            if since_year:
                df = df[df["announce_date"].apply(
                    lambda d: pd.notna(d) and hasattr(d, 'year') and d.year >= since_year
                )]
            return df
        except ImportError:
            raise DataSyncError("akshare 未安装，请运行 pip install akshare")
        except Exception as e:
            raise DataSyncError(f"获取 {stock_code} 分红明细失败: {e}") from e

    @api_retry(max_retries=3, delay=2.0)
    def get_dividend_summary(self) -> pd.DataFrame:
        """获取近期全市场分红预告（东方财富数据）"""
        try:
            import akshare as ak
            df = ak.stock_dividents_cninfo()
            return df
        except Exception:
            return pd.DataFrame()

    @api_retry(max_retries=3, delay=2.0)
    def get_upcoming_dividends(self, date: Optional[str] = None) -> pd.DataFrame:
        try:
            import akshare as ak
            if date is None:
                from datetime import datetime
                date = datetime.now().strftime("%Y%m%d")
            df = ak.news_trade_notify_dividend_baidu(date=date)
            return df
        except Exception:
            return pd.DataFrame()

    @api_retry(max_retries=2, delay=1.0,
               degrade_value={"code": "", "name": "", "listing_date": "", "industry": ""})
    def get_stock_info(self, stock_code: str) -> dict:
        try:
            import akshare as ak
            # 优先用 stock_individual_info_em
            try:
                df = ak.stock_individual_info_em(symbol=stock_code)
                kv = dict(zip(df["item"], df["value"]))
                return {
                    "code": kv.get("股票代码", stock_code),
                    "name": kv.get("股票简称", ""),
                    "listing_date": str(kv.get("上市时间", "")),
                    "industry": kv.get("行业", ""),
                }
            except Exception:
                pass
            # 降级：用 A 股全量列表查找
            df = ak.stock_info_a_code_name()
            row = df[df["code"] == stock_code]
            if not row.empty:
                return {
                    "code": stock_code,
                    "name": row.iloc[0]["name"],
                    "listing_date": "",
                    "industry": "",
                }
            return {"code": stock_code, "name": "", "listing_date": "", "industry": ""}
        except Exception as e:
            raise DataSyncError(f"获取 {stock_code} 股票信息失败: {e}") from e

    @api_retry(max_retries=3, delay=1.0)
    def get_all_stocks(self) -> pd.DataFrame:
        try:
            import akshare as ak
            df = ak.stock_info_a_code_name()
            df["exchange"] = df["code"].apply(self._infer_exchange)
            return df
        except Exception as e:
            raise DataSyncError(f"获取股票列表失败: {e}") from e

    @api_retry(max_retries=2, delay=2.0)
    def get_all_etf_dividends(self, years: list = None) -> pd.DataFrame:
        """获取全市场 ETF 分红数据（不按代码过滤，一次调用覆盖所有 ETF）"""
        if years is None:
            from datetime import datetime
            years = [str(y) for y in range(datetime.now().year, datetime.now().year - 5, -1)]
        frames = []
        try:
            import akshare as ak
            for year in years:
                df = ak.fund_fh_em(year=year)
                if not df.empty:
                    frames.append(df)
            if not frames:
                return pd.DataFrame()
            result = pd.concat(frames, ignore_index=True)
            cols = result.columns.tolist()
            # 基金代码在第2列（索引1），名称在第3列（索引2）
            result["stock_code"] = result[cols[1]].astype(str).str.strip()
            result["cash_per_10"] = (pd.to_numeric(result[cols[5]], errors="coerce") * 10).round(2)
            result["announce_date"] = self._safe_date(result[cols[3]])
            result["record_date"] = self._safe_date(result[cols[3]])
            result["ex_dividend_date"] = self._safe_date(result[cols[4]])
            result["bonus_share_date"] = self._safe_date(result[cols[6]])
            result["stock_name"] = result[cols[2]]
            result["progress"] = "实施"
            return result
        except Exception as e:
            raise DataSyncError(f"获取全市场ETF分红失败: {e}") from e

    @api_retry(max_retries=2, delay=2.0)
    def get_etf_dividend(self, stock_code: str, years: list = None) -> pd.DataFrame:
        """获取 ETF 分红数据（通过 fund_fh_em）"""
        if years is None:
            from datetime import datetime
            years = [str(y) for y in range(datetime.now().year, datetime.now().year - 5, -1)]
        frames = []
        try:
            import akshare as ak
            for year in years:
                df = ak.fund_fh_em(year=year)
                mask = df.iloc[:, 1].astype(str).str.strip() == stock_code
                subset = df[mask]
                if not subset.empty:
                    frames.append(subset)
            if not frames:
                return pd.DataFrame()
            result = pd.concat(frames, ignore_index=True)
            cols = result.columns.tolist()
            result["stock_code"] = stock_code
            result["cash_per_10"] = (pd.to_numeric(result[cols[5]], errors="coerce") * 10).round(2)
            result["announce_date"] = self._safe_date(result[cols[3]])
            result["record_date"] = self._safe_date(result[cols[3]])
            result["ex_dividend_date"] = self._safe_date(result[cols[4]])
            result["bonus_share_date"] = self._safe_date(result[cols[6]])
            result["stock_name"] = result[cols[2]]
            result["progress"] = "实施"
            return result
        except Exception as e:
            raise DataSyncError(f"获取ETF {stock_code} 分红失败: {e}") from e

    @staticmethod
    def _safe_date(series):
        return series.astype(str).apply(lambda d: d if d and d != "nan" and d != "NaT" else None)

    @staticmethod
    def _infer_exchange(code: str) -> str:
        """从6位代码推断交易所"""
        code = str(code)
        if code.startswith(("600", "601", "603", "605", "688", "689")):
            return "SH"
        if code.startswith(("000", "001", "002", "003", "300", "301")):
            return "SZ"
        if code.startswith(("920", "830", "831", "832", "833", "834", "835", "836", "837", "838", "839",
                            "870", "871", "872", "873", "874", "875", "400", "420", "430")):
            return "BJ"
        return "SZ"
