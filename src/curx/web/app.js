const defaultQuestion = "电池充电截止电压是多少？";
const conversationHistoryKeyPrefix = "curx.conversation-history.v2";
const collapsedHistoryLimit = 5;

const state = {
  identity: null,
  snapshot: null,
  answer: null,
  question: defaultQuestion,
  messages: [],
  history: [],
  historyExpanded: false,
  currentConversationId: null,
  answerAbortController: null,
  pendingAnswerScrollFrame: null,
  activeAssistantContent: null,
  previewReturn: "space",
  sources: [],
  ingestionJobs: [],
  ingestionPollTimer: null,
  knowledgeRequestVersion: 0,
  selectedFile: null,
  activeSourceId: null,
  sourceMode: "file",
};

const byId = (id) => document.getElementById(id);

class ApiError extends Error {
  constructor(status, detail = null) {
    super(detail?.message ?? `Request failed: ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function requestJson(url, options = {}) {
  const { headers = {}, ...fetchOptions } = options;
  const requestHeaders =
    options.body instanceof FormData
      ? headers
      : { "Content-Type": "application/json", ...headers };
  const response = await fetch(url, {
    ...fetchOptions,
    headers: requestHeaders,
  });

  if (response.status === 204) return null;
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, payload?.detail);
  }

  return payload;
}

function parseSseEvent(rawEvent) {
  let event = "message";
  const dataLines = [];

  rawEvent.split(/\r?\n/).forEach((line) => {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
      return;
    }

    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  });

  const data = dataLines.length ? JSON.parse(dataLines.join("\n")) : {};
  return { event, data };
}

async function requestSse(url, payload, onEvent, signal) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(response.status, payload?.detail);
  }

  if (!response.body) {
    throw new Error("Streaming response is not available in this browser.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

    const events = buffer.split(/\r?\n\r?\n/);
    buffer = events.pop() ?? "";

    for (const rawEvent of events) {
      if (!rawEvent.trim()) continue;
      onEvent(parseSseEvent(rawEvent));
    }

    if (done) break;
  }

  if (buffer.trim()) {
    onEvent(parseSseEvent(buffer));
  }
}

function appendInlineMarkdown(parent, value) {
  const text = String(value);
  const tokenPattern =
    /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|~~[^~\n]+~~|\*[^*\n]+\*|_[^_\n]+_|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/g;
  let cursor = 0;

  for (const match of text.matchAll(tokenPattern)) {
    const token = match[0];
    const index = match.index ?? 0;
    if (index > cursor) parent.append(document.createTextNode(text.slice(cursor, index)));

    if (token.startsWith("`")) {
      const code = document.createElement("code");
      code.textContent = token.slice(1, -1);
      parent.append(code);
    } else if (token.startsWith("**") || token.startsWith("__")) {
      const strong = document.createElement("strong");
      strong.textContent = token.slice(2, -2);
      parent.append(strong);
    } else if (token.startsWith("~~")) {
      const deleted = document.createElement("s");
      deleted.textContent = token.slice(2, -2);
      parent.append(deleted);
    } else if (token.startsWith("*") || token.startsWith("_")) {
      const emphasis = document.createElement("em");
      emphasis.textContent = token.slice(1, -1);
      parent.append(emphasis);
    } else {
      const linkMatch = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
      if (linkMatch) {
        const link = document.createElement("a");
        link.textContent = linkMatch[1];
        link.href = linkMatch[2];
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        parent.append(link);
      } else {
        parent.append(document.createTextNode(token));
      }
    }

    cursor = index + token.length;
  }

  if (cursor < text.length) parent.append(document.createTextNode(text.slice(cursor)));
}

function markdownTableCells(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isMarkdownTableSeparator(line) {
  const cells = markdownTableCells(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function normalizeMarkdownSource(value) {
  const source = String(value ?? "").trim();
  const wrappedMarkdown = source.match(/^```(?:markdown|md)\s*\n([\s\S]*?)\n```$/i);
  return wrappedMarkdown ? wrappedMarkdown[1] : source;
}

function renderMarkdown(container, markdown) {
  const lines = normalizeMarkdownSource(markdown).replace(/\r\n?/g, "\n").split("\n");
  const fragment = document.createDocumentFragment();
  let paragraphLines = [];
  let index = 0;

  const flushParagraph = () => {
    if (!paragraphLines.length) return;
    const paragraph = document.createElement("p");
    appendInlineMarkdown(paragraph, paragraphLines.join(" ").trim());
    fragment.append(paragraph);
    paragraphLines = [];
  };

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      flushParagraph();
      index += 1;
      continue;
    }

    const fenceMatch = trimmed.match(/^```([\w-]+)?\s*$/);
    if (fenceMatch) {
      flushParagraph();
      const codeLines = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;

      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = codeLines.join("\n");
      if (fenceMatch[1]) code.dataset.language = fenceMatch[1];
      pre.append(code);
      fragment.append(pre);
      continue;
    }

    if (trimmed.includes("|") && index + 1 < lines.length && isMarkdownTableSeparator(lines[index + 1])) {
      flushParagraph();
      const table = document.createElement("table");
      const head = document.createElement("thead");
      const headRow = document.createElement("tr");
      markdownTableCells(trimmed).forEach((cell) => {
        const header = document.createElement("th");
        appendInlineMarkdown(header, cell);
        headRow.append(header);
      });
      head.append(headRow);
      table.append(head);
      index += 2;

      const body = document.createElement("tbody");
      while (index < lines.length && lines[index].trim().includes("|")) {
        const row = document.createElement("tr");
        markdownTableCells(lines[index]).forEach((cell) => {
          const value = document.createElement("td");
          appendInlineMarkdown(value, cell);
          row.append(value);
        });
        body.append(row);
        index += 1;
      }
      table.append(body);
      fragment.append(table);
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      const level = Math.min(4, headingMatch[1].length + 2);
      const heading = document.createElement(`h${level}`);
      appendInlineMarkdown(heading, headingMatch[2]);
      fragment.append(heading);
      index += 1;
      continue;
    }

    const unorderedMatch = trimmed.match(/^[-+*]\s+(.+)$/);
    const orderedMatch = trimmed.match(/^\d+[.)]\s+(.+)$/);
    if (unorderedMatch || orderedMatch) {
      flushParagraph();
      const ordered = Boolean(orderedMatch);
      const list = document.createElement(ordered ? "ol" : "ul");

      while (index < lines.length) {
        const candidate = lines[index].trim();
        const itemMatch = ordered
          ? candidate.match(/^\d+[.)]\s+(.+)$/)
          : candidate.match(/^[-+*]\s+(.+)$/);
        if (!itemMatch) break;
        const item = document.createElement("li");
        appendInlineMarkdown(item, itemMatch[1]);
        list.append(item);
        index += 1;
      }

      fragment.append(list);
      continue;
    }

    if (trimmed.startsWith(">")) {
      flushParagraph();
      const quoteLines = [];
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        quoteLines.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      const quote = document.createElement("blockquote");
      appendInlineMarkdown(quote, quoteLines.join(" "));
      fragment.append(quote);
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      flushParagraph();
      fragment.append(document.createElement("hr"));
      index += 1;
      continue;
    }

    paragraphLines.push(trimmed);
    index += 1;
  }

  flushParagraph();
  container.replaceChildren(fragment);
}

function markdownPreview(value) {
  return normalizeMarkdownSource(value)
    .replace(/```[\s\S]*?```/g, "代码片段")
    .replace(/[#>*_`|\[\]()~-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function parentSectionFor(view, explicitParent) {
  if (explicitParent) return explicitParent;
  if (view === "home" || view === "answer") return "home";
  if (view === "space" || view === "upload" || view === "preview") return "space";
  return "settings";
}

function setView(view, explicitParent) {
  const parentSection = parentSectionFor(view, explicitParent);

  document.querySelectorAll(".nav-item[data-section]").forEach((item) => {
    item.classList.toggle("active", item.dataset.section === parentSection);
  });

  document.querySelectorAll(".view").forEach((section) => {
    section.classList.toggle("active", section.id === `view-${view}`);
  });

  if (view !== "settings") clearCreatedKeyReveal();
  window.scrollTo({ top: 0, behavior: "instant" });
  if (view === "settings" && state.identity?.role === "admin") {
    loadAccessKeys().catch(handleAuthenticatedRequestError);
  }
  if ((view === "space" || view === "upload") && state.identity) {
    loadKnowledgeData().catch(handleAuthenticatedRequestError);
  }
}

function conversationHistoryKey() {
  if (!state.identity) return null;
  return `${conversationHistoryKeyPrefix}.${state.identity.tenant.id}.${state.identity.id}`;
}

function loadConversationHistory() {
  const storageKey = conversationHistoryKey();
  if (!storageKey) return [];
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => item?.id && item?.answer) : [];
  } catch (error) {
    console.warn("Conversation history could not be loaded.", error);
    return [];
  }
}

function persistConversationHistory() {
  const storageKey = conversationHistoryKey();
  if (!storageKey) return;
  try {
    localStorage.setItem(storageKey, JSON.stringify(state.history));
  } catch (error) {
    console.warn("Conversation history could not be saved.", error);
  }
}

function formatHistoryTime(timestamp) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function renderConversationHistory() {
  const list = byId("recent-list");
  const toggle = byId("history-toggle");
  const count = byId("history-count");
  list.replaceChildren();
  list.classList.toggle("expanded", state.historyExpanded && state.history.length > collapsedHistoryLimit);

  const hasMore = state.history.length > collapsedHistoryLimit;
  toggle.hidden = !hasMore;
  toggle.textContent = state.historyExpanded ? "收起" : "展开全部";
  toggle.setAttribute("aria-expanded", String(state.historyExpanded));
  count.textContent = !state.history.length
    ? "暂无会话"
    : state.historyExpanded
      ? `共 ${state.history.length} 条`
      : `最近 ${Math.min(state.history.length, collapsedHistoryLimit)} 条`;

  if (!state.history.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = "还没有问答记录，完成一次提问后会出现在这里。";
    list.append(empty);
    return;
  }

  const visibleHistory = state.historyExpanded
    ? state.history
    : state.history.slice(0, collapsedHistoryLimit);

  visibleHistory.forEach((conversation) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-item";
    button.dataset.historyId = conversation.id;

    const copy = document.createElement("span");
    copy.className = "history-copy";
    const title = document.createElement("strong");
    const preview = document.createElement("small");
    title.textContent = conversation.title;
    preview.textContent = markdownPreview(conversation.answer.answer).slice(0, 72);
    copy.append(title, preview);

    const time = document.createElement("time");
    const updatedAt = new Date(conversation.updatedAt);
    if (!Number.isNaN(updatedAt.getTime())) time.dateTime = updatedAt.toISOString();
    time.textContent = formatHistoryTime(conversation.updatedAt);

    button.append(copy, time);
    list.append(button);
  });
}

function toggleConversationHistory() {
  state.historyExpanded = !state.historyExpanded;
  renderConversationHistory();
}

function saveCurrentConversation(answer) {
  const current = state.history.find((item) => item.id === state.currentConversationId);
  const firstQuestion = state.messages.find((message) => message.role === "user")?.content;
  const id = current?.id ?? crypto.randomUUID?.() ?? `conversation-${Date.now()}`;
  const conversation = {
    id,
    title: current?.title ?? firstQuestion ?? state.question,
    updatedAt: new Date().toISOString(),
    messages: state.messages.map((message) => ({ ...message })),
    answer,
  };

  state.currentConversationId = id;
  state.history = [conversation, ...state.history.filter((item) => item.id !== id)].slice(0, 12);
  persistConversationHistory();
  renderConversationHistory();
}

function openConversationHistory(id) {
  const conversation = state.history.find((item) => item.id === id);
  if (!conversation) return;

  state.answerAbortController?.abort();
  state.answerAbortController = null;
  state.currentConversationId = conversation.id;
  state.messages = conversation.messages.map((message) => ({ ...message }));
  state.question =
    [...state.messages].reverse().find((message) => message.role === "user")?.content ??
    conversation.title;
  byId("answer-question").textContent = conversation.title;
  byId("follow-input").value = "";
  renderConversationTranscript(state.messages);
  renderAnswerMeta(conversation.answer);
  state.answer = conversation.answer;
  setView("answer", "home");
  followAnswerOutput();
}

function renderWorkspace(snapshot) {
  const activeSpace = snapshot.spaces[0];
  state.identity = snapshot.current_user;
  const identity = state.identity;
  const displayName = identity.display_name || identity.username;
  const roleNames = { member: "普通成员", operator: "知识运营", admin: "系统管理员" };

  byId("user-avatar").textContent = displayName.slice(0, 1).toUpperCase();
  byId("user-menu-name").textContent = displayName;
  byId("user-menu-role").textContent = roleNames[identity.role] ?? identity.role;
  byId("settings-user-name").textContent = `${displayName}（${identity.username}）`;
  byId("settings-user-role").textContent = roleNames[identity.role] ?? identity.role;
  document.querySelectorAll("[data-admin-only]").forEach((element) => {
    element.hidden = identity.role !== "admin";
  });
  byId("member-settings-note").hidden = identity.role === "admin";
  const canWriteKnowledge = Boolean(activeSpace?.can_write);
  document.querySelectorAll("[data-write-only]").forEach((element) => {
    element.hidden = !canWriteKnowledge;
  });
  byId("read-only-upload-note").hidden = canWriteKnowledge;

  if (activeSpace) {
    byId("top-space-name").textContent = activeSpace.name;
    byId("home-space-name").textContent = activeSpace.name;
    byId("space-title").textContent = activeSpace.name;
    byId("home-doc-count").textContent = activeSpace.document_count;
    byId("space-doc-count").textContent = activeSpace.document_count;
    byId("space-health").textContent = `${activeSpace.health_percent}%`;
  } else {
    byId("top-space-name").textContent = "暂无授权空间";
    byId("home-space-name").textContent = "暂无授权空间";
    byId("space-title").textContent = "暂无授权空间";
    byId("home-doc-count").textContent = "0";
    byId("space-doc-count").textContent = "0";
    byId("space-health").textContent = "0%";
  }

  setSourceMode(state.sourceMode);
}

const ingestionStatusInfo = {
  queued: { label: "排队中", tone: "", summary: "等待 Worker 处理" },
  extracting: { label: "提取中", tone: "warning", summary: "正在读取原始内容" },
  normalizing: { label: "标准化", tone: "warning", summary: "正在整理文档结构" },
  chunking: { label: "切片中", tone: "warning", summary: "正在生成稳定分块" },
  embedding: { label: "向量化", tone: "warning", summary: "正在写入全文与向量索引" },
  indexed: { label: "已索引", tone: "success", summary: "全文与向量索引可用" },
  failed: { label: "失败", tone: "danger", summary: "需要处理后重试" },
  cancelled: { label: "已取消", tone: "", summary: "任务已由用户取消" },
  superseded: { label: "已替代", tone: "", summary: "已有新版本接替" },
};

const sourceTypeNames = {
  markdown: "MD",
  html: "HTML",
  pdf: "PDF",
  docx: "DOCX",
  faq: "FAQ",
};

const activeIngestionStatuses = new Set([
  "queued",
  "extracting",
  "normalizing",
  "chunking",
  "embedding",
]);

function currentKnowledgeSpace() {
  return state.snapshot?.spaces?.[0] ?? null;
}

function canWriteCurrentSpace() {
  return Boolean(currentKnowledgeSpace()?.can_write);
}

function formatSourceTimestamp(timestamp) {
  if (!timestamp) return { time: "--", date: "暂无记录" };
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return { time: "--", date: "暂无记录" };
  return {
    time: new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(date),
    date: new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
    }).format(date),
  };
}

function statusLabel(status) {
  const info = ingestionStatusInfo[status] ?? {
    label: status || "未知",
    tone: "",
    summary: "等待状态更新",
  };
  const label = document.createElement("span");
  label.className = `state-label ${info.tone}`.trim();
  label.textContent = info.label;
  return label;
}

function renderKnowledgeSources() {
  const container = byId("document-list");
  const fragment = document.createDocumentFragment();
  const indexedSources = state.sources.filter(
    (source) => source.latest_job_status === "indexed",
  );
  const failedJobs = state.ingestionJobs.filter((job) => job.status === "failed");
  const sourceTypes = [...new Set(state.sources.map((source) => source.source_type))];
  const health = state.sources.length
    ? Math.round((indexedSources.length / state.sources.length) * 100)
    : 0;
  const latestSource = state.sources
    .slice()
    .sort((left, right) => new Date(right.updated_at) - new Date(left.updated_at))[0];
  const updated = formatSourceTimestamp(latestSource?.updated_at);

  byId("space-health").textContent = `${health}%`;
  byId("space-health-note").textContent =
    health === 100 && state.sources.length ? "全部来源可检索" : state.sources.length ? "仍有任务待处理" : "等待资料";
  byId("space-doc-count").textContent = String(indexedSources.length);
  byId("home-doc-count").textContent = String(indexedSources.length);
  byId("source-type-summary").textContent = sourceTypes.length
    ? `${sourceTypes.length} 类来源`
    : "暂无来源";
  byId("failed-job-count").textContent = String(failedJobs.length);
  byId("space-updated-time").textContent = updated.time;
  byId("space-updated-date").textContent = updated.date;

  if (!state.sources.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = canWriteCurrentSpace()
      ? "还没有知识来源。上传文件、粘贴正文或创建 FAQ 后会显示在这里。"
      : "当前知识空间还没有可查看的来源。";
    container.replaceChildren(empty);
    return;
  }

  state.sources.forEach((source) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "document-row";
    button.dataset.sourceId = source.id;

    const type = document.createElement("span");
    type.className = "file-type";
    type.textContent = sourceTypeNames[source.source_type] ?? source.source_type.toUpperCase();

    const details = document.createElement("span");
    const title = document.createElement("strong");
    const meta = document.createElement("small");
    title.textContent = source.title;
    const tags = source.tags.length ? ` · ${source.tags.join(" / ")}` : "";
    meta.textContent = `版本 ${source.current_version}${tags}`;
    details.append(title, meta);

    const status = document.createElement("span");
    status.className = "document-meta";
    status.append(statusLabel(source.latest_job_status));
    const time = document.createElement("small");
    time.textContent = formatHistoryTime(source.updated_at);
    status.append(time);

    const arrow = document.createElement("span");
    arrow.className = "row-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "→";
    button.append(type, details, status, arrow);
    fragment.append(button);
  });
  container.replaceChildren(fragment);
}

function renderIngestionJobs() {
  const container = byId("ingestion-task-list");
  const fragment = document.createDocumentFragment();
  const sourceById = new Map(state.sources.map((source) => [source.id, source]));

  if (!state.ingestionJobs.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "还没有入库任务。提交资料后可在这里查看每个处理阶段。";
    container.replaceChildren(empty);
    return;
  }

  state.ingestionJobs.forEach((job) => {
    const source = sourceById.get(job.source_id);
    const info = ingestionStatusInfo[job.status] ?? {
      label: job.status,
      tone: "",
      summary: "等待状态更新",
    };
    const latestEvent = job.events[job.events.length - 1];
    const row = document.createElement("article");
    row.className = "task-row";

    const type = document.createElement("span");
    type.className = "file-type";
    type.textContent = source ? sourceTypeNames[source.source_type] : "DOC";

    const details = document.createElement("span");
    const title = document.createElement("strong");
    const summary = document.createElement("small");
    title.textContent = source?.title ?? `入库任务 ${job.correlation_id.slice(0, 8)}`;
    summary.textContent =
      job.error_message || latestEvent?.summary || info.summary;
    details.append(title, summary);

    const progressArea = document.createElement("div");
    progressArea.className = "task-progress";
    if (activeIngestionStatuses.has(job.status)) {
      const progress = document.createElement("div");
      progress.className = "progress";
      progress.setAttribute("aria-label", `索引进度 ${job.progress_percent}%`);
      const bar = document.createElement("i");
      bar.style.width = `${job.progress_percent}%`;
      progress.append(bar);
      const progressText = document.createElement("small");
      progressText.textContent = `${info.label} · ${job.progress_percent}%`;
      progressArea.append(progress, progressText);
    } else {
      progressArea.append(statusLabel(job.status));
    }

    const actions = document.createElement("div");
    actions.className = "task-actions";
    if (canWriteCurrentSpace() && activeIngestionStatuses.has(job.status)) {
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "danger-button";
      cancel.dataset.cancelJob = job.id;
      cancel.textContent = "取消";
      actions.append(cancel);
    } else if (
      canWriteCurrentSpace() &&
      (job.status === "failed" || job.status === "cancelled") &&
      job.attempt_count < job.max_attempts
    ) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.dataset.retryJob = job.id;
      retry.textContent = "重试";
      actions.append(retry);
    }

    row.append(type, details, progressArea, actions);
    fragment.append(row);
  });
  container.replaceChildren(fragment);
}

function scheduleIngestionPoll() {
  if (state.ingestionPollTimer) window.clearTimeout(state.ingestionPollTimer);
  state.ingestionPollTimer = null;
  if (!state.ingestionJobs.some((job) => activeIngestionStatuses.has(job.status))) return;
  state.ingestionPollTimer = window.setTimeout(() => {
    loadKnowledgeData().catch(handleAuthenticatedRequestError);
  }, 1200);
}

async function loadKnowledgeData() {
  const space = currentKnowledgeSpace();
  if (!space) {
    state.sources = [];
    state.ingestionJobs = [];
    renderKnowledgeSources();
    renderIngestionJobs();
    return;
  }
  const requestVersion = ++state.knowledgeRequestVersion;
  const [sources, jobs] = await Promise.all([
    requestJson(`/api/knowledge-spaces/${space.id}/sources`),
    requestJson(`/api/knowledge-spaces/${space.id}/ingestion-jobs?limit=50`),
  ]);
  if (requestVersion !== state.knowledgeRequestVersion || !state.identity) return;
  state.sources = sources;
  state.ingestionJobs = jobs;
  renderKnowledgeSources();
  renderIngestionJobs();
  scheduleIngestionPoll();
}

function setSourceMode(mode) {
  state.sourceMode = mode;
  document.querySelectorAll("[data-source-mode]").forEach((button) => {
    const active = button.dataset.sourceMode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-source-panel]").forEach((panel) => {
    panel.hidden = !canWriteCurrentSpace() || panel.dataset.sourcePanel !== mode;
  });
}

function selectedFile(file) {
  state.selectedFile = file ?? null;
  byId("selected-file-name").textContent = file
    ? `${file.name} · ${Math.max(1, Math.round(file.size / 1024))} KB`
    : "尚未选择文件";
  if (file && !byId("file-source-title").value.trim()) {
    byId("file-source-title").value = file.name.replace(/\.[^.]+$/, "");
  }
}

function resetSourceForms() {
  byId("file-source-form").reset();
  byId("text-source-form").reset();
  byId("faq-source-form").reset();
  selectedFile(null);
  byId("file-source-error").textContent = "";
  byId("text-source-error").textContent = "";
  byId("faq-source-error").textContent = "";
  byId("upload-zone").classList.remove("is-dragging");
  setSourceMode("file");
}

function closeSourceDetailDialog() {
  const dialog = byId("source-detail-dialog");
  if (dialog.open) dialog.close();
}

function tagsFromInput(id) {
  return [...new Set(byId(id).value.split(",").map((tag) => tag.trim()).filter(Boolean))];
}

function sourceFormErrorMessage(error) {
  const messages = {
    unsupported_file_type: "仅支持 Markdown、HTML、PDF 和 DOCX 文件。",
    upload_too_large: "文件超过 25 MB 限制。",
    empty_upload: "资料内容不能为空。",
    damaged_pdf: "PDF 无法解析，请确认文件没有损坏。",
    damaged_docx: "DOCX 无法解析，请确认文件没有损坏。",
    queue_unavailable: "任务队列暂时不可用，已保留失败记录。",
    knowledge_write_required: "当前账号没有上传权限。",
  };
  return messages[error.detail?.code] ?? error.message ?? "提交失败，请稍后重试。";
}

async function handleFileSourceSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const error = byId("file-source-error");
  error.textContent = "";
  if (!state.selectedFile) {
    error.textContent = "请先选择一个文件。";
    return;
  }
  const space = currentKnowledgeSpace();
  if (!space) return;
  submit.disabled = true;
  submit.textContent = "正在上传";
  const body = new FormData();
  body.append("file", state.selectedFile);
  body.append("title", byId("file-source-title").value.trim());
  body.append("tags", tagsFromInput("file-source-tags").join(","));
  try {
    await requestJson(`/api/knowledge-spaces/${space.id}/sources/upload`, {
      method: "POST",
      body,
    });
    form.reset();
    selectedFile(null);
    await loadKnowledgeData();
    byId("ingestion-task-list").scrollIntoView({ block: "start", behavior: "smooth" });
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) {
      handleAuthenticatedRequestError(caught);
      return;
    }
    error.textContent = sourceFormErrorMessage(caught);
  } finally {
    submit.disabled = false;
    submit.textContent = "上传并开始索引";
  }
}

async function handleTextSourceSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const error = byId("text-source-error");
  const space = currentKnowledgeSpace();
  if (!space) return;
  error.textContent = "";
  submit.disabled = true;
  submit.textContent = "正在提交";
  try {
    await requestJson(`/api/knowledge-spaces/${space.id}/sources/text`, {
      method: "POST",
      body: JSON.stringify({
        title: byId("text-source-title").value.trim(),
        source_type: byId("text-source-type").value,
        content: byId("text-source-content").value,
        tags: tagsFromInput("text-source-tags"),
      }),
    });
    form.reset();
    await loadKnowledgeData();
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) {
      handleAuthenticatedRequestError(caught);
      return;
    }
    error.textContent = sourceFormErrorMessage(caught);
  } finally {
    submit.disabled = false;
    submit.textContent = "提交并开始索引";
  }
}

async function handleFaqSourceSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const error = byId("faq-source-error");
  const space = currentKnowledgeSpace();
  if (!space) return;
  error.textContent = "";
  submit.disabled = true;
  submit.textContent = "正在创建";
  try {
    await requestJson(`/api/knowledge-spaces/${space.id}/sources/faq`, {
      method: "POST",
      body: JSON.stringify({
        title: byId("faq-source-title").value.trim(),
        items: [
          {
            question: byId("faq-question").value.trim(),
            answer: byId("faq-answer").value.trim(),
          },
        ],
        tags: tagsFromInput("faq-source-tags"),
      }),
    });
    form.reset();
    await loadKnowledgeData();
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) {
      handleAuthenticatedRequestError(caught);
      return;
    }
    error.textContent = sourceFormErrorMessage(caught);
  } finally {
    submit.disabled = false;
    submit.textContent = "创建 FAQ 来源";
  }
}

async function mutateIngestionJob(jobId, action) {
  if (action === "cancel" && !window.confirm("确认取消这个入库任务？")) return;
  await requestJson(`/api/ingestion-jobs/${jobId}/${action}`, { method: "POST" });
  await loadKnowledgeData();
}

async function openSourceDetail(sourceId) {
  const detail = await requestJson(`/api/sources/${sourceId}`);
  state.activeSourceId = sourceId;
  byId("source-detail-title").textContent = detail.title;
  byId("source-detail-type").textContent =
    sourceTypeNames[detail.source_type] ?? detail.source_type.toUpperCase();
  byId("source-detail-status").replaceChildren(
    statusLabel(detail.latest_job_status ?? detail.status),
  );
  byId("source-detail-version").textContent = `版本 ${detail.current_version}`;
  byId("source-detail-hash").textContent = detail.content_hash.slice(0, 20);
  byId("source-detail-error").textContent = "";
  byId("source-reindex").dataset.sourceId = sourceId;
  byId("source-reindex").hidden = !canWriteCurrentSpace();

  const versions = document.createDocumentFragment();
  detail.documents.forEach((documentVersion) => {
    const row = document.createElement("div");
    row.className = "version-row";
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    const meta = document.createElement("small");
    title.textContent = `版本 ${documentVersion.version_number}`;
    meta.textContent = `${documentVersion.chunk_count} 个分块 · ${documentVersion.language}`;
    copy.append(title, meta);
    row.append(copy, statusLabel(documentVersion.status));
    versions.append(row);
  });
  byId("source-version-list").replaceChildren(versions);

  const events = document.createDocumentFragment();
  (detail.latest_job?.events ?? []).forEach((event) => {
    const item = document.createElement("li");
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    const meta = document.createElement("small");
    title.textContent = event.summary;
    meta.textContent = `${event.progress_percent}% · ${formatHistoryTime(event.created_at)}`;
    copy.append(title, meta);
    item.append(copy, statusLabel(event.status));
    events.append(item);
  });
  byId("source-event-list").replaceChildren(events);

  const dialog = byId("source-detail-dialog");
  if (!dialog.open) dialog.showModal();
}

async function reindexActiveSource() {
  if (!state.activeSourceId) return;
  if (!window.confirm("确认创建新文档版本并重新索引？旧版本会保留用于历史审计。")) return;
  const button = byId("source-reindex");
  button.disabled = true;
  button.textContent = "正在排队";
  byId("source-detail-error").textContent = "";
  try {
    await requestJson(`/api/sources/${state.activeSourceId}/reindex`, {
      method: "POST",
    });
    byId("source-detail-dialog").close();
    await loadKnowledgeData();
    setView("upload", "space");
  } catch (error) {
    byId("source-detail-error").textContent = sourceFormErrorMessage(error);
  } finally {
    button.disabled = false;
    button.textContent = "重新索引";
  }
}

function clearCreatedKeyReveal() {
  const reveal = byId("created-key-reveal");
  const value = byId("created-key-value");
  if (!reveal || !value) return;
  reveal.hidden = true;
  value.textContent = "";
}

function resetAccountScopedState() {
  state.answerAbortController?.abort();
  if (state.pendingAnswerScrollFrame) {
    window.cancelAnimationFrame(state.pendingAnswerScrollFrame);
  }
  if (state.ingestionPollTimer) {
    window.clearTimeout(state.ingestionPollTimer);
  }

  state.identity = null;
  state.snapshot = null;
  state.answer = null;
  state.question = defaultQuestion;
  state.messages = [];
  state.history = [];
  state.historyExpanded = false;
  state.currentConversationId = null;
  state.answerAbortController = null;
  state.pendingAnswerScrollFrame = null;
  state.activeAssistantContent = null;
  state.previewReturn = "space";
  state.sources = [];
  state.ingestionJobs = [];
  state.ingestionPollTimer = null;
  state.knowledgeRequestVersion += 1;
  state.selectedFile = null;
  state.activeSourceId = null;
  state.sourceMode = "file";

  byId("question-input").value = defaultQuestion;
  byId("follow-input").value = "";
  byId("global-search").value = "";
  byId("answer-question").textContent = defaultQuestion;
  clearAnswerThread();
  byId("event-steps").replaceChildren();
  byId("citation-list").replaceChildren();
  byId("next-actions").replaceChildren();
  byId("access-key-list").replaceChildren();
  byId("access-key-count").textContent = "0 条";
  byId("document-list").replaceChildren();
  byId("ingestion-task-list").replaceChildren();
  resetSourceForms();
  closeSourceDetailDialog();
  renderConversationHistory();
  clearCreatedKeyReveal();
}

function showAuthGate(message = "") {
  resetAccountScopedState();
  byId("app-shell").hidden = true;
  byId("auth-gate").hidden = false;
  byId("user-menu-popover").hidden = true;
  byId("user-menu-trigger").setAttribute("aria-expanded", "false");
  byId("auth-error").textContent = message;
  window.setTimeout(() => byId("auth-username").focus(), 0);
}

function showApplication() {
  byId("auth-gate").hidden = true;
  byId("app-shell").hidden = false;
}

async function loadSessionStatus() {
  return requestJson("/api/auth/session");
}

async function loadAuthenticatedWorkspace() {
  const snapshot = await requestJson("/api/workspace");
  state.snapshot = snapshot;
  renderWorkspace(snapshot);
  state.history = loadConversationHistory();
  state.historyExpanded = false;
  renderConversationHistory();
  showApplication();
}

function handleAuthenticatedRequestError(error) {
  if (error instanceof ApiError && error.status === 401) {
    showAuthGate("会话已失效，请重新输入激活密钥。");
    return;
  }
  console.error(error);
}

async function handleAuthSubmit(event) {
  event.preventDefault();
  const submitButton = byId("auth-submit");
  const username = byId("auth-username").value.trim();
  const accessKey = byId("auth-key").value.trim();
  byId("auth-error").textContent = "";
  submitButton.disabled = true;
  submitButton.textContent = "正在验证";

  try {
    await requestJson("/api/auth/bind", {
      method: "POST",
      body: JSON.stringify({ username, access_key: accessKey }),
    });
    byId("auth-key").value = "";
    await loadAuthenticatedWorkspace();
    setView("home", "home");
  } catch (error) {
    if (error instanceof ApiError) {
      const messages = {
        invalid_credentials: "用户名或激活密钥无效。",
        too_many_attempts: "失败次数过多，请稍后再试。",
      };
      byId("auth-error").textContent =
        messages[error.detail?.code] ?? "暂时无法完成登录，请稍后重试。";
    } else {
      console.error(error);
      byId("auth-error").textContent = "无法连接 Curx 服务，请检查服务是否运行。";
    }
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "进入 Curx";
  }
}

async function handleLogout() {
  try {
    await requestJson("/api/auth/logout", { method: "POST" });
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 401)) console.error(error);
  }
  showAuthGate("已退出当前账号。");
}

function formatShortDate(value) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

function renderAccessKeys(accessKeys) {
  const container = byId("access-key-list");
  const fragment = document.createDocumentFragment();
  const statusNames = {
    active: "有效",
    scheduled: "待生效",
    expired: "已过期",
    revoked: "已撤销",
  };
  byId("access-key-count").textContent = `${accessKeys.length} 条`;

  if (!accessKeys.length) {
    const empty = document.createElement("p");
    empty.className = "empty-key-list";
    empty.textContent = "尚未创建激活密钥。";
    container.replaceChildren(empty);
    return;
  }

  accessKeys.forEach((accessKey) => {
    const row = document.createElement("div");
    row.className = "key-row";

    const details = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = accessKey.label;
    const meta = document.createElement("small");
    const binding = accessKey.bound_username
      ? `已绑定 ${accessKey.bound_username}`
      : "尚未绑定";
    meta.textContent =
      `${accessKey.prefix} · ${binding} · 到期 ${formatShortDate(accessKey.expires_at)}`;
    details.append(title, meta);

    const actions = document.createElement("div");
    actions.className = "key-row-actions";
    const status = document.createElement("span");
    status.className = `state-label ${accessKey.status === "active" ? "success" : ""}`;
    status.textContent = statusNames[accessKey.status] ?? accessKey.status;
    actions.append(status);

    if (accessKey.status === "active" || accessKey.status === "scheduled") {
      const revoke = document.createElement("button");
      revoke.className = "danger-button";
      revoke.type = "button";
      revoke.dataset.revokeKey = accessKey.id;
      revoke.dataset.revokeLabel = accessKey.label;
      revoke.textContent = "撤销";
      actions.append(revoke);
    }

    row.append(details, actions);
    fragment.append(row);
  });
  container.replaceChildren(fragment);
}

async function loadAccessKeys() {
  if (state.identity?.role !== "admin") return;
  const accessKeys = await requestJson("/api/admin/access-keys");
  renderAccessKeys(accessKeys);
}

async function handleAccessKeySubmit(event) {
  event.preventDefault();
  const submitButton = byId("create-access-key");
  const currentSpace = state.snapshot?.spaces?.[0];
  const scope = byId("key-scope").value;
  const expiry = byId("key-expiry").value;
  byId("key-form-error").textContent = "";
  clearCreatedKeyReveal();

  if (!expiry || (scope === "current" && !currentSpace)) {
    byId("key-form-error").textContent = "请选择有效期并确认当前知识空间。";
    return;
  }

  submitButton.disabled = true;
  submitButton.textContent = "正在创建";
  try {
    const created = await requestJson("/api/admin/access-keys", {
      method: "POST",
      body: JSON.stringify({
        label: byId("key-label").value.trim(),
        granted_role: byId("key-role").value,
        expires_at: new Date(`${expiry}T23:59:59`).toISOString(),
        all_spaces: scope === "all",
        knowledge_space_ids: scope === "current" ? [currentSpace.id] : [],
      }),
    });
    byId("created-key-value").textContent = created.access_key;
    byId("created-key-reveal").hidden = false;
    byId("key-label").value = "";
    await loadAccessKeys();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showAuthGate("会话已失效，请重新输入激活密钥。");
      return;
    }
    console.error(error);
    byId("key-form-error").textContent =
      error instanceof ApiError ? error.message : "创建失败，请稍后重试。";
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "创建激活密钥";
  }
}

async function copyCreatedKey() {
  const value = byId("created-key-value").textContent;
  if (!value) return;
  await navigator.clipboard.writeText(value);
  byId("copy-created-key").textContent = "已复制";
  window.setTimeout(() => {
    byId("copy-created-key").textContent = "复制";
  }, 1200);
}

async function revokeAccessKey(accessKeyId, label) {
  const confirmed = window.confirm(`确认撤销“${label}”？已绑定会话会立即失效。`);
  if (!confirmed) return;
  try {
    await requestJson(`/api/admin/access-keys/${accessKeyId}`, { method: "DELETE" });
    await loadAccessKeys();
  } catch (error) {
    handleAuthenticatedRequestError(error);
  }
}

function followAnswerOutput() {
  if (state.pendingAnswerScrollFrame) return;

  state.pendingAnswerScrollFrame = window.requestAnimationFrame(() => {
    state.pendingAnswerScrollFrame = null;
    (state.activeAssistantContent ?? byId("answer-thread")).scrollIntoView({
      block: "end",
      inline: "nearest",
      behavior: "auto",
    });
  });
}

function clearAnswerThread() {
  state.activeAssistantContent = null;
  byId("answer-thread").replaceChildren();
}

function appendConversationMessage(role, content, options = {}) {
  const block = document.createElement("article");
  block.className = `message-block ${role}`;

  const meta = document.createElement("div");
  meta.className = "message-meta";

  const roleLabel = document.createElement("span");
  roleLabel.className = `message-role ${role}`;
  roleLabel.textContent = role === "user" ? "USER" : "AI";

  const label = document.createElement("span");
  label.textContent = role === "user" ? "用户提问" : "助手回答";

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";

  const copy = document.createElement("div");
  copy.className = role === "assistant" ? "answer-copy" : "question-copy";

  if (options.thinking) {
    renderThinkingInto(copy);
  } else if (role === "assistant") {
    renderMarkdown(copy, content);
  } else {
    copy.textContent = content;
  }

  meta.append(roleLabel, label);
  bubble.append(copy);
  block.append(meta, bubble);
  byId("answer-thread").append(block);

  return copy;
}

function renderConversationTranscript(messages) {
  clearAnswerThread();

  messages.forEach((message) => {
    if (message.role === "system") return;
    appendConversationMessage(message.role, message.content);
  });
}

function renderEvents(events) {
  const list = byId("event-steps");
  list.replaceChildren();

  events.forEach((event) => {
    const item = document.createElement("li");
    const marker = document.createElement("span");
    const label = document.createElement("strong");
    const summary = document.createElement("small");

    label.textContent = event.label;
    summary.textContent = event.summary;
    item.title = `${event.summary} · ${event.duration_ms}ms`;
    item.append(marker, label, summary);
    list.append(item);
  });
}

function renderCitations(citations) {
  const list = byId("citation-list");
  list.replaceChildren();

  if (!citations.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "本轮暂未引用知识库。";
    list.append(empty);
    return;
  }

  citations.forEach((citation, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "citation-item";
    button.dataset.citationIndex = index;

    const heading = document.createElement("span");
    const title = document.createElement("strong");
    const score = document.createElement("small");
    const excerpt = document.createElement("p");
    const location = document.createElement("small");

    title.textContent = `${citation.order}. ${citation.title}`;
    score.textContent = `${Math.round(citation.score * 100)}%`;
    excerpt.textContent = citation.excerpt;
    location.textContent = `第 ${citation.page ?? "-"} 页 · ${citation.location}`;

    heading.append(title, score);
    button.append(heading, excerpt, location);
    list.append(button);
  });
}

function renderNextActions(actions) {
  const list = byId("next-actions");
  list.replaceChildren();

  actions.forEach((action) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.nextAction = action;
    button.textContent = action;
    list.append(button);
  });
}

function renderAnswer(answer) {
  state.answer = answer;
  renderAnswerContent(answer.answer);
  renderAnswerMeta(answer);
  followAnswerOutput();
}

function renderAnswerMeta(answer) {
  byId("confidence-pill").textContent =
    answer.confidence === "模型" ? "模型回答" : `${answer.confidence}可信`;
  byId("confidence-pill").className =
    answer.confidence === "高" ? "state-label success" : "state-label";
  renderEvents(answer.events);
  renderCitations(answer.citations);
  renderNextActions(answer.next_actions);
}

function renderAnswerError() {
  renderAnswerContent("回答暂时无法生成，请确认服务已启动后重试。");
  byId("confidence-pill").textContent = "生成失败";
  byId("confidence-pill").className = "state-label";
  renderEvents([]);
  renderCitations([]);
  renderNextActions(["重新提问"]);
}

function renderStreamError(summary) {
  renderAnswerContent(summary || "回答暂时无法生成，请确认服务已启动后重试。");
  byId("confidence-pill").textContent = "生成失败";
  byId("confidence-pill").className = "state-label";
  renderNextActions(["重新提问"]);
  followAnswerOutput();
}

function renderAnswerContent(markdown) {
  const answerText =
    state.activeAssistantContent ?? appendConversationMessage("assistant", "", { thinking: false });
  state.activeAssistantContent = answerText;
  answerText.classList.remove("is-thinking");
  renderMarkdown(answerText, markdown);
}

function renderThinkingInto(answerText) {
  const label = document.createElement("span");
  label.className = "thinking-copy";
  label.textContent = "AI 正在思考中";
  answerText.classList.add("is-thinking");
  answerText.replaceChildren(label);
}

function renderThinkingState() {
  state.activeAssistantContent = appendConversationMessage("assistant", "", { thinking: true });
}

async function openAnswer(question, options = {}) {
  const continueThread = Boolean(options.continueThread);
  const finalQuestion = question.trim() || defaultQuestion;
  state.answerAbortController?.abort();
  state.answerAbortController = new AbortController();

  if (!continueThread) {
    state.messages = [];
    state.currentConversationId = null;
    clearAnswerThread();
  }
  state.messages.push({ role: "user", content: finalQuestion });
  state.question = finalQuestion;
  byId("answer-question").textContent = finalQuestion;
  appendConversationMessage("user", finalQuestion);
  renderThinkingState();
  byId("confidence-pill").textContent = "思考中";
  byId("confidence-pill").className = "state-label";
  byId("follow-input").value = "";
  renderEvents([]);
  renderCitations([]);
  renderNextActions([]);
  setView("answer", "home");
  followAnswerOutput();

  const streamEvents = [];
  let streamedText = "";

  try {
    await requestSse(
      "/api/chat/stream",
      {
        messages: state.messages,
        knowledge_space_id: state.snapshot?.spaces?.[0]?.id ?? null,
      },
      ({ event, data }) => {
        if (event === "answer.started" || event === "answer.generating") {
          streamEvents.push(data);
          renderEvents(streamEvents);
          byId("confidence-pill").textContent = "思考中";
          return;
        }

        if (event === "answer.delta") {
          streamedText += data.text ?? "";
          if (streamedText) renderAnswerContent(streamedText);
          followAnswerOutput();
          return;
        }

        if (event === "answer.completed") {
          renderAnswer(data);
          state.messages.push({ role: "assistant", content: data.answer });
          saveCurrentConversation(data);
          state.answerAbortController = null;
          return;
        }

        if (event === "answer.failed") {
          streamEvents.push(data);
          renderEvents(streamEvents);
          renderStreamError(data.summary);
        }
      },
      state.answerAbortController.signal,
    );
  } catch (error) {
    if (error.name === "AbortError") return;
    if (error instanceof ApiError && error.status === 401) {
      showAuthGate("会话已失效，请重新输入激活密钥。");
      return;
    }
    console.error(error);
    renderAnswerError();
  } finally {
    if (!state.answerAbortController?.signal.aborted) {
      state.answerAbortController = null;
    }
  }
}

function sourceForCitation(citation) {
  return state.snapshot?.sources?.find((source) => source.id === citation?.source_id);
}

function openPreview(returnView, citation = null) {
  state.previewReturn = returnView;
  const source = citation ? sourceForCitation(citation) : state.snapshot?.sources?.[0];
  const title = citation?.title ?? `${source?.title ?? "产品规格书"} ${source?.version ?? "v2.3.1"}`;
  const page = citation?.page ?? source?.page ?? 12;
  const location = citation?.location ?? source?.location ?? "3.2 电池与充电规格";
  const excerpt = citation?.excerpt ?? source?.excerpt ?? "充电截止电压为 4.20V（±0.05V）。";
  const score = citation?.score ?? 0.94;

  byId("preview-title").textContent = title;
  byId("preview-location").textContent = `第 ${page} 页 · ${location}`;
  byId("preview-excerpt").textContent = excerpt;
  byId("preview-source").textContent = title;
  byId("preview-meta").textContent = `第 ${page} 页 · ${location}`;
  byId("preview-score").textContent = `${Math.round(score * 100)}%`;
  byId("preview-relevance").textContent = score >= 0.85 ? "高相关" : "中相关";
  byId("preview-back-label").textContent = returnView === "answer" ? "返回回答" : "返回知识空间";
  setView("preview", returnView === "answer" ? "home" : "space");
}

function openSearch() {
  const dialog = byId("search-dialog");
  if (!dialog.open) dialog.showModal();
  byId("global-search").focus();
}

function closeSearch() {
  const dialog = byId("search-dialog");
  if (dialog.open) dialog.close();
}

function submitTextareaOnEnter(textareaId, formId) {
  const textarea = byId(textareaId);
  const form = byId(formId);

  textarea.addEventListener("keydown", (event) => {
    const isConfirmingImeInput = event.isComposing || event.keyCode === 229;
    if (event.key !== "Enter" || event.shiftKey || isConfirmingImeInput) return;

    event.preventDefault();
    if (!textarea.value.trim()) return;
    form.requestSubmit();
  });
}

function handleDelegatedClick(event) {
  const sourceModeButton = event.target.closest("[data-source-mode]");
  if (sourceModeButton) {
    setSourceMode(sourceModeButton.dataset.sourceMode);
    return;
  }

  const revokeButton = event.target.closest("[data-revoke-key]");
  if (revokeButton) {
    revokeAccessKey(revokeButton.dataset.revokeKey, revokeButton.dataset.revokeLabel);
    return;
  }

  const historyButton = event.target.closest("[data-history-id]");
  if (historyButton) {
    openConversationHistory(historyButton.dataset.historyId);
    return;
  }

  const citationButton = event.target.closest("[data-citation-index]");
  if (citationButton) {
    const citation = state.answer?.citations?.[Number(citationButton.dataset.citationIndex)];
    openPreview("answer", citation);
    return;
  }

  const previewButton = event.target.closest("[data-preview-from]");
  if (previewButton) {
    openPreview(previewButton.dataset.previewFrom);
    return;
  }

  const sourceButton = event.target.closest("[data-source-id]");
  if (sourceButton) {
    openSourceDetail(sourceButton.dataset.sourceId).catch(handleAuthenticatedRequestError);
    return;
  }

  const cancelJobButton = event.target.closest("[data-cancel-job]");
  if (cancelJobButton) {
    mutateIngestionJob(cancelJobButton.dataset.cancelJob, "cancel").catch(
      handleAuthenticatedRequestError,
    );
    return;
  }

  const retryJobButton = event.target.closest("[data-retry-job]");
  if (retryJobButton) {
    mutateIngestionJob(retryJobButton.dataset.retryJob, "retry").catch(
      handleAuthenticatedRequestError,
    );
    return;
  }

  const closeSourceDialogButton = event.target.closest("[data-close-source-dialog]");
  if (closeSourceDialogButton) {
    closeSourceDetailDialog();
    return;
  }

  const questionButton = event.target.closest("[data-question]");
  if (questionButton) {
    closeSearch();
    openAnswer(questionButton.dataset.question);
    return;
  }

  const actionButton = event.target.closest("[data-next-action]");
  if (actionButton) {
    openAnswer(`${actionButton.dataset.nextAction}：${state.question}`, { continueThread: true });
    return;
  }

  const viewButton = event.target.closest("[data-view]");
  if (viewButton) {
    closeSearch();
    setView(viewButton.dataset.view);
  }
}

async function init() {
  document.addEventListener("click", handleDelegatedClick);
  byId("auth-form").addEventListener("submit", handleAuthSubmit);
  byId("logout-button").addEventListener("click", handleLogout);
  byId("user-menu-trigger").addEventListener("click", (event) => {
    event.stopPropagation();
    const popover = byId("user-menu-popover");
    popover.hidden = !popover.hidden;
    byId("user-menu-trigger").setAttribute("aria-expanded", String(!popover.hidden));
  });
  document.addEventListener("click", (event) => {
    if (event.target.closest(".user-menu")) return;
    byId("user-menu-popover").hidden = true;
    byId("user-menu-trigger").setAttribute("aria-expanded", "false");
  });

  byId("access-key-form").addEventListener("submit", handleAccessKeySubmit);
  byId("refresh-access-keys").addEventListener("click", () => {
    loadAccessKeys().catch(handleAuthenticatedRequestError);
  });
  byId("copy-created-key").addEventListener("click", () => {
    copyCreatedKey().catch((error) => {
      console.error(error);
      byId("key-form-error").textContent = "复制失败，请手动选择密钥文本。";
    });
  });
  const defaultExpiry = new Date();
  defaultExpiry.setDate(defaultExpiry.getDate() + 30);
  byId("key-expiry").value = defaultExpiry.toISOString().slice(0, 10);

  byId("history-toggle").addEventListener("click", toggleConversationHistory);

  byId("ask-form").addEventListener("submit", (event) => {
    event.preventDefault();
    openAnswer(byId("question-input").value);
  });

  byId("follow-form").addEventListener("submit", (event) => {
    event.preventDefault();
    openAnswer(byId("follow-input").value, { continueThread: true });
  });
  submitTextareaOnEnter("question-input", "ask-form");
  submitTextareaOnEnter("follow-input", "follow-form");

  byId("preview-back").addEventListener("click", () => {
    setView(state.previewReturn, state.previewReturn === "answer" ? "home" : "space");
  });

  byId("file-source-form").addEventListener("submit", handleFileSourceSubmit);
  byId("text-source-form").addEventListener("submit", handleTextSourceSubmit);
  byId("faq-source-form").addEventListener("submit", handleFaqSourceSubmit);
  byId("source-file").addEventListener("change", (event) => {
    selectedFile(event.currentTarget.files?.[0] ?? null);
  });
  byId("upload-zone").addEventListener("dragenter", (event) => {
    event.preventDefault();
    byId("upload-zone").classList.add("is-dragging");
  });
  byId("upload-zone").addEventListener("dragover", (event) => {
    event.preventDefault();
    byId("upload-zone").classList.add("is-dragging");
  });
  byId("upload-zone").addEventListener("dragleave", (event) => {
    if (event.target === byId("upload-zone")) {
      byId("upload-zone").classList.remove("is-dragging");
    }
  });
  byId("upload-zone").addEventListener("drop", (event) => {
    event.preventDefault();
    byId("upload-zone").classList.remove("is-dragging");
    selectedFile(event.dataTransfer?.files?.[0] ?? null);
  });
  byId("refresh-ingestion").addEventListener("click", () => {
    loadKnowledgeData().catch(handleAuthenticatedRequestError);
  });
  byId("source-detail-close").addEventListener("click", closeSourceDetailDialog);
  byId("source-detail-dialog").addEventListener("click", (event) => {
    if (event.target === byId("source-detail-dialog")) closeSourceDetailDialog();
  });
  byId("source-reindex").addEventListener("click", () => {
    reindexActiveSource().catch(handleAuthenticatedRequestError);
  });
  setSourceMode("file");

  byId("search-trigger").addEventListener("click", openSearch);
  byId("search-close").addEventListener("click", closeSearch);
  byId("search-dialog").addEventListener("click", (event) => {
    if (event.target === byId("search-dialog")) closeSearch();
  });
  byId("search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const query = byId("global-search").value.trim();
    closeSearch();
    openAnswer(query || defaultQuestion);
  });
  byId("global-search").addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const query = event.currentTarget.value.trim();
    closeSearch();
    openAnswer(query || defaultQuestion);
  });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      openSearch();
    }
  });

  try {
    const session = await loadSessionStatus();
    if (!session.authenticated) {
      showAuthGate();
      return;
    }
    await loadAuthenticatedWorkspace();
    setView("home", "home");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showAuthGate();
    } else {
      console.error(error);
      showAuthGate("无法连接 Curx 服务，请确认后端已在 8020 端口运行。");
    }
  }
}

init();
