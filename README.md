# My Screenwriter

面向短剧开发的 Human-in-the-loop 多智能体剧本工作流 MVP。系统每次只执行一轮 AI 生成与审查，保存不可变版本并通知用户，然后停在 `WAITING_HUMAN_REVIEW`。只有用户提交批注并点击 Generate，或明确选择批准定稿，工作流才继续迁移。

## 第一版包含什么

- Creative Brief Agent：把灵感整理成稳定的项目约束。
- Story Writer：系统中唯一拥有剧情创作权的 Agent。
- 五个并行 Reviewer：结构冲突、人物、留存付费、连续性、制片可行性。
- Chief Editor：把 AI 诊断和人工批注压缩为下一轮 `Revision Brief`。
- Verification Agent：做格式、回归和修改落实检查。
- Human Review Gate：逐集批注、显式 Generate、显式 Finalize、一次性审阅令牌。
- 版本历史：每轮草稿、Review、Verification、Revision Brief 均不可变保存。
- SQLite 持久化、REST API、日志通知适配器、Mock 模型和远程模型适配器。

## 架构

```text
Web UI / REST API
        │
        ▼
ScreenwriterService (application workflow)
        │
        ├── ProjectRepository ── SQLite (MVP)
        ├── LLMProvider ──────── Mock / OpenAI-compatible endpoint
        └── NotificationPort ─── Logging (MVP) / Feishu adapter (next)
        │
        ▼
Domain: Project + StoryVersion + HumanComment + state machine
```

目录职责：

```text
src/screenwriter/
├── domain/           # 纯领域对象和端口，不依赖 FastAPI/模型 SDK
├── application/      # 状态机、Agent 编排、Prompt 与结构化输出契约
├── infrastructure/   # SQLite、模型 HTTP、通知适配器
└── api/              # FastAPI 输入输出适配
```

核心状态迁移：

```text
DRAFT
  └─ Generate initial
       → GENERATING → REVIEWING → WAITING_HUMAN_REVIEW
                                      ├─ Add comments + Generate
                                      │    → GENERATING → ... → WAITING_HUMAN_REVIEW
                                      └─ Approve & Finalize → FINAL
```

`human_review_token` 是一次性令牌。SQLite 使用 `BEGIN IMMEDIATE` 原子消费令牌，防止双击 Generate 或重复请求启动两轮生成。

## 大语言模型接入模式

### 1. 端口与适配器

应用层只依赖 `LLMProvider.generate_json(ModelTask)`，不知道厂商 SDK、URL 或鉴权方式。`ModelTask` 包含：

- `role`：用于模型路由；
- `system_prompt` / `user_prompt`：角色边界和任务上下文；
- `output_schema`：该 Agent 必须返回的 JSON Schema；
- `temperature`：Writer 较高，Reviewer 较低。

第一版提供两个适配器：

- `MockLLMProvider`：完全本地、确定性结果，用于测试状态机和接口。
- `OpenAICompatibleProvider`：调用 `${LLM_BASE_URL}/chat/completions`，使用 JSON Schema 结构化输出。可对接提供兼容接口的云模型或模型网关。

### 2. 按角色路由模型

不同 Agent 不需要使用同一个模型：

```env
LLM_DEFAULT_MODEL=gpt-5-mini
LLM_WRITER_MODEL=gpt-5
LLM_REVIEWER_MODEL=gpt-5-mini
LLM_EDITOR_MODEL=gpt-5-mini
```

- Writer 使用创作能力更强的模型；
- Reviewer 并行调用成本较低、结构化输出稳定的模型；
- Chief Editor 使用擅长约束归纳的模型；
- 后续可在 `ModelRouting` 中增加按项目、市场、预算或失败重试路由。

### 3. 上下文隔离

各 Agent 不共享无限增长的聊天记录，而只接收任务所需的结构化状态：

- Writer：Creative Brief、项目配置、上一版本、Revision Brief；
- Reviewer：当前完整草稿和自己的审查职责；
- Chief Editor：上一版本、AI Review、人工批注；
- Verification：新草稿和本轮 Revision Brief。

这对应“Stateless Agents, Stateful Workflow”：模型调用是无状态的，数据库中的工作流和版本才是状态真源。

### 4. 格式与审查基准

Writer Prompt 固定引用并落实[《剧本标准格式说明》](https://ycnbhmgr4z9b.feishu.cn/docx/QCEidXpT5ogM1HxeQXrcha7onXd)，用户审阅的 `screenplay` 必须采用规定的场景标题、动作行和双语对白格式。

所有 Reviewer 固定引用[《短剧剧本深度拆解 Prompt｜完整版》](https://ycnbhmgr4z9b.feishu.cn/docx/NSTidkU9YodkBPxL9yYcMnaLngb)，并遵守“先讲事实，再讲判断”和“Reviewer 只有诊断权”的边界。

### 5. 生产环境建议

当前 API 会在请求内等待一轮模型调用完成，适合本地验证。生产化时保持应用层不变，替换外围设施：

- API 只创建 iteration job，Worker 异步执行；
- SQLite 替换为 PostgreSQL；
- 引入队列并用 `project_id + iteration` 做幂等键；
- 增加模型超时、指数退避、熔断、用量和成本日志；
- 保存 Prompt 版本、模型名、请求追踪 ID 和原始结构化响应；
- NotificationPort 接入飞书消息，携带项目、版本、审查摘要和审阅链接；
- 对剧本正文做分集/分段生成，避免超长上下文与单次输出截断。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn screenwriter.main:app --reload
```

默认 `LLM_PROVIDER=mock`，无需密钥。打开 `http://localhost:8000/docs` 可调用 API。

另开一个终端启动用户界面：

```bash
cd web
npm install
cp .env.example .env.local
npm run dev
```

打开 `http://localhost:3000`。页面可完成项目创建、创作参数设置、初稿生成、逐集批注、下一轮生成、定稿以及版本回看。

右上角「模型设置」可以直接切换 Mock / OpenAI-compatible，并配置 Base URL、API Key 和各 Agent 使用的模型。设置保存在 SQLite 中，后端会在每次模型调用前读取当前配置，因此保存后从下一次 Generate 起立即生效，**不需要停止或重启 FastAPI**。正在执行中的一轮不会被中途切换。

也可以通过后端环境变量设置首次启动时的默认远程模型：

```env
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://your-model-gateway.example/v1
LLM_API_KEY=...
```

运行测试：

```bash
pytest
```

## API 主路径

1. `POST /projects`：创建项目。
2. `POST /projects/{id}/iterations`：生成第一版并进入人工审阅。
3. `POST /projects/{id}/comments`：添加逐集或文本锚点批注。
4. 重新读取 `GET /projects/{id}` 获取一次性 `human_review_token`。
5. `POST /projects/{id}/review/generate`：携带 token 进入下一轮。
6. `POST /projects/{id}/review/finalize`：携带 token 定稿。
7. `GET /projects/{id}/versions`：查看完整版本历史。

## 当前边界

- 日志通知是占位适配器，下一版可实现飞书消息推送。
- 模型结构化响应目前依赖服务端支持 JSON Schema；不支持时应新增该厂商专用适配器，不要把兼容差异写进应用层。
- 第一版未实现分布式 Job Worker，因此不要以多副本方式承载长耗时生成请求。
- 当前前端默认连接本机 `http://localhost:8000`；公网部署时需把 `NEXT_PUBLIC_API_BASE_URL` 配置为可公开访问的 HTTPS 后端地址。
