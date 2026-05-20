"""账户管理服务"""
from datetime import datetime
from typing import Optional
from database.engine import DatabaseEngine


class AccountService:

    def __init__(self):
        self.db = DatabaseEngine()

    def create(self, account_name: str, account_type: str = "普通账户",
               broker: str = "", notes: str = "") -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = self.db.execute(
            """INSERT INTO accounts (account_name, account_type, broker, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (account_name, account_type, broker, notes, now, now),
        )
        self.db.commit()
        return cursor.lastrowid

    def update(self, account_id: int, **kwargs) -> bool:
        if not kwargs:
            return False
        fields = []
        values = []
        for key in ("account_name", "account_type", "broker", "notes", "is_active"):
            if key in kwargs:
                fields.append(f"{key} = ?")
                values.append(kwargs[key])
        if not fields:
            return False
        fields.append("updated_at = ?")
        values.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        values.append(account_id)
        self.db.execute(f"UPDATE accounts SET {', '.join(fields)} WHERE id = ?", tuple(values))
        self.db.commit()
        return True

    def delete(self, account_id: int) -> bool:
        self.db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        self.db.commit()
        return True

    def get(self, account_id: int):
        return self.db.fetch_one("SELECT * FROM accounts WHERE id = ?", (account_id,))

    def list_all(self) -> list:
        return self.db.fetch_all("SELECT * FROM accounts ORDER BY created_at DESC")

    def list_active(self) -> list:
        return self.db.fetch_all(
            "SELECT * FROM accounts WHERE is_active = 1 ORDER BY created_at DESC"
        )
