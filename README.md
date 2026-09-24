# Multi-Agent 学术文献综述系统

> **输入一个研究方向（可选上传 PDF/TXT/MD），自动检索真实文献、对比方法、识别研究空白，生成带规范引用的文献综述报告。**

基于 LangGraph 的多智能体协作：检索员 → 分析师 → 撰稿人 → 人工审核。检索预算、结构校验与质量门禁由代码（`backend/skills`、`backend/utils/quality.py`）约束，不只靠提示词。

## 核心亮点

- **真实文献强制** — 只收录 Crossref / OpenAlex / EuropePMC / CORE / ArXiv 等检索结果；编造编号从正文删除；参考文献 1..N 重写
- **可选上传文件** — PDF/TXT/MD 抽取正文与文末参考线索并入检索
- **并行学术预搜** — Crossref+OpenAlex 并发；文献足够则压缩 LLM 检索轮次
- **失败终态** — 检索空/质量过低进入 `failed`，不伪装审核
- **质量分** — 前端展示检索/分析/报告分与引用覆盖
- **进行中任务** — 侧栏独立展示 + 1s 秒表；历史与进行中分离
- **手动删除报告** — 历史与报告区可删任务
- **SSE 实时进度** — 工具级进度、阶段 SVG 图标
- **断点恢复** — AsyncSqliteSaver + resume
- **模型白名单** — OpenAI 兼容接口，前端可选
- **约 190+ 测试** — mock 外部 API

## 架构

```text
主题 (+可选上传)
  → init
  → searcher（并行预搜 + LLM 补充；Skill 预算）
  → analyst（JSON 分析 + matplotlib 图表）
  → writer（引用对账 + 质量分）
  → reviewer ─┬→ END（通过 / failed / 超返工上限）
              └→ writer（返工）
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 编排 | LangGraph + LangChain |
| 学术检索 | Crossref / OpenAlex / EuropePMC / CORE / ArXiv |
| 补充 | Tavily（可选）、DuckDuckGo、SearXNG（自建可选） |
| LLM | OpenAI 兼容 API |
| 后端 | FastAPI + SSE |
| 前端 | Streamlit |
| 图表 | matplotlib |
| RAG | ChromaDB |
| 持久化 | AsyncSqliteSaver |
| 上传解析 | PyMuPDF |

## 功能要点

### 文献真实性

- 多篇检索结果按条目拆分；禁止用 query 冒充标题  
- 上传材料只作分析上下文，不进可引用列表  
- 质量分含引用覆盖与标题关键词错配启发  

### Skill 与质量

- `backend/skills`：LIT_SEARCH 工具预算、ANALYSIS/REPORT 校验、主题模板  
- 检索文献过少 → failed；报告结构/覆盖过低 → 自动重写一次  

### 上传文件（可选）

```bash
curl -X POST http://localhost:8000/api/uploads/research-docs -F "files=@paper.pdf"
```

提交时带 `upload_batch_id` 即可；不上传仍可只用主题研究。

## 快速开始

### 本地

```bash
python -m venv venv
# Windows: venv\Scripts\activate
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn backend.main:app --reload --port 8000
streamlit run frontend/app.py
python -m pytest tests/ -v
```

### 服务器

```bash
sudo bash deploy/install.sh
# 慢网： PIP_MIRROR=1 sudo bash deploy/install.sh
systemctl status learn-agent-api learn-agent-web
```

前端默认 `80`，API `8000`（内网）。

### 远程部署

```powershell
$env:DEPLOY_HOST='服务器IP'; $env:DEPLOY_PW='密码'; python deploy/remote_deploy.py
```

## API 摘要

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/research` | topic, model_name?, upload_batch_id? |
| GET | `/api/research/{id}/stream` | SSE 进度 |
| GET | `/api/research/{id}/report` | 报告 + references/charts/quality_metrics |
| POST | `/api/research/{id}/review` | 审核（通过/修改意见） |
| POST | `/api/research/{id}/resume` | 断点复活 |
| DELETE | `/api/research/{id}` | 删除任务 |
| GET | `/api/research/history` | 历史 |
| GET | `/api/research/running` | 进行中（含 started_at） |
| POST | `/api/uploads/research-docs` | 上传文献 |
| GET | `/api/dependencies` | 依赖状态 |
| GET | `/api/models` | 模型白名单 |
| POST | `/api/admin/config` | 在线配置（口令） |
| GET | `/api/health` | 健康检查 |

## 项目结构

```text
learn_agent/
├── backend/
│   ├── agents/     searcher / analyst / writer / supervisor
│   ├── api/        routes / schemas
│   ├── graph/      state / builder / checkpointer
│   ├── skills/     LIT_SEARCH / ANALYSIS / REPORT + 模板
│   ├── tools/      arxiv / lit_sources / visualization / rag / search
│   └── utils/      citations / quality / upload_docs / progress
├── frontend/
│   ├── app.py             入口：页面配置 + main 流程组装
│   ├── api_client.py      后端 HTTP 调用 + SSE 消费
│   ├── session.py         session_state / 任务恢复 / 终态切换
│   ├── stream.py          SSE 分片轮询（process_stream）
│   ├── sidebar.py         侧边栏（说明 / 依赖 / 历史 / 系统设置）
│   ├── views.py           主区视图（输入 / 进度 / 报告 / 审核）
│   ├── theme.py           主题 / CSS / SVG 图标 / 秒表
│   └── markdown_render.py 内嵌报告渲染（锚点 + 目录）
├── requirements.txt
├── .env.example
└── pytest.ini
```

## License

MIT
