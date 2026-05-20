"""API 重试装饰器，带指数退避和降级"""
import time
import functools
import logging
from typing import Tuple, Type
import pandas as pd

logger = logging.getLogger(__name__)


def api_retry(
    max_retries: int = 3,
    delay: float = 2.0,
    retry_on: Tuple[Type[Exception], ...] = (Exception,),
    degrade_value=None,
):
    """API 调用失败时重试，最终降级返回空 DataFrame"""
    if degrade_value is None:
        degrade_value = pd.DataFrame()

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retry_on as e:
                    last_exc = e
                    if attempt < max_retries:
                        wait = delay * (2 ** attempt)
                        logger.warning(
                            "%s 第 %d/%d 次失败: %s, %.1fs 后重试",
                            func.__name__, attempt + 1, max_retries, e, wait,
                        )
                        time.sleep(wait)
            logger.error("%s 重试 %d 次后降级: %s", func.__name__, max_retries, last_exc)
            return degrade_value
        return wrapper
    return decorator
