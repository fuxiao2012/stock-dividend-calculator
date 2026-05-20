"""导入导出服务 — CSV/Excel"""
from datetime import datetime
from pathlib import Path
from typing import Optional
import pandas as pd
from database.engine import DatabaseEngine
from config import EXPORT_DIR
from utils.exceptions import ImportError2, ValidationError


REQUIRED_COLS = {"证券代码", "持仓数量"}
OPTIONAL_COLS = {"证券名称", "买入成本", "买入日期", "备注"}
# 兼容旧版列名
COL_ALIASES = {
    "股票代码": "证券代码", "持有数量": "持仓数量",
    "股票名称": "证券名称",
}
ALL_COLS = REQUIRED_COLS | OPTIONAL_COLS


class ImportExportService:

    def __init__(self):
        self.db = DatabaseEngine()

    def import_positions(self, file_path: str, account_id: int, update_mode: bool = False) -> dict:
        """导入持仓文件到指定账户

        Args:
            update_mode: True=以股票代码为主键更新已有持仓，False=始终新增
        """
        path = Path(file_path)
        if not path.exists():
            raise ImportError2(f"文件不存在: {file_path}")

        suffix = path.suffix.lower()
        df = None

        def _try_read_csv(fpath):
            for enc in ("utf-8", "gbk", "gb2312", "gb18030", "utf-8-sig"):
                try:
                    return pd.read_csv(fpath, dtype={"证券代码": str}, encoding=enc)
                except (UnicodeDecodeError, UnicodeError):
                    continue
            return pd.read_csv(fpath, dtype={"证券代码": str}, encoding="utf-8", errors="replace")

        try:
            if suffix == ".csv":
                df = _try_read_csv(file_path)
            elif suffix in (".xlsx", ".xls"):
                try:
                    engine = "openpyxl" if suffix == ".xlsx" else "xlrd"
                    df = pd.read_excel(file_path, dtype={"证券代码": str}, engine=engine)
                except Exception:
                    df = _try_read_csv(file_path)
            else:
                raise ImportError2(f"不支持的文件格式: {suffix}")
        except Exception as e:
            raise ImportError2(f"文件读取失败: {e}")

        # 兼容旧版列名
        df = df.rename(columns=COL_ALIASES)
        missing = REQUIRED_COLS - set(df.columns)
        if missing:
            raise ValidationError(f"缺少必要列: {', '.join(missing)}")

        imported = 0
        updated = 0
        errors = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for i, row in df.iterrows():
            try:
                code = str(row["证券代码"]).strip()
                qty = int(row["持仓数量"])
                if qty <= 0:
                    raise ValidationError("持仓数量必须大于0")
                name_raw = row.get("证券名称", "")
                name = str(name_raw).strip() if "证券名称" in df.columns and pd.notna(name_raw) else ""
                cost = float(row["买入成本"]) if "买入成本" in df.columns and pd.notna(row.get("买入成本")) else None
                buy_date = str(row.get("买入日期", "")).strip() if "买入日期" in df.columns else ""
                notes = str(row.get("备注", "")).strip() if "备注" in df.columns else ""

                self.db.execute(
                    "INSERT OR IGNORE INTO stocks (stock_code, stock_name, exchange) VALUES (?, ?, 'SZ')",
                    (code, name or ""),
                )

                if update_mode:
                    existing = self.db.fetch_one(
                        "SELECT id FROM positions WHERE account_id = ? AND stock_code = ? AND is_active = 1",
                        (account_id, code),
                    )
                    if existing:
                        self.db.execute(
                            """UPDATE positions SET stock_name=?, quantity=?, cost_price=?,
                               cost_total=?, buy_date=?, notes=?, updated_at=?
                               WHERE id=?""",
                            (name, qty, cost, round(cost * qty, 2) if cost else None,
                             buy_date or None, notes, now, existing["id"]),
                        )
                        updated += 1
                        continue

                self.db.execute(
                    """INSERT INTO positions (account_id, stock_code, stock_name, quantity,
                       cost_price, cost_total, buy_date, notes, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (account_id, code, name, qty, cost,
                     round(cost * qty, 2) if cost else None,
                     buy_date or None, notes, now, now),
                )
                imported += 1
            except Exception as e:
                errors.append(f"第{i+2}行: {e}")

        self.db.commit()
        self._log_import_export("导入", path.name, suffix.replace(".", ""), imported + updated)

        msg_parts = [f"新增 {imported} 条"]
        if updated:
            msg_parts.append(f"更新 {updated} 条")
        return {
            "success": len(errors) == 0,
            "total": len(df),
            "imported": imported,
            "updated": updated,
            "errors": errors,
            "message": "，".join(msg_parts),
        }

    def export_positions(self, account_id: Optional[int] = None, fmt: str = "csv") -> str:
        """导出持仓到文件"""
        if account_id:
            rows = self.db.fetch_all(
                "SELECT stock_code, stock_name, quantity, cost_price, buy_date, notes "
                "FROM positions WHERE account_id = ? AND is_active = 1 ORDER BY stock_code",
                (account_id,),
            )
        else:
            rows = self.db.fetch_all(
                "SELECT stock_code, stock_name, quantity, cost_price, buy_date, notes "
                "FROM positions WHERE is_active = 1 ORDER BY stock_code"
            )

        df = pd.DataFrame(rows, columns=["证券代码", "证券名称", "持仓数量", "买入成本", "买入日期", "备注"])
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"positions_{timestamp}.{fmt}"
        filepath = EXPORT_DIR / filename

        if fmt == "csv":
            df.to_csv(filepath, index=False, encoding="utf-8-sig")
        else:
            df.to_excel(filepath, index=False, sheet_name="持仓列表")

        self._log_import_export("导出", filename, fmt, len(df))
        return str(filepath)

    def export_dividend_report(self, year: int, account_id: Optional[int] = None, fmt: str = "xlsx") -> str:
        """导出分红报告"""
        if account_id:
            rows = self.db.fetch_all(
                """SELECT stock_code, stock_name, record_date, cash_per_share,
                   hold_quantity, gross_dividend, tax_rate, tax_amount, net_dividend
                   FROM dividend_calculations
                   WHERE account_id = ? AND strftime('%Y', record_date) = ? AND is_eligible = 1
                   ORDER BY record_date""",
                (account_id, str(year)),
            )
        else:
            rows = self.db.fetch_all(
                """SELECT stock_code, stock_name, record_date, cash_per_share,
                   hold_quantity, gross_dividend, tax_rate, tax_amount, net_dividend
                   FROM dividend_calculations
                   WHERE strftime('%Y', record_date) = ? AND is_eligible = 1
                   ORDER BY record_date""",
                (str(year),),
            )

        df = pd.DataFrame(rows, columns=[
            "证券代码", "证券名称", "股权登记日", "每股派息", "持仓数量",
            "税前分红", "税率", "税额", "税后分红"
        ])

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"dividend_report_{year}_{timestamp}.{fmt}"
        filepath = EXPORT_DIR / filename

        if fmt == "xlsx":
            with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="分红明细")

                summary = df.groupby("证券代码").agg(
                    证券名称=("证券名称", "first"),
                    税前分红合计=("税前分红", "sum"),
                    税后分红合计=("税后分红", "sum"),
                ).reset_index()
                summary.to_excel(writer, index=False, sheet_name="按股票汇总")
        else:
            df.to_csv(filepath, index=False, encoding="utf-8-sig")

        self._log_import_export("导出", filename, fmt, len(df))
        return str(filepath)

    def _log_import_export(self, op_type: str, file_name: str, file_format: str, record_count: int):
        self.db.execute(
            """INSERT INTO import_export_log (op_type, file_name, file_format, record_count)
               VALUES (?, ?, ?, ?)""",
            (op_type, file_name, file_format, record_count),
        )
        self.db.commit()
