# EvalKit

给评测同学用的 **Promptfoo 工作台**：配置 Prompt / Provider / Tests，跑评测，看报告。

- 后端：Python + FastAPI（调度 `promptfoo eval`，解析结果并生成报告）
- 前端：Vue 3 + Ant Design Vue（可视化配置、一键运行、报告可视化）
- 引擎：开源 [promptfoo](https://www.promptfoo.dev/)

## 功能

- 可视化配置 Prompt、Provider、Tests（也可直接编辑 YAML）
- 异步运行 promptfoo 评测任务
- 自动生成 **JSON / HTML / CSV** 报告
- 报告页：通过率、Provider 对比、断言明细、筛选检索
- 内置 **Demo Mock Eval**（本地 Python mock provider，无需 API Key）

## 目录结构

```text
Evalkit/
├── backend/          # FastAPI
├── frontend/         # Vue + Ant Design Vue
├── samples/          # 示例 YAML / mock provider
└── README.md
```

## 快速开始

### 0. 安装 Promptfoo CLI（本地 tools）

```bash
cd tools
npm install
```

需要 Node.js >= 22.22。

### 1. 后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

浏览器打开：http://localhost:5173

### 3. 跑一次 Demo

1. 打开「测评任务」→ `Demo Mock Eval`
2. 点击「运行测评」
3. 在报告页查看通过率与明细，可下载 JSON / HTML / CSV

## 使用真实模型

编辑配置中的 `providers`，例如：

```yaml
providers:
  - id: openai:gpt-4o-mini
    label: gpt-4o-mini
```

启动后端前设置环境变量：

```bash
export OPENAI_API_KEY=sk-...
```

## API 概览

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/dashboard/stats` | 仪表盘统计 |
| GET/POST | `/api/configs` | 配置列表 / 创建 |
| PUT/DELETE | `/api/configs/{id}` | 更新 / 删除配置 |
| GET/POST | `/api/runs` | 运行列表 / 启动测评 |
| GET | `/api/runs/{id}` | 运行详情 |
| GET | `/api/runs/{id}/report` | 结构化报告视图 |
| GET | `/api/runs/{id}/report.json` | 下载 JSON |
| GET | `/api/runs/{id}/report.html` | 下载 HTML |
| GET | `/api/runs/{id}/report.csv` | 下载 CSV |

## 说明

- Promptfoo 优先使用 `tools/node_modules/.bin/promptfoo`
- 运行产物保存在 `data/runs/{run_id}/`
- 配置保存在 `data/configs/{config_id}/`
