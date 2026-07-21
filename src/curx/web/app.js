const defaultQuestion = "电池充电截止电压是多少？";
const conversationHistoryKey = "curx.conversation-history.v1";
const collapsedHistoryLimit = 5;

const state = {
  snapshot: null,
  answer: null,
  question: defaultQuestion,
  messages: [],
  history: [],
  historyExpanded: false,
  currentConversationId: null,
  answerAbortController: null,
  pendingAnswerScrollFrame: null,
  previewReturn: "space",
};

const byId = (id) => document.getElementById(id);

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json();
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
    throw new Error(`Request failed: ${response.status}`);
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

  window.scrollTo({ top: 0, behavior: "instant" });
}

function loadConversationHistory() {
  try {
    const parsed = JSON.parse(localStorage.getItem(conversationHistoryKey) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => item?.id && item?.answer) : [];
  } catch (error) {
    console.warn("Conversation history could not be loaded.", error);
    return [];
  }
}

function persistConversationHistory() {
  try {
    localStorage.setItem(conversationHistoryKey, JSON.stringify(state.history));
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
  renderAnswer(conversation.answer);
  setView("answer", "home");
}

function renderWorkspace(snapshot) {
  const activeSpace = snapshot.spaces[0];
  if (!activeSpace) return;

  byId("top-space-name").textContent = activeSpace.name;
  byId("home-space-name").textContent = activeSpace.name;
  byId("home-doc-count").textContent = activeSpace.document_count;
  byId("space-doc-count").textContent = activeSpace.document_count;
  byId("space-health").textContent = `${activeSpace.health_percent}%`;
}

function followAnswerOutput() {
  if (state.pendingAnswerScrollFrame) return;

  state.pendingAnswerScrollFrame = window.requestAnimationFrame(() => {
    state.pendingAnswerScrollFrame = null;
    byId("answer-text").scrollIntoView({
      block: "end",
      inline: "nearest",
      behavior: "auto",
    });
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
  byId("confidence-pill").textContent =
    answer.confidence === "模型" ? "模型回答" : `${answer.confidence}可信`;
  byId("confidence-pill").className =
    answer.confidence === "高" ? "state-label success" : "state-label";
  renderEvents(answer.events);
  renderCitations(answer.citations);
  renderNextActions(answer.next_actions);
  followAnswerOutput();
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
  const answerText = byId("answer-text");
  answerText.classList.remove("is-thinking");
  renderMarkdown(answerText, markdown);
}

function renderThinkingState() {
  const answerText = byId("answer-text");
  const label = document.createElement("span");
  label.className = "thinking-copy";
  label.textContent = "AI 正在思考中";
  answerText.classList.add("is-thinking");
  answerText.replaceChildren(label);
}

async function openAnswer(question, options = {}) {
  const continueThread = Boolean(options.continueThread);
  const finalQuestion = question.trim() || defaultQuestion;
  state.answerAbortController?.abort();
  state.answerAbortController = new AbortController();

  if (!continueThread) {
    state.messages = [];
    state.currentConversationId = null;
  }
  state.messages.push({ role: "user", content: finalQuestion });
  state.question = finalQuestion;
  byId("answer-question").textContent = finalQuestion;
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
        knowledge_space_id: null,
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

function simulateParse() {
  byId("parse-progress").style.width = "100%";
  byId("parse-status").textContent = "解析完成，已生成 46 条结构化切片";
  byId("start-parse").textContent = "解析完成";
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
  state.history = loadConversationHistory();
  renderConversationHistory();
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

  byId("start-parse").addEventListener("click", simulateParse);
  byId("upload-zone").addEventListener("click", simulateParse);
  byId("upload-zone").addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      simulateParse();
    }
  });
  byId("upload-zone").addEventListener("dragover", (event) => event.preventDefault());
  byId("upload-zone").addEventListener("drop", (event) => {
    event.preventDefault();
    simulateParse();
  });

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

  byId("save-settings").addEventListener("click", () => {
    byId("save-settings").textContent = "已保存";
    window.setTimeout(() => {
      byId("save-settings").textContent = "保存更改";
    }, 1200);
  });

  try {
    state.snapshot = await requestJson("/api/demo/workspace");
    renderWorkspace(state.snapshot);
  } catch (error) {
    console.error(error);
  }

  setView("home", "home");
}

init();
