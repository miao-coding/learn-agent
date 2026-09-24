"""后端 API 客户端：全部 HTTP 调用 + SSE 流消费（分片轮询的传输层）"""
import json
import time

import requests
import streamlit as st

# ============ 常量 ============
API_BASE_URL = "http://localhost:8000"


@st.cache_data(ttl=15)
def check_health() -> bool:
    """检查后端连接"""
    try:
        resp = requests.get(f"{API_BASE_URL}/api/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


@st.cache_data(ttl=30)
def fetch_available_models() -> dict | None:
    """获取后端可用模型列表（未配置白名单时返回 None，前端隐藏选择框）"""
    try:
        resp = requests.get(f"{API_BASE_URL}/api/models", timeout=5)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


@st.cache_data(ttl=15)
def get_admin_status() -> dict | None:
    """获取后端配置状态（在线配置是否启用、Key 是否已配置，不含密钥明文）"""
    try:
        resp = requests.get(f"{API_BASE_URL}/api/admin/status", timeout=5)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def update_admin_config(payload: dict) -> dict | None:
    """提交管理员配置（口令保护，成功后即时生效并持久化到服务器 .env）"""
    try:
        resp = requests.post(f"{API_BASE_URL}/api/admin/config", json=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def admin_list_models(payload: dict) -> dict | None:
    """获取 OpenAI 兼容接口的可用模型列表（口令保护）"""
    try:
        resp = requests.post(f"{API_BASE_URL}/api/admin/list-models", json=payload, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def admin_test_model(payload: dict) -> dict | None:
    """测试模型连通性（真实发送一次最小调用，口令保护）"""
    try:
        resp = requests.post(f"{API_BASE_URL}/api/admin/test-model", json=payload, timeout=40)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def fetch_history(limit: int = 15) -> list:
    """获取历史任务列表（服务端 checkpoints.db 持久化，刷新/退出不丢失）"""
    try:
        resp = requests.get(
            f"{API_BASE_URL}/api/research/history", params={"limit": limit}, timeout=10
        )
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception:
        return []


def fetch_running_tasks() -> list:
    """当前进程内仍在执行的任务"""
    try:
        resp = requests.get(f"{API_BASE_URL}/api/research/running", timeout=8)
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception:
        return []


def delete_history(thread_id: str) -> bool:
    """删除指定历史研究报告（服务端清 checkpoints 持久化数据）"""
    try:
        resp = requests.delete(
            f"{API_BASE_URL}/api/research/{thread_id}", timeout=15
        )
        return resp.status_code == 200 and resp.json().get("deleted", False)
    except Exception:
        return False


@st.cache_data(ttl=30)
def fetch_dependencies() -> dict | None:
    """获取后端外部依赖健康状态（含 SearXNG 探活，轮询周期下需缓存）"""
    try:
        resp = requests.get(f"{API_BASE_URL}/api/dependencies", timeout=8)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def submit_research(topic: str, model_name: str = "", upload_batch_id: str = "") -> dict | None:
    """提交研究任务（upload_batch_id 可选）"""
    try:
        payload = {"topic": topic, "model_name": model_name}
        if upload_batch_id:
            payload["upload_batch_id"] = upload_batch_id
        resp = requests.post(
            f"{API_BASE_URL}/api/research",
            json=payload,
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        try:
            st.session_state["_last_submit_err"] = resp.json().get("detail", "")
        except Exception:
            st.session_state["_last_submit_err"] = resp.text[:200]
        return None
    except Exception as e:
        st.session_state["_last_submit_err"] = str(e)
        return None


def upload_research_docs(uploaded_files: list) -> dict | None:
    """上传 PDF/TXT/MD 文献，返回 {batch_id, files}"""
    if not uploaded_files:
        return None
    files = []
    for f in uploaded_files:
        name = getattr(f, "name", "doc.pdf")
        data = f.getvalue() if hasattr(f, "getvalue") else f.read()
        files.append(("files", (name, data, "application/octet-stream")))
    try:
        resp = requests.post(f"{API_BASE_URL}/api/uploads/research-docs", files=files, timeout=120)
        if resp.status_code == 200:
            return resp.json()
        try:
            st.session_state["_last_upload_err"] = resp.json().get("detail", "")
        except Exception:
            st.session_state["_last_upload_err"] = resp.text[:200]
        return None
    except Exception as e:
        st.session_state["_last_upload_err"] = str(e)
        return None


def submit_review(thread_id: str, feedback: str, action: str = "") -> dict | None:
    """提交审核（action: approve/revise，显式传意图；空则后端按旧文本规则兼容）"""
    try:
        payload = {"feedback": feedback}
        if action:
            payload["action"] = action
        resp = requests.post(
            f"{API_BASE_URL}/api/research/{thread_id}/review",
            json=payload,
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = (resp.text or "")[:160]
        return {"status": "error", "message": detail or f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_report(thread_id: str) -> dict | None:
    """获取最终报告"""
    try:
        resp = requests.get(
            f"{API_BASE_URL}/api/research/{thread_id}/report",
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def fetch_task_progress(thread_id: str) -> dict | None:
    """拉取服务端进度历史 + started_at（刷新/重连补齐日志）"""
    try:
        resp = requests.get(
            f"{API_BASE_URL}/api/research/{thread_id}/progress",
            params={"limit": 50},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def _probe_task_status(thread_id: str) -> str:
    """回查任务的持久化状态（SSE 队列消失时判断任务是否其实已结束）"""
    for h in fetch_history(50):
        if h.get("thread_id") == thread_id:
            return str(h.get("status") or "")
    return ""


def consume_sse_sync(thread_id: str, max_retries: int = 3, retry_delay: float = 1.0, since: int = 0):
    """同步消费 SSE 流式事件

    Args:
        thread_id: 任务线程 ID
        max_retries: 连接失败时的最大重试次数（用于返工场景下后端队列尚未就绪的情况）
        retry_delay: 每次重试之间的等待秒数
        since: 只接收该序号之后的事件（服务端事件日志重放锚点，防止重复）
    """
    url = f"{API_BASE_URL}/api/research/{thread_id}/stream?since={int(since)}"

    for attempt in range(max_retries + 1):
        try:
            with requests.get(url, stream=True, timeout=None) as response:
                if response.status_code == 404:
                    # 队列不存在（服务重启丢队列 / 任务刚结束被摘除）→
                    # 先尝试从 checkpoint 断点复活任务，再重连
                    resumed = False
                    if attempt == 0:
                        try:
                            r = requests.post(
                                f"{API_BASE_URL}/api/research/{thread_id}/resume", timeout=30
                            )
                            resumed = r.status_code == 200 and r.json().get("status") == "resumed"
                        except Exception:
                            resumed = False
                        if resumed:
                            time.sleep(2)
                    if not resumed:
                        # 无法复活：任务可能恰好已结束（reviewing/completed/failed），
                        # 回查真实状态并转入结果展示，而不是误报错误
                        real_status = _probe_task_status(thread_id)
                        if real_status in ("reviewing", "completed", "failed"):
                            yield "task_finished", {"status": real_status}
                            return
                    if attempt < max_retries:
                        time.sleep(retry_delay)
                        continue
                    yield "error", {"message": "任务未找到，可能已完成或过期"}
                    return

                event_type = None
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        event_type = None
                        continue
                    # SSE 心跳注释 → 转为心跳事件（驱动前端刷新运行计时）
                    if line.startswith(":"):
                        yield "heartbeat", {}
                        continue
                    if line.startswith("event: "):
                        event_type = line[7:].strip()
                    elif line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                        except json.JSONDecodeError:
                            data = {"raw": line[6:]}
                        yield event_type, data
                    elif line.startswith("data:"):
                        # 兼容无空格的情况
                        try:
                            data = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            data = {"raw": line[5:].strip()}
                        yield event_type, data
            # 正常结束（连接关闭），不再重试
            return

        except requests.exceptions.ConnectionError:
            if attempt < max_retries:
                time.sleep(retry_delay)
                continue
            yield "error", {"message": "无法连接到后端服务，请确认后端已启动"}
            return
        except Exception as e:
            yield "error", {"message": f"SSE 流异常中断: {str(e)}"}
            return
