#!/usr/bin/env bash
# ============================================================
# Multi-Agent 智能行业研究系统 - Linux 一键部署脚本
#
# 用法：将整个项目上传到服务器后，在项目根目录执行：
#       sudo bash deploy/install.sh
#
# 适用：Debian / Ubuntu（其他发行版请自行替换 apt 部分）
# 可选：国内服务器网络慢时启用清华 pip 镜像：
#       PIP_MIRROR=1 sudo bash deploy/install.sh
#
# 服务说明：
#   learn-agent-api  : FastAPI + LangGraph 后端（端口 8000，内存限额 700M）
#   learn-agent-web  : Streamlit 前端     （端口 8501，内存限额 400M）
#
# 卸载：
#   systemctl disable --now learn-agent-api learn-agent-web
#   rm /etc/systemd/system/learn-agent-*.service && systemctl daemon-reload
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${SUDO_USER:-$(whoami)}"
RUN_USER_HOME="$(getent passwd "${RUN_USER}" | cut -d: -f6)"
API_PORT="${API_PORT:-8000}"
# 对外仅暴露 80（前端）；浏览器不直连后端，API 仅服务器内网监听，更安全
WEB_PORT="${WEB_PORT:-80}"

echo "==> 项目目录: ${PROJECT_DIR}"
echo "==> 运行用户: ${RUN_USER} (${RUN_USER_HOME})"

# ── [1/5] 系统依赖 + 中文字体（解决图表中文乱码）──────────────
echo "==> [1/5] 安装系统依赖与中文字体..."
if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y python3 python3-venv python3-pip fonts-wqy-zenhei fontconfig
    fc-cache -f >/dev/null
else
    echo "!! 未检测到 apt-get。请手动安装 python3-venv 与中文字体(如 wqy-zenhei)后重跑本脚本。"
    exit 1
fi

# ── [2/5] Python 虚拟环境 + 项目依赖（磁盘占用约 1.5~2.5G）────
echo "==> [2/5] 创建虚拟环境并安装 Python 依赖（需几分钟）..."
cd "${PROJECT_DIR}"
python3 -m venv venv
PIP_EXTRA_ARGS=()
if [ "${PIP_MIRROR:-0}" = "1" ]; then
    PIP_EXTRA_ARGS+=("-i" "https://pypi.tuna.tsinghua.edu.cn/simple")
fi
./venv/bin/pip install --upgrade pip "${PIP_EXTRA_ARGS[@]}" -q
./venv/bin/pip install -r requirements.txt "${PIP_EXTRA_ARGS[@]}" -q

# 新装字体需重建 matplotlib 字体缓存，否则中文仍显示方块
rm -rf "${RUN_USER_HOME}/.cache/matplotlib"

# ── [3/5] 环境变量配置 ────────────────────────────────────────
echo "==> [3/5] 准备 .env ..."
# 若覆盖旧部署：清理旧字节码缓存（tar 保留旧 mtime，可能使 __pycache__ 失效判定失准而执行旧代码）
find "${PROJECT_DIR}/backend" "${PROJECT_DIR}/frontend" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
if [ ! -f .env ]; then
    cp .env.example .env
    echo "!! 已生成 ${PROJECT_DIR}/.env —— 部署完成后请编辑填入 OPENAI_API_KEY 和 TAVILY_API_KEY"
else
    echo "   已存在 .env，跳过。"
fi

# ── [4/5] 生成 systemd 服务（内存软/硬限额防拖垮整机，swap 兜底）──
echo "==> [4/5] 写入 systemd 服务..."

cat > /etc/systemd/system/learn-agent-api.service <<EOF
[Unit]
Description=Learn Agent - FastAPI + LangGraph API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${PROJECT_DIR}
Environment="PYTHONUNBUFFERED=1"
Environment="MPLBACKEND=Agg"
ExecStart=${PROJECT_DIR}/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port ${API_PORT} --workers 1
Restart=always
RestartSec=5
# 内存保护：软限 600M / 硬限 700M（RAG+绘图峰值场景，超出部分由系统回收）
MemoryHigh=600M
MemoryMax=700M

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/learn-agent-web.service <<EOF
[Unit]
Description=Learn Agent - Streamlit Web
After=network-online.target learn-agent-api.service
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${PROJECT_DIR}
Environment="PYTHONUNBUFFERED=1"
Environment="HOME=${RUN_USER_HOME}"
ExecStart=${PROJECT_DIR}/venv/bin/streamlit run frontend/app.py --server.headless true --server.address 0.0.0.0 --server.port ${WEB_PORT}
Restart=always
RestartSec=5
MemoryHigh=350M
MemoryMax=400M

[Install]
WantedBy=multi-user.target
EOF

# ── [5/5] 启动并自检 ─────────────────────────────────────────
echo "==> [5/5] 启动服务..."
systemctl daemon-reload
systemctl enable learn-agent-api.service learn-agent-web.service
# 注意：不能用 enable --now（对已运行的服务是 no-op，重复部署时不会加载新代码）
systemctl restart learn-agent-api.service learn-agent-web.service

sleep 3
for svc in learn-agent-api learn-agent-web; do
    if systemctl is-active --quiet "${svc}"; then
        echo "   [OK] ${svc} 运行中"
    else
        echo "   [失败] ${svc} 未启动，查看日志: journalctl -u ${svc} -n 50"
    fi
done

echo ""
echo "============================================================"
echo " 部署完成！"
echo "   后端 API : http://<服务器IP>:${API_PORT}/docs"
echo "   前端界面 : http://<服务器IP>:${WEB_PORT}"
echo ""
echo " 后续步骤："
echo "   1. 编辑 ${PROJECT_DIR}/.env 填入 OPENAI_API_KEY / TAVILY_API_KEY"
echo "      （使用兼容接口时同时配置 OPENAI_BASE_URL）"
echo "   2. systemctl restart learn-agent-api learn-agent-web"
echo ""
echo " 常用命令："
echo "   journalctl -u learn-agent-api -f     # 后端实时日志"
echo "   free -h                              # 观察内存/swap 占用"
echo ""
echo " 提示：ChromaDB 首次执行 RAG 检索时会下载约 80MB 的"
echo "       ONNX embedding 模型到 ${RUN_USER_HOME}/.cache/chroma/，"
echo "       请确保服务器可访问外网。"
echo "============================================================"
