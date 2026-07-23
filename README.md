# Crux
The core of your own matter

- 不是大而全的数据库，是你精选、珍藏、反复调用的“认知隘口”——所有语料翻过这座山，才真正成为你的东西

## 当前雏形

Curx 现在包含一个 FastAPI 应用骨架和一个知识库工作台原型页面：

- `GET /api/health`：应用健康检查。
- `GET /api/demo/workspace`：返回演示知识空间、最近问题和引用来源。
- `POST /api/demo/answer`：返回带公开回答事件和固定引用的演示回答。
- `/`：知识库工作台 UI，包含知识空间、问答区、回答流程和引用来源。

后续产品阶段、开发任务和验收门槛以 `docs/task_plan.md` 为主看板。

## 本地运行

```powershell
Copy-Item .env.example .env
docker compose up -d
uv run alembic upgrade head
uv run python -m curx.cli bootstrap-admin --username admin
uv run curx
```

打开 http://127.0.0.1:8020 查看页面。

Curx 的本地端口与 AidBot 隔离：后端 `8020`、PostgreSQL `5433`、Redis `6380`、
MinIO API `9010`、MinIO 控制台 `9011`。如需保留现有 `.env` 中的模型密钥，可在
自动忽略提交的 `.env.local` 中只覆盖这些本地端口。

`bootstrap-admin` 会创建初始租户、管理员、默认知识空间，并且只展示一次管理员激活密钥。
使用输出的用户名和激活密钥在页面完成首次绑定。后续普通用户的激活密钥由管理员在
“管理设置”中创建；数据库只保存密钥哈希和前缀。

如需手动激活本地虚拟环境：

```powershell
.\.venv\Scripts\activate
```

## 验证

```powershell
$env:PYTHONPATH = "src"
uv run pytest
```

## 下一步

1. 接入 Alembic 迁移和真实 SQLAlchemy 模型。
2. 将演示知识空间替换为 PostgreSQL 中的租户、用户、密钥和知识空间数据。
3. 实现 Markdown 上传、异步索引任务和混合检索接口。
