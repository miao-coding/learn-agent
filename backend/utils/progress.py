"""Agent 进度事件总线 — SSE 事件发布/订阅 + 断线重放

- publish()：任务事件写入有界事件日志（ring buffer）并扇出给所有订阅者
  （token 流量大、只进实时队列不进日志，保证日志能覆盖较长历史）
- subscribe()/unsubscribe()：每个 SSE 连接独立队列，多标签页互不抢事件
- report_progress()：Agent 节点内推送细粒度进度（走同一发布通道）

重连协议：事件带自增序号；客户端先 GET /progress 拿 upto_seq，
再带 ?since=upto_seq 连 /stream，服务端只重放 since 之后的事件，
保证不重不漏（先前靠队列积压重放，仅支持单消费者且断连期间无界增长）。
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque

logger = logging.getLogger(__name__)

# thread_id → 事件日志（有界，元素为 (seq, event_dict)）
_logs: dict[str, deque] = {}
_LOG_MAX = 400

# 高频事件不进日志，仅实时扇出（重连可从 /progress 补日志，token 只用于实时字数）
_LOG_SKIP_EVENTS = {"token"}

# thread_id → 事件序号计数
_seq: dict[str, int] = {}

# thread_id → SSE 订阅者队列集合
_subscribers: dict[str, set[asyncio.Queue]] = {}

# 单个订阅者队列上限：慢消费者丢最旧保最新（重连可从日志补齐）
_SUB_QUEUE_MAX = 1000


def _log(thread_id: str) -> deque:
    buf = _logs.get(thread_id)
    if buf is None:
        buf = deque(maxlen=_LOG_MAX)
        _logs[thread_id] = buf
    return buf


def publish(thread_id: str, event: dict) -> int:
    """发布事件：写入有界日志并扇出到所有 SSE 订阅者，返回事件序号"""
    seq = _seq.get(thread_id, 0) + 1
    _seq[thread_id] = seq
    if event.get("event") not in _LOG_SKIP_EVENTS:
        _log(thread_id).append((seq, event))
    for q in list(_subscribers.get(thread_id) or ()):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # 慢消费者：丢最旧事件保最新
            try:
                q.get_nowait()
                q.put_nowait(event)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass
    return seq


def subscribe(thread_id: str, since: int = 0) -> tuple[asyncio.Queue, list[dict]]:
    """新建 SSE 订阅：返回 (队列, 需重放的历史事件)

    先记下当前序号再注册队列，重放窗口为 (since, seq_before]，
    注册后到达的事件只走队列 — 两段衔接不重不漏。
    """
    seq_before = _seq.get(thread_id, 0)
    q: asyncio.Queue = asyncio.Queue(maxsize=_SUB_QUEUE_MAX)
    _subscribers.setdefault(thread_id, set()).add(q)
    replay = [ev for seq, ev in _log(thread_id) if since < seq <= seq_before]
    return q, replay


def unsubscribe(thread_id: str, q: asyncio.Queue) -> None:
    """SSE 连接断开时摘除订阅者（幂等）"""
    subs = _subscribers.get(thread_id)
    if subs is not None:
        subs.discard(q)
        if not subs:
            _subscribers.pop(thread_id, None)


def current_seq(thread_id: str) -> int:
    """当前最新事件序号（供 /progress 返回 upto_seq）"""
    return _seq.get(thread_id, 0)


def replay_events(thread_id: str, since: int = 0) -> list[dict]:
    """读取 since 之后的事件（不含 token）"""
    return [ev for seq, ev in _log(thread_id) if seq > since]


def has_terminal_event(thread_id: str) -> bool:
    """事件日志中是否已有 done 终止事件（判断刚结束的任务能否仅靠重放收尾）"""
    return any(ev.get("event") == "done" for _, ev in _log(thread_id))


def get_progress_snapshot(thread_id: str, limit: int = 50) -> tuple[list[str], int]:
    """读取进度消息历史与最新事件序号（刷新/重连补日志 + since 锚点）"""
    msgs = [
        str((ev.get("data") or {}).get("message", ""))
        for _, ev in _log(thread_id)
        if ev.get("event") == "progress"
    ]
    upto = _seq.get(thread_id, 0)
    if not msgs:
        return [], upto
    n = max(1, min(limit, _LOG_MAX))
    return msgs[-n:], upto


def clear_progress(thread_id: str) -> None:
    """删除任务时清掉日志、序号与订阅"""
    _logs.pop(thread_id, None)
    _seq.pop(thread_id, None)
    _subscribers.pop(thread_id, None)


async def report_progress(config: dict | None, message: str) -> None:
    """Agent 节点内推送进度消息到前端（失败静默，不影响主流程）"""
    try:
        if not config:
            return
        thread_id = (config.get("configurable") or {}).get("thread_id")
        if not thread_id:
            return
        publish(thread_id, {"event": "progress", "data": {"message": message}})
    except Exception:
        logger.debug("report_progress 失败（忽略）", exc_info=True)
