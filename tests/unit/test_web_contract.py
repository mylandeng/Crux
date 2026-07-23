from pathlib import Path

APP_JS = Path(__file__).parents[2] / "src" / "curx" / "web" / "app.js"


def test_auth_gate_clears_account_scoped_browser_state() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    reset_start = source.index("function resetAccountScopedState()")
    reset_end = source.index("function showAuthGate", reset_start)
    reset_body = source[reset_start:reset_end]
    gate_end = source.index("function showApplication", reset_end)
    gate_body = source[reset_end:gate_end]

    for required_reset in (
        "state.messages = [];",
        "state.history = [];",
        "state.currentConversationId = null;",
        "state.sources = [];",
        "state.ingestionJobs = [];",
        "state.selectedFile = null;",
        'byId("question-input").value = defaultQuestion;',
        'byId("follow-input").value = "";',
        'byId("global-search").value = "";',
        'byId("access-key-list").replaceChildren();',
        "resetSourceForms();",
        "closeSourceDetailDialog();",
    ):
        assert required_reset in reset_body

    assert "resetAccountScopedState();" in gate_body


def test_ingestion_ui_uses_real_handlers_instead_of_demo_parse() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    init_start = source.index("async function init()")
    init_body = source[init_start:]

    for required_listener in (
        'byId("file-source-form").addEventListener("submit", handleFileSourceSubmit);',
        'byId("text-source-form").addEventListener("submit", handleTextSourceSubmit);',
        'byId("faq-source-form").addEventListener("submit", handleFaqSourceSubmit);',
        'byId("refresh-ingestion").addEventListener("click", () => {',
        'byId("source-reindex").addEventListener("click", () => {',
        'selectedFile(event.dataTransfer?.files?.[0] ?? null);',
        'setSourceMode("file");',
    ):
        assert required_listener in init_body

    for removed_demo_reference in (
        "function simulateParse()",
        'byId("start-parse")',
        'byId("parse-progress")',
        'byId("parse-status")',
    ):
        assert removed_demo_reference not in source


def test_ingestion_workspace_and_click_delegation_cover_real_interactions() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    workspace_start = source.index("function renderWorkspace(snapshot) {")
    workspace_end = source.index("const ingestionStatusInfo =", workspace_start)
    workspace_body = source[workspace_start:workspace_end]
    click_start = source.index("function handleDelegatedClick(event) {")
    click_end = source.index("async function init()", click_start)
    click_body = source[click_start:click_end]

    assert "setSourceMode(state.sourceMode);" in workspace_body

    for delegated_control in (
        'event.target.closest("[data-source-mode]")',
        'event.target.closest("[data-source-id]")',
        'event.target.closest("[data-cancel-job]")',
        'event.target.closest("[data-retry-job]")',
        'event.target.closest("[data-close-source-dialog]")',
        "openSourceDetail(sourceButton.dataset.sourceId).catch(handleAuthenticatedRequestError);",
        'mutateIngestionJob(cancelJobButton.dataset.cancelJob, "cancel").catch(',
        'mutateIngestionJob(retryJobButton.dataset.retryJob, "retry").catch(',
    ):
        assert delegated_control in click_body


def test_boot_sequence_checks_auth_session_before_loading_workspace() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    init_start = source.index("async function init() {")
    init_body = source[init_start:]

    assert 'return requestJson("/api/auth/session");' in source
    assert "const session = await loadSessionStatus();" in init_body
    assert "if (!session.authenticated) {" in init_body
    assert "showAuthGate();" in init_body
