"""数据库引擎 — Streamlit 感知的连接管理"""
import sqlite3
import streamlit as st
from config import DB_PATH


class DatabaseEngine:
    """封装 SQLite 操作，提供 Streamlit 级缓存连接"""

    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path

    @staticmethod
    @st.cache_resource
    def get_connection() -> sqlite3.Connection:
        """Streamlit 缓存的连接（跨 rerun 复用）"""
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA cache_size=-8000;")
        return conn

    @staticmethod
    def execute(query: str, params: tuple = ()) -> sqlite3.Cursor:
        conn = DatabaseEngine.get_connection()
        return conn.execute(query, params)

    @staticmethod
    def execute_many(query: str, params_list: list):
        conn = DatabaseEngine.get_connection()
        conn.executemany(query, params_list)
        conn.commit()

    @staticmethod
    def fetch_one(query: str, params: tuple = ()):
        return DatabaseEngine.execute(query, params).fetchone()

    @staticmethod
    def fetch_all(query: str, params: tuple = ()):
        return DatabaseEngine.execute(query, params).fetchall()

    @staticmethod
    def commit():
        DatabaseEngine.get_connection().commit()
