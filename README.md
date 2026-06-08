# SuperBizAgent

> 企业级智能业务代理系统 — 客服多Agent + 退货审核 + AIOps 智能运维

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-latest-orange.svg)](https://langchain-ai.github.io/langgraph/)

## ✨ 核心特性

| 模块 | 架构 | 说明 |
|------|------|------|
| 🛒 **客服 Agent** | SupervisorAgent + 4 子Agent | 售前/售后/升级/闲聊 自动路由 |
| 📋 **退货审核 Agent** | 单 ReactAgent + 7 工具 | 自动审核退货申请、品类限制/时间窗口/升级风险判定 |
| 🔧 **AIOps 诊断** | Plan-Execute-Replan | 自动故障诊断和根因分析 |
| 📚 **RAG 问答** | LangGraph + Milvus | 向量检索增强、文档上传索引 |
| 🔌 **MCP 集成** | MCP 协议 | 日志查询、监控数据工具接入 |

## 🛠️ 技术栈

- **框架**: FastAPI + LangChain + LangGraph
- **LLM**: 阿里云 DashScope (通义千问 qwen3-max)
- **向量库**: Milvus 2.5 (HNSW 索引)
- **Embedding**: DashScope text-embedding-v4 (1024 维)
- **工具协议**: MCP (Model Context Protocol)
- **依赖管理**: uv / pip

## 🚀 快速开始

### 环境要求
- Python 3.11+
- Docker Desktop（Milvus 向量数据库）
- 阿里云 DashScope API Key（[获取地址](https://dashscope.aliyun.com/)）

### 安装和启动

#### Linux/macOS

```bash
# 1. 安装依赖
pip install uv
uv venv && source .venv/bin/activate
uv pip install -e .

# 2. 配置 API Key
cp .env.example .env   # 编辑 .env 填入 DASHSCOPE_API_KEY

# 3. 启动 Milvus
docker compose -f vector-database.yml up -d

# 4. 启动 MCP 服务（可选）
python mcp_servers/cls_server.py &
python mcp_servers/monitor_server.py &

# 5. 启动主服务
uvicorn app.main:app --host 0.0.0.0 --port 9900
```

#### Windows

```powershell
# 1. 安装依赖
pip install uv
uv venv
.venv\Scripts\activate
uv pip install -e .

# 2. 配置 API Key
notepad .env   # 填入 DASHSCOPE_API_KEY

# 3. 启动 Milvus
docker compose -f vector-database.yml up -d

# 4. 启动主服务
python -m uvicorn app.main:app --host 0.0.0.0 --port 9900

# 或使用一键启动脚本
.\start-windows.bat
```

### 访问服务
- **API 文档 (Swagger)**: http://localhost:9900/docs
- **Web 界面**: http://localhost:9900

---

## 📡 API 接口

### 客服 Agent

| 功能 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 客服对话 | POST | `/api/chat` | SupervisorAgent 多Agent路由 |
| 流式对话 | POST | `/api/chat_stream` | SSE 流式输出 |
| RAG 对话 | POST | `/api/chat/rag` | 知识库问答模式 |
| 清空会话 | POST | `/api/chat/clear` | 清除历史 |
| 上下文同步 | POST | `/api/chat/context/sync` | 商家端回复同步 |
| 会话信息 | GET | `/api/chat/session/{id}` | 查询会话状态 |

### 退货审核 Agent

| 功能 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 退货审核 | POST | `/api/return/audit` | 自动审核退货申请 |
| 流式审核 | POST | `/api/return/audit_stream` | SSE 流式输出 |
| 拒绝次数 | GET | `/api/return/rejection_count/{user}` | 查询用户连续拒绝次数 |

### AIOps 运维

| 功能 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 智能诊断 | POST | `/api/aiops` | Plan-Execute-Replan 诊断 |
| 文件上传 | POST | `/api/upload` | 上传文档到知识库 |
| 健康检查 | GET | `/api/health` | 服务状态 |

### 使用示例

```bash
# 客服对话（ContextEnvelope 格式 — 兼容 Java mall-portal）
curl -X POST "http://localhost:9900/api/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId": "s1",
    "user": {"userId": 1, "username": "test"},
    "product": {"productId": 100, "productName": "iPhone 16"},
    "message": {"content": "这个手机支持5G吗？"}
  }'

# 退货审核
curl -X POST "http://localhost:9900/api/return/audit" \
  -H "Content-Type: application/json" \
  -d '{"applyId": 123}'

# 流式对话
curl -X POST "http://localhost:9900/api/chat_stream" \
  -H "Content-Type: application/json" \
  -d '{"Id":"s1", "Question":"你好"}' \
  --no-buffer
```

---

## 📁 项目结构

```
super_biz_agent_py/
├── app/                                    # 应用核心
│   ├── main.py                             # FastAPI 入口
│   ├── config.py                           # 配置管理（全量配置）
│   ├── api/                                # API 路由层
│   │   ├── chat.py                         # 客服对话（SupervisorAgent）
│   │   ├── aiops.py                        # AIOps 诊断
│   │   ├── return_audit.py                 # 退货审核
│   │   ├── file.py                         # 文件上传
│   │   └── health.py                       # 健康检查
│   ├── services/                           # 业务服务层
│   │   ├── chat_service.py                 # 客服 SupervisorAgent + 4子Agent
│   │   ├── return_agent_service.py         # 退货审核 ReactAgent + LRU缓存
│   │   ├── rag_agent_service.py            # RAG Agent（知识库问答）
│   │   ├── aiops_service.py                # AIOps Plan-Execute-Replan
│   │   ├── vector_store_manager.py         # Milvus 向量存储管理
│   │   ├── vector_embedding_service.py     # Embedding 向量化服务
│   │   ├── vector_index_service.py         # 向量索引服务
│   │   ├── vector_search_service.py        # 向量检索服务
│   │   └── document_splitter_service.py    # 文档分割服务
│   ├── agent/                              # Agent 核心逻辑
│   │   ├── mcp_client.py                   # MCP 客户端
│   │   └── aiops/                          # AIOps Plan-Execute-Replan
│   │       ├── planner.py                  # 计划制定
│   │       ├── executor.py                 # 步骤执行
│   │       └── replanner.py                # 重规划器
│   ├── tools/                              # Agent 工具集
│   │   ├── faq_tools.py                    # FAQ 向量检索
│   │   ├── audit_tools.py                  # 退货规则查询（合并7个工具）
│   │   ├── knowledge_tool.py               # 知识库查询
│   │   ├── time_tool.py                    # 时间工具
│   │   ├── query_metrics_alerts.py         # Prometheus 告警查询
│   │   └── query_logs_tools.py             # CLS 日志查询（Mock模式）
│   ├── models/                             # 数据模型
│   │   ├── request.py                      # 请求模型（兼容 ContextEnvelope）
│   │   └── response.py                     # 响应模型
│   ├── core/                               # 核心组件
│   │   ├── llm_factory.py                  # LLM 工厂
│   │   └── milvus_client.py                # Milvus 客户端
│   └── utils/                              # 工具类
│       ├── logger.py                       # Loguru 日志
│       └── prompt_loader.py                # Prompt 模板加载器
├── prompts/                                # Prompt 模板（Markdown）
│   ├── chat/                               # 客服 Prompt（6个）
│   │   ├── supervisor.md                   # 路由 Supervisor
│   │   ├── pre_sales.md                    # 售前 Agent
│   │   ├── post_sales.md                   # 售后 Agent
│   │   ├── escalation.md                   # 升级 Agent
│   │   └── chitchat.md                     # 闲聊 Agent
│   ├── audit/                              # 退货审核 Prompt（2个）
│   │   ├── return_audit.md                 # 审核 Agent
│   │   └── rule_judge.md                   # 规则判定
│   └── aiops/                              # AIOps Prompt（3个）
├── data/                                   # 静态数据
│   ├── faq/product_faq.json                # 150条 FAQ
│   └── audit/rules.json                    # 退货审核规则 v2.0
├── mcp_servers/                            # MCP 服务端
│   ├── cls_server.py                       # CLS 日志查询
│   └── monitor_server.py                   # 监控数据服务
├── static/                                 # Web 前端
├── aiops-docs/                             # 运维知识库文档
├── .env                                    # 环境变量配置
├── vector-database.yml                     # Milvus Docker Compose
├── pyproject.toml                          # 项目元数据 + 依赖
├── start-windows.bat                       # Windows 一键启动
└── stop-windows.bat                        # Windows 停止脚本
```

---

## 🤖 Agent 架构详解

### 1. 客服 Agent（SupervisorAgent）

```
SupervisorAgent "agent_router"  ← 快速关键词路由 + LLM 语义路由
├── pre_sales_agent  (售前) → FaqTools（商品/价格/对比/推荐）
├── post_sales_agent (售后) → FaqTools + 规则库 + 天数计算
├── escalation_agent (升级) → 零工具（纯话术 + 情绪安抚）
└── chitchat_agent   (闲聊) → DateTimeTools（问候/感谢）
```

**路由策略**：
- 商品/价格/对比/推荐 → `pre_sales`
- 退货/退款/物流/保修 → `post_sales`
- 投诉/律师/法律/不确定 → `escalation`
- 问候/感谢/无关话题 → `chitchat`

### 2. 退货审核 Agent（ReactAgent）

单 ReactAgent + 7 工具，短路逻辑内置 Prompt：

```
短路规则（优先级从高到低）：
1. rejectCount ≥ 3 → 直接转人工
2. strict_reject 命中 → 跳过后续检查，直接拒绝
3. auto_approve 不匹配 → 拒绝，跳过升级扫描
4. 可通过 + 情绪激烈 → 检查升级风险
```

### 3. AIOps Agent（Plan-Execute-Replan）

```
Planner → Executor → Replanner → (循环/结束)
   ↓          ↓          ↓
 制定计划    执行步骤    评估 → continue/replan/respond
```

---

## ⚙️ 配置说明

通过 `.env` 文件配置：

```bash
# ==================== 必填 ====================
DASHSCOPE_API_KEY=your-api-key          # 阿里云 DashScope API Key
DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
RAG_MODEL=qwen3-max                     # 对话模型

# ==================== Milvus ====================
MILVUS_HOST=localhost
MILVUS_PORT=19530

# ==================== RAG ====================
RAG_TOP_K=3
CHUNK_MAX_SIZE=800
CHUNK_OVERLAP=100

# ==================== Mall 后端 ====================
MALL_ADMIN_BASE_URL=http://localhost:8080   # Java mall-admin 地址

# ==================== 退货审核 ====================
RETURN_AUDIT_REJECTION_MAX_CONSECUTIVE=3
RETURN_AUDIT_RECEIPT_UNCONDITIONAL_DAYS=7
RETURN_AUDIT_RECEIPT_CONDITIONAL_DAYS=15

# ==================== MCP (可选) ====================
MCP_ENABLED=false
MCP_CLS_URL=http://localhost:8003/mcp
MCP_MONITOR_URL=http://localhost:8004/mcp

# ==================== Mock 模式 ====================
CLS_MOCK_ENABLED=true                   # 无真实 CLS 时使用模拟日志
PROMETHEUS_MOCK_ENABLED=false            # 关闭时直连 Prometheus API
```

---

## 🧪 测试

```bash
# RAG 检索质量评估
python rag-test/scripts/evaluate.py

# 启动单接口测试
curl -X POST "http://localhost:9900/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"Id":"test","Question":"iPhone支持5G吗？","productName":"iPhone 16"}'
```

---

## 🐛 常见问题

### Milvus 连接失败
```bash
docker ps | grep milvus
docker compose -f vector-database.yml restart standalone
```

### API Key 错误
```bash
# 检查配置是否生效
cat .env | grep DASHSCOPE_API_KEY
```

### 端口占用
```powershell
# Windows
netstat -ano | findstr :9900
taskkill /F /PID <PID>
```

---

## 📚 参考资源

- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/)
- [LangGraph SupervisorAgent](https://langchain-ai.github.io/langgraph/how-tos/multi-agent-multi-turn/)
- [阿里云 DashScope](https://dashscope.aliyun.com/)
- [MCP 协议](https://modelcontextprotocol.io/)

## 📄 许可证

author： chief

MIT License
