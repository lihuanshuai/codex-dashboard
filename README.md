# codex-dashboard

本机 Codex 任务状态 Dashboard。它基于 FastAPI + Jinja2 模板实现，前端使用 Lit Web Components 组件化，直接读取 `~/.codex/sessions` 和 `~/.codex/archived_sessions` 下的 rollout JSONL，不依赖外部数据库。

![Dashboard 截图](docs/screenshot.png)

## 功能

- 按项目和会话组织 Codex 状态，同一个会话只展示一次。
- 默认优先展示运行中 / 待审批的项目和会话，也可切换为仅按 JSONL 最近事件时间倒序。
- 展示权限审批请求数量，能标出尚未收到 `function_call_output` 的待审批任务；连接 Codex app-server control socket 后会监控实时审批请求，可直接从网页批准或拒绝。Codex Desktop 的待审批项会提供跳回原会话的入口。
- 会话标题来自该会话的第一个用户输入，单行截断，完整内容可通过鼠标悬停查看。
- 点击会话卡片可查看该会话的用户与 Codex 对话记录。
- 后端使用 Pydantic model 描述任务与会话响应结构。
- Lit 组件拆分在 `static/components/` 下，页面直接用原生 ES Modules 加载源码；修改 JS 后刷新即可生效，不需要打包步骤。
- 显示用户输入、最近回复、工作目录、会话来源、耗时、token 和工具调用数量。
- 支持搜索 prompt / cwd / 回复 / 审批说明，按状态、待审批状态和归档来源过滤。
- 浏览器页面每 15 秒自动刷新，适合放在本机常驻查看。

## 启动

```bash
uv run codex-dashboard
```

默认监听：`http://127.0.0.1:8765`

可选参数：

```bash
uv run codex-dashboard --host 127.0.0.1 --port 8765 --codex-home ~/.codex
```

首次使用可先同步环境：

```bash
uv sync
```

## API

```bash
curl 'http://127.0.0.1:8765/api/tasks?limit=80'
```

查看某个会话的对话记录：

```bash
curl 'http://127.0.0.1:8765/api/session?file=/path/to/rollout.jsonl'
```

查看网页审批桥状态：

```bash
curl 'http://127.0.0.1:8765/api/approval-bridge/status'
```

返回结构包含：

- `summary`：总数、状态分布、来源分布、审批分布、活跃工作区。
- `tasks`：每个 Codex turn 的状态、cwd、prompt、最近回复、工具调用、审批请求与 token 信息。
- `messages`：会话详情接口返回的用户与 Codex 对话记录。

## 说明

任务状态来自 JSONL 事件：看到 `task_started` 且还没有对应 `task_complete` 时显示为 `running`；权限审批来自 `require_escalated` / `with_escalated_permissions` 工具调用，若还没有对应 `function_call_output` 则显示为待审批。

网页审批不是改写 JSONL，而是把审批决定发给正在运行的 Codex app-server。页面会主动连接 control socket；如果 socket 不存在，会先尝试运行 `codex remote-control start --json` 再连接，以捕获后续实时审批回调。为避免误审批，后端会校验请求必须来自 localhost，且 `session_id` / `turn_id` / `call_id` 必须匹配当前仍处于 pending 的本机会话。

侧栏「网页审批」里的实时可审批列表来自 app-server live request。Codex Desktop 当前会话如果没有把审批回调路由到这个 app-server，Dashboard 会在「Desktop 待审批监控」里用 JSONL 扫描结果展示它们，并提供“打开 Desktop 原会话审批”按钮。按钮不会使用浏览器直跳 `codex://`，而是调用 localhost 后端校验 thread id 后执行 `/usr/bin/open codex://threads/<thread_id>`；不会展示网页内批准按钮，避免把无法提交的历史/非 live 请求伪装成可审批。

当前已确认 Desktop 的 `codex-ipc/ipc-501.sock` 是 IDE context 通道，不是审批提交通道；app-server 协议中的审批决定也只能作为 live server request 的 response 返回。因此 Dashboard 只对自己实时捕获到的 app-server 审批请求执行网页内批准，对 Desktop JSONL 待审批请求只做定位与跳转。

也可以手动提前启动：

```bash
codex remote-control start --json
```

如果你的 control socket 不在默认位置，可通过环境变量指定：

```bash
CODEX_DASHBOARD_APP_SERVER_SOCK=/path/to/app-server-control.sock uv run codex-dashboard
```
