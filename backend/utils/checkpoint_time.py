"""UUIDv6 checkpoint_id → 可读时间（P2 历史时间显示）"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Gregorian 1582-10-15 00:00:00 UTC → Unix epoch 的秒偏移
_UUID_EPOCH_OFFSET_SEC = 12219292800


def uuid6_to_datetime(value: str) -> datetime | None:
    """将 langgraph checkpoint 的 UUIDv6 转为 UTC datetime；失败返回 None"""
    try:
        h = value.replace("-", "").lower()
        if len(h) != 32:
            return None
        version = int(h[12], 16)
        if version not in (6, 7):
            # UUIDv1 也常见于部分版本：尝试按 v1 时间字段
            if version == 1:
                return _uuid1_to_datetime(h)
            return None
        if version == 7:
            # UUIDv7: 48-bit unix ms
            ms = int(h[:12], 16)
            return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        # UUIDv6: 48-bit time_high + version nibble + 12-bit time_low
        high48 = int(h[:12], 16)
        low12 = int(h[13:16], 16)
        ts60 = (high48 << 12) | low12
        unix = ts60 / 1e7 - _UUID_EPOCH_OFFSET_SEC
        return datetime.fromtimestamp(unix, tz=timezone.utc)
    except Exception:
        return None


def _uuid1_to_datetime(h: str) -> datetime | None:
    try:
        time_low = int(h[0:8], 16)
        time_mid = int(h[8:12], 16)
        time_hi = int(h[13:16], 16) & 0x0FFF
        ts60 = (time_hi << 48) | (time_mid << 32) | time_low
        unix = ts60 / 1e7 - _UUID_EPOCH_OFFSET_SEC
        return datetime.fromtimestamp(unix, tz=timezone.utc)
    except Exception:
        return None


def format_checkpoint_time(value: str) -> str:
    """返回本地可读时间字符串；无法解析时回退截断原值"""
    dt = uuid6_to_datetime(value)
    if not dt:
        return (value or "")[:19]
    local = dt.astimezone()
    return local.strftime("%m-%d %H:%M")
