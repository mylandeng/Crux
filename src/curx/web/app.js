const defaultQuestion = "电池充电截止电压是多少？";

const byId = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value).replace(/[&<>"]/g, (char) => {
    const entities = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
    return entities[char];
  });
}

function setView(view) {
  document.querySelectorAll(".nav-item[data-view], .flow-tab[data-view]").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((section) => {
    section.classList.toggle("active", section.id === `view-${view}`);
  });
}

function answerFor(question) {
  if (question.includes("截止电压") || question.includes("4.20")) {
    return "标准充电条件下，单节锂电池充电截止电压为 <b>4.20V（±0.05V）</b>。";
  }
  if (question.includes("步骤") || question.includes("排查")) {
    return "静态演示步骤：先确认充电规格与 BMS 阈值，再核对温度采样、绝缘告警和充电终止电流。";
  }
  return `针对“${escapeHtml(question)}”，这里展示前端静态演示回答；后续接入后端后再返回真实检索与引用。`;
}

function openAnswer(question) {
  const finalQuestion = question || defaultQuestion;
  setView("answer");
  byId("answer-question").textContent = finalQuestion;
  byId("answer-text").innerHTML = answerFor(finalQuestion);
  byId("follow-input").value = "";
}

function simulateParse() {
  byId("parse-progress").style.width = "100%";
  byId("parse-status").textContent = "解析完成，已生成 46 条结构化切片";
  byId("start-parse").textContent = "解析完成";
}

function init() {
  document.addEventListener("click", (event) => {
    const viewButton = event.target.closest("[data-view]");
    if (viewButton) setView(viewButton.dataset.view);

    const questionButton = event.target.closest("[data-question]");
    if (questionButton) openAnswer(questionButton.dataset.question);
  });

  byId("ask-form").addEventListener("submit", (event) => {
    event.preventDefault();
    openAnswer(byId("question-input").value.trim() || defaultQuestion);
  });

  byId("follow-form").addEventListener("submit", (event) => {
    event.preventDefault();
    openAnswer(byId("follow-input").value.trim() || defaultQuestion);
  });

  byId("upload-entry").addEventListener("click", () => setView("upload"));
  byId("start-parse").addEventListener("click", simulateParse);
  byId("upload-zone").addEventListener("click", simulateParse);
  byId("upload-zone").addEventListener("keydown", (event) => {
    if (event.key === "Enter") simulateParse();
  });
  byId("upload-zone").addEventListener("dragover", (event) => event.preventDefault());
  byId("upload-zone").addEventListener("drop", (event) => {
    event.preventDefault();
    simulateParse();
  });

  byId("global-search").addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    openAnswer(event.target.value.trim() || defaultQuestion);
  });

  byId("save-settings").addEventListener("click", () => {
    byId("save-settings").textContent = "已保存";
    window.setTimeout(() => {
      byId("save-settings").textContent = "保存设置";
    }, 1200);
  });

  setView("home");
}

init();
