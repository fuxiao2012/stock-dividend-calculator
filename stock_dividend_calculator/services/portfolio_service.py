"""持仓管理服务"""
from datetime import datetime
from typing import Optional
from database.engine import DatabaseEngine


class PortfolioService:

    def __init__(self):
        self.db = DatabaseEngine()

    def add_position(self, account_id: int, stock_code: str, quantity: int,
                     stock_name: str = "", cost_price: Optional[float] = None,
                     buy_date: str = "", notes: str = "") -> int:
        cost_total = round(cost_price * quantity, 2) if cost_price else None
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 先确保 stocks 表有记录（FK 约束要求）
        self.db.execute(
            "INSERT OR IGNORE INTO stocks (stock_code, stock_name, exchange) VALUES (?, ?, 'SZ')",
            (stock_code, stock_name or ""),
        )
        cursor = self.db.execute(
            """INSERT INTO positions (account_id, stock_code, stock_name, quantity,
               cost_price, cost_total, buy_date, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (account_id, stock_code, stock_name or "", quantity,
             cost_price, cost_total, buy_date or None, notes, now, now),
        )
        self.db.commit()
        return cursor.lastrowid

    def update_position(self, position_id: int, **kwargs) -> bool:
        if not kwargs:
            return False
        current = self.db.fetch_one("SELECT quantity, cost_price FROM positions WHERE id = ?", (position_id,))
        if not current:
            return False
        new_qty = kwargs.get("quantity", current["quantity"])
        new_cost = kwargs.get("cost_price", current["cost_price"])
        if "quantity" in kwargs or "cost_price" in kwargs:
            kwargs["cost_total"] = round(new_qty * (new_cost or 0), 2)

        fields = []
        values = []
        for key in ("stock_code", "stock_name", "quantity", "cost_price",
                     "cost_total", "buy_date", "sell_date", "notes", "is_active"):
            if key in kwargs:
                fields.append(f"{key} = ?")
                values.append(kwargs[key])
        if not fields:
            return False
        fields.append("updated_at = ?")
        values.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        values.append(position_id)
        self.db.execute(f"UPDATE positions SET {', '.join(fields)} WHERE id = ?", tuple(values))
        self.db.commit()
        return True

    def mark_sold(self, position_id: int, sell_date: str) -> bool:
        return self.update_position(position_id, sell_date=sell_date, is_active=0)

    def delete(self, position_id: int) -> bool:
        cur = self.db.execute("DELETE FROM positions WHERE id = ?", (position_id,))
        self.db.commit()
        return cur.rowcount > 0

    def get(self, position_id: int):
        return self.db.fetch_one("SELECT * FROM positions WHERE id = ?", (position_id,))

    def list_all(self, account_id: Optional[int] = None) -> list:
        if account_id:
            return self.db.fetch_all(
                "SELECT * FROM positions WHERE account_id = ? ORDER BY created_at DESC",
                (account_id,),
            )
        return self.db.fetch_all("SELECT * FROM positions ORDER BY created_at DESC")

    def list_active(self, account_id: Optional[int] = None) -> list:
        if account_id:
            return self.db.fetch_all(
                "SELECT * FROM positions WHERE account_id = ? AND is_active = 1 ORDER BY created_at DESC",
                (account_id,),
            )
        return self.db.fetch_all(
            "SELECT * FROM positions WHERE is_active = 1 ORDER BY created_at DESC"
        )

    def get_summary(self, account_id: Optional[int] = None) -> dict:
        """持仓汇总统计"""
        if account_id:
            row = self.db.fetch_one(
                """SELECT COUNT(*) as total, SUM(quantity * COALESCE(cost_price, 0)) as total_cost
                   FROM positions WHERE account_id = ? AND is_active = 1""",
                (account_id,),
            )
        else:
            row = self.db.fetch_one(
                """SELECT COUNT(*) as total, SUM(quantity * COALESCE(cost_price, 0)) as total_cost
                   FROM positions WHERE is_active = 1"""
            )
        return {"total_positions": row["total"], "total_cost": row["total_cost"] or 0}
