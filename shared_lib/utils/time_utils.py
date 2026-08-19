"""时区/时间工具，所有展示时间均为北京时间，数据库统一存储 UTC。"""
from datetime import datetime, timezone, timedelta


BEIJING_TZ = timezone(timedelta(hours=8))


def beijing_input_to_utc_datetime(value: str | None) -> datetime | None:
    """前端 datetime-local 输入（北京时间，格式 YYYY-MM-DDTHH:MM）转 UTC datetime。"""
    if not value:
        return None
    # datetime-local 值形如 2026-07-28T14:00，无秒和时区
    dt = datetime.fromisoformat(value)
    dt = dt.replace(tzinfo=BEIJING_TZ)
    return dt.astimezone(timezone.utc)


def parse_datetime_to_utc(value: datetime | str | None) -> datetime | None:
    """将 datetime 对象或 ISO 字符串统一解析为 UTC datetime。

    若输入字符串无时区，则按北京时间解析。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=BEIJING_TZ).astimezone(timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        if not value:
            return None
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BEIJING_TZ)
        return dt.astimezone(timezone.utc)
    return None


def format_datetime_beijing(value: datetime | str | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """将数据库 UTC datetime 格式化为北京时间字符串。

    兼容旧数据：若传入的是无时区 naive datetime，按北京时间解释。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        if not value:
            return ""
        dt = datetime.fromisoformat(value)
    else:
        dt = value

    if dt.tzinfo is None:
        # 旧数据：按北京时间解释
        dt = dt.replace(tzinfo=BEIJING_TZ)
    else:
        # 新数据：UTC -> 北京
        dt = dt.astimezone(BEIJING_TZ)
    return dt.strftime(fmt)


def now_beijing() -> datetime:
    """当前北京时间。"""
    return datetime.now(timezone.utc).astimezone(BEIJING_TZ)


def now_utc() -> datetime:
    """当前 UTC 时间。"""
    return datetime.now(timezone.utc)
