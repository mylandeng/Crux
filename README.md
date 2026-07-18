# Crux
The core of your own matter

- 不是大而全的数据库，是你精选、珍藏、反复调用的“认知隘口”——所有语料翻过这座山，才真正成为你的东西

## 当前雏形

Curx 现在包含一个 FastAPI 应用骨架和一个知识库工作台原型页面：

- `GET /api/health`：应用健康检查。
- `GET /api/demo/workspace`：返回演示知识空间、最近问题和引用来源。
- `POST /api/demo/answer`：返回带公开回答事件和固定引用的演示回答。
- `/`：知识库工作台 UI，包含知识空间、问答区、回答流程和引用来源。

## 本地运行

```powershell
Copy-Item .env.example .env
docker compose up -d
$env:PYTHONPATH = "src"
uv run uvicorn curx.main:app --reload
```

打开 http://127.0.0.1:8000 查看页面。

## 验证

```powershell
$env:PYTHONPATH = "src"
uv run pytest
```

## 下一步

1. 接入 Alembic 迁移和真实 SQLAlchemy 模型。
2. 将演示知识空间替换为 PostgreSQL 中的租户、用户、密钥和知识空间数据。
3. 实现 Markdown 上传、异步索引任务和混合检索接口。
