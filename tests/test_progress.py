"""进度事件总线测试"""
import asyncio

from backend.utils import progress


def test_register_and_report():
    """注册后 report_progress 能把消息路由到对应队列"""
    queue = asyncio.Queue()
    progress.register("t1", queue)
    try:
        asyncio.run(
            progress.report_progress(
                {"configurable": {"thread_id": "t1"}}, "调用 arxiv_search"
            )
        )
        assert queue.qsize() == 1
        event = queue.get_nowait()
        assert event["event"] == "progress"
        assert event["data"]["message"] == "调用 arxiv_search"
    finally:
        progress.unregister("t1")
    assert "t1" not in progress._queues


def test_report_without_registration_is_noop():
    """未注册的任务推送被静默忽略"""
    asyncio.run(
        progress.report_progress({"configurable": {"thread_id": "nobody"}}, "msg")
    )


def test_report_with_none_config_is_noop():
    """config 为 None（如直接调用节点函数）时静默忽略"""
    asyncio.run(progress.report_progress(None, "msg"))


def test_unregister_is_idempotent():
    """重复注销不报错"""
    progress.unregister("never-registered")
