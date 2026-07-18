const state = {
  snapshot: null,
  answer: null,
};

const fallbackQuestion = "电池充电截止电压是多少？";

const byId = (id) => document.getElementById(id);

async function requestJson(url, options) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function renderSpaces(spaces) {
  const list = byId("space-list");
  list.innerHTML = spaces
    .map(
      (space, index) => `
        <button class="space-item ${index === 0 ? "active" : ""}" type="button">
          <span class="space-icon ${space.color}">${space.name.slice(0, 1)}</span>
          <span>
            <strong>${space.name}</strong>
            <small>${space.document_count} 份文档 · ${space.description}</small>
          </span>
          <span aria-hidden="true">›</span>
        </button>
      `,
    )
    .join("");
}

function renderThreads(id, questions, withTime = true) {
  const list = byId(id);
  list.innerHTML = questions
    .map(
      (question, index) => `
        <button class="thread-item ${index === 0 ? "active" : ""}" type="button">
          <strong>${question}</strong>
          ${withTime ? `<small>${index === 0 ? "14:32" : index < 3 ? "昨天" : "05-18"}</small>` : "<small>收藏</small>"}
        </button>
      `,
    )
    .join("");
}

function renderSources(sources) {
  const list = byId("source-list");
  list.innerHTML = sources
    .map(
      (source, index) => `
        <article class="source-card">
          <span class="source-rank">${index + 1}</span>
          <div>
            <strong>${source.title} ${source.version}</strong>
            <small>第 ${source.page ?? "-"} 页 · ${source.location}</small>
            <p>${source.excerpt}</p>
            <div class="source-actions">
              <button type="button">打开原文</button>
              <button type="button" data-source-id="${source.id}">查看上下文</button>
            </div>
          </div>
        </article>
      `,
    )
    .join("");

  list.querySelectorAll("[data-source-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const source = state.snapshot.sources.find((item) => item.id === button.dataset.sourceId);
      renderSourceDetail(source);
    });
  });
}

function renderSourceDetail(source) {
  if (!source) return;
  byId("source-detail").innerHTML = `
    <p class="eyebrow">引用详情</p>
    <h2>${source.relevance}</h2>
    <small>${source.title} ${source.version} · 第 ${source.page ?? "-"} 页 · ${source.location}</small>
    <blockquote>${source.excerpt}</blockquote>
    <p>这条内容直接支撑回答中的关键数值，适合在答案里作为固定证据引用。</p>
    <div class="source-actions">
      <button type="button">返回回答</button>
      <button type="button">加入收藏</button>
    </div>
  `;
}

function renderEvents(events) {
  byId("event-steps").innerHTML = events
    .map(
      (event) => `
        <li title="${event.summary}">
          ${event.label}
        </li>
      `,
    )
    .join("");
}

function renderAnswer(answer, question) {
  state.answer = answer;
  byId("answer-title").textContent = question || fallbackQuestion;
  byId("answer-text").textContent = answer.answer;
  byId("confidence-pill").textContent = `${answer.confidence}可信`;
  byId("confidence-pill").className =
    answer.confidence === "高" ? "status-pill high" : "status-pill medium";
  renderEvents(answer.events);
  byId("citation-list").innerHTML = answer.citations
    .map(
      (citation) => `
        <li>
          <button type="button" data-source-id="${citation.source_id}">${citation.title}</button>
          第 ${citation.page ?? "-"} 页：${citation.excerpt}
        </li>
      `,
    )
    .join("");
  byId("citation-list").querySelectorAll("[data-source-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const source = state.snapshot.sources.find((item) => item.id === button.dataset.sourceId);
      renderSourceDetail(source);
    });
  });
  byId("next-actions").innerHTML = answer.next_actions
    .map((action) => `<button type="button">${action}</button>`)
    .join("");
}

async function ask(question) {
  byId("answer-text").textContent = "正在理解问题、检索资料并提取证据。";
  const answer = await requestJson("/api/demo/answer", {
    method: "POST",
    body: JSON.stringify({
      question,
      knowledge_space_id: state.snapshot?.spaces?.[0]?.id ?? null,
    }),
  });
  renderAnswer(answer, question);
}

async function init() {
  state.snapshot = await requestJson("/api/demo/workspace");
  byId("current-user").textContent = state.snapshot.current_user;
  byId("hero-user").textContent = state.snapshot.current_user;
  const activeSpace = state.snapshot.spaces[0];
  byId("health-value").textContent = `${activeSpace.health_percent}%`;
  byId("indexed-value").textContent = activeSpace.document_count;
  renderSpaces(state.snapshot.spaces);
  renderThreads("recent-list", state.snapshot.recent_questions);
  renderThreads("saved-list", state.snapshot.saved_questions, false);
  renderSources(state.snapshot.sources);
  await ask(fallbackQuestion);
}

byId("ask-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = byId("question-input").value.trim() || fallbackQuestion;
  await ask(question);
});

init().catch((error) => {
  byId("answer-text").textContent = "原型数据加载失败，请确认后端服务已启动。";
  console.error(error);
});
