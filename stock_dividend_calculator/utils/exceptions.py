"""自定义异常"""


class AppError(Exception):
    """应用基础异常"""


class DataSyncError(AppError):
    """数据同步失败"""


class ValidationError(AppError):
    """数据校验失败"""


class ImportError2(AppError):
    """导入失败（避免与内置 ImportError 冲突）"""
