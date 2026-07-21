---
name: iterate-curx-qa-ui
description: 延续、实现或评审 Curx 知识问答界面及其真实模型流式联调。用于修改 src/curx/web 下的首页、问答、历史会话、Markdown 展示、响应式布局，或调整 /api/chat 流式事件、追问上下文和模型配置时；也用于公司与本地代码同步后恢复既定交互约束并完成回归验证。
---

# 迭代 Curx 问答界面

## 先恢复项目上下文

1. 阅读 `docs/system-design.md`，把系统边界和 SSE 事件合同作为技术来源。
2. 阅读 `docs/front_design.md`，把内部知识工作台的克制、稳定、可扫描作为视觉来源。
3. 检查 `resource/` 中的 UI 参考图，但以用户最近确认的交互决定为准。
4. 阅读 `AGENTS.md`；存在 `graphify-out/graph.json` 时，先用 `graphify query` 缩小代码范围。
5. 运行 `git status --short` 和目标文件的 diff。保留公司或用户已有改动，不回退来源不明的修改。

## 保持已确认的产品约束

- 左侧一级导航只展示“AI 问一问”“知识空间”“管理设置”。
- 上传解析属于知识空间子页面；原文预览只在用户打开文档或引用时出现。
- 顶部搜索默认只显示放大镜按钮，点击后再打开搜索弹窗。
- 首页使用长提问框；桌面端把历史对话放在右侧，默认最多 5 条，超过后提供展开和收起。展开列表空间不足时使用独立细滚动条。
- 历史记录当前在浏览器本地最多保存 12 条；除非任务明确要求服务端持久化，不虚构账号级同步能力。
- 主提问和继续追问均支持 Enter 发送、Shift+Enter 换行，并跳过输入法组字期间的 Enter。
- 继续追问的“发送”按钮保持纯文字，不添加箭头。
- 返回箭头使用粗、圆润、黑色造型；“开始检索”使用灯泡标识，不使用箭头。
- 等待首段模型内容时显示“AI 正在思考中”的轻微明暗呼吸效果；收到首个 `answer.delta` 后立即切换到回答正文，并尊重 `prefers-reduced-motion`。
- 模型 Markdown 必须渲染为标题、列表、表格、引用、链接和代码等结构。使用 DOM 节点构建安全输出，不把模型文本直接写入 `innerHTML`。

## 保持流式问答合同

- 前端通过 `POST /api/chat/stream` 发送完整 `messages` 上下文，追问不能丢失之前的用户和助手消息。
- 对外只消费稳定事件：`answer.started`、`answer.generating`、`answer.delta`、`answer.completed`、`answer.failed`。
- 不向界面泄露模型内部推理；只展示安全、可读的阶段摘要。
- `answer.delta` 只追加正文；`answer.completed` 负责最终答案、阶段、引用和下一步操作。
- 模型供应商配置放在 `Settings` 和环境变量中，不在前端或源码中写入密钥。

## 文件定位

- 页面结构：`src/curx/web/index.html`
- 视觉与响应式：`src/curx/web/styles.css`
- 交互、历史、SSE、Markdown：`src/curx/web/app.js`
- Chat API：`src/curx/api/chat.py`
- 模型适配与 SSE：`src/curx/services/chat_llm.py`
- 请求和事件结构：`src/curx/domain/schemas.py`
- 模型配置：`src/curx/core/config.py`、`.env.example`
- 回归测试：`tests/unit/test_demo_api.py`

## 实施流程

1. 从用户描述提取页面位置、默认状态、展开状态、加载状态和移动端状态。
2. 优先沿用当前原生 HTML、CSS、JavaScript 结构，不为小交互引入新框架。
3. 同步修改结构、样式和状态逻辑，避免只做静态外观。
4. 对历史、流式输出、错误、空状态和输入法行为逐项回归。
5. 启动或复用最新本地服务，在实际页面检查布局、点击、刷新、流式首段和控制台错误。
6. 截图检查桌面端；涉及响应式结构时同时检查窄屏，确认无文本重叠和横向溢出。

## 提交前验证

依次运行：

```powershell
node --check src\curx\web\app.js
uv run ruff check src tests
uv run pytest -q
git diff --check
graphify update .
```

若 `graphify` 不可用，明确记录未执行；不要因此跳过其余检查。提交前再次检查 `git status --short`，确认 `.env`、缓存、运行日志和本地数据库未进入暂存区。
