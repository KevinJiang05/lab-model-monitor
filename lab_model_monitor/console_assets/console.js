"use strict";
const $ = (id) => document.getElementById(id);
const form = $("settings-form");
const tabs = ["overview", "detection", "connections", "history"];
const names = {
  success: "已完成", failed: "存在异常", running: "运行中", passed: "通过",
  wrong_answer: "答错", format_error: "格式错误", timeout: "超时", api_error: "接口失败",
  incomplete: "回答截断", generated: "HTML 已生成（未视觉评分）", Ready: "等待运行", Disabled: "已暂停", Running: "运行中",
  not_installed: "未安装", unavailable: "无法读取", unsupported: "不支持",
};
let state, dirty = false, saving = false, pendingAction = false;
let timer, noticeTimer, completedJob, runSignature, latestSignature = null;
let currentTab = "overview", availableModels = [];
const date = (value) => value ? new Date(value).toLocaleString("zh-CN", {timeZone: "Asia/Taipei", hour12: false}) : "—";

function setTab(name, focus = false) {
  currentTab = tabs.includes(name) ? name : "overview";
  for (const tab of tabs) {
    const selected = tab === currentTab;
    $("panel-" + tab).hidden = !selected;
    $("tab-" + tab).setAttribute("aria-selected", String(selected));
    $("tab-" + tab).tabIndex = selected ? 0 : -1;
  }
  history.replaceState(null, "", "#" + currentTab);
  if (focus) $("tab-" + currentTab).focus();
  editState();
}

function notice(message, error = false) {
  clearTimeout(noticeTimer);
  $("notice").hidden = false;
  $("notice-message").textContent = message;
  $("notice").className = error ? "notice error" : "notice";
  if (!error) noticeTimer = setTimeout(() => { $("notice").hidden = true; }, 4000);
}

async function api(path, payload) {
  const response = await fetch(path, payload ? {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
  } : {cache: "no-store"});
  const result = await response.json();
  if (!response.ok) {
    const errors = {
      operation_running: "已有操作运行中。",
      invalid_settings_or_credentials: "保存失败，请检查设置和所启用渠道的凭据。",
      save_or_operation_failed: "保存或任务更新失败，已尝试恢复原配置。请刷新检查任务状态。",
      invalid_request_or_configuration: "无法读取配置，请检查 runtime/settings.json。",
    };
    throw new Error(errors[result.error] || "操作未完成，请刷新后重试。");
  }
  return result;
}

function settings() {
  const models = $("models").value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
  if (!models.length || models.length > 10 || new Set(models).size !== models.length || models.some((value) => value.length > 200)) {
    setTab("detection");
    $("models").focus();
    throw new Error("请填写 1–10 个不重复的模型名称，每行一个。");
  }
  return {
    api: {enabled: true, base_url: $("base-url").value.trim(), model: models[0], api_mode: $("api-mode").value, timeout_seconds: Number($("timeout").value)},
    schedule: {enabled: $("enabled").checked, daily_time: $("daily-time").value, models, attempts_per_model: Number($("attempts").value), reasoning_effort: $("effort").value, timeout_seconds: Number($("timeout").value), max_output_tokens: Number($("tokens").value)},
    timezone: "Asia/Taipei", site_url: $("site-url").value.trim(), feishu_enabled: $("feishu-enabled").checked,
    test: {instructions: $("instructions").value.trim(), prompt: $("prompt").value.trim(), expected_answer: Number($("expected").value)},
  };
}

function hydrate() {
  const s = state.settings;
  const values = {
    "daily-time": s.schedule.daily_time, models: s.schedule.models.join("\n"), attempts: s.schedule.attempts_per_model,
    effort: s.schedule.reasoning_effort, timeout: s.schedule.timeout_seconds, tokens: s.schedule.max_output_tokens,
    "base-url": s.api.base_url, "api-mode": s.api.api_mode, "site-url": s.site_url,
    instructions: s.test.instructions, prompt: s.test.prompt, expected: s.test.expected_answer,
  };
  for (const [id, value] of Object.entries(values)) $(id).value = value;
  $("enabled").checked = s.schedule.enabled;
  $("feishu-enabled").checked = s.feishu_enabled;
  document.querySelectorAll("[data-credential]").forEach((input) => { input.value = ""; });
  document.querySelectorAll("[data-clear]").forEach((input) => { input.checked = false; });
  dirty = false;
  editState();
}

function editState() {
  const showSave = dirty || currentTab === "detection" || currentTab === "connections";
  $("savebar").hidden = !showSave;
  document.body.classList.toggle("has-savebar", showSave);
  $("dirty-status").textContent = dirty ? "未保存" : "已保存";
  $("dirty-status").className = dirty ? "unsaved" : "";
  $("discard").disabled = !dirty || saving;
  if (!state) return;
  const d = state.default_test;
  const standard = $("instructions").value.trim() === d.instructions && $("prompt").value.trim() === d.prompt && Number($("expected").value) === d.expected_answer;
  $("prompt-kind").textContent = standard ? "标准糖果题" : "自定义整数题";
  $("prompt-kind").className = standard ? "badge" : "badge custom";
  $("advanced-summary").textContent = $("effort").value + " · " + $("timeout").value + " 秒 · " + $("tokens").value + " Token";
  $("feishu-summary").textContent = $("feishu-enabled").checked ? "已启用" : "已停用";
  $("site-summary").textContent = $("site-url").value.trim() ? "已配置" : "已停用";
  const blocked = state.busy || saving || pendingAction;
  for (const id of ["save", "run", "sync", "models-action"]) {
    $(id).disabled = blocked || (id !== "save" && dirty) || (id === "run" || id === "models-action") && !state.credentials.api_key.configured;
  }
  $("save").textContent = saving ? "保存中…" : "保存并应用";
}

function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}

function modelChoices(models) {
  availableModels = models;
  $("model-list").hidden = false;
  renderModelChoices();
}

function renderModelChoices() {
  const list = $("model-options");
  const filter = $("model-filter").value.trim().toLowerCase();
  const selected = $("models").value.split(/\r?\n/).map((value) => value.trim());
  list.replaceChildren();
  for (const model of availableModels.filter((item) => item.id.toLowerCase().includes(filter))) {
    const button = node("button", model.id, "model-chip" + (selected.includes(model.id) ? " selected" : ""));
    button.type = "button";
    button.addEventListener("click", () => {
      const values = $("models").value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
      if (values.includes(model.id)) return;
      if (values.length >= 10) return notice("最多选择 10 个模型。", true);
      $("models").value = [...values, model.id].join("\n");
      dirty = true;
      renderModelChoices();
      editState();
      notice("已加入检测模型。");
    });
    list.append(button);
  }
  if (!list.childElementCount) list.append(node("div", "无匹配模型", "empty"));
}

function renderLatest() {
  const latest = state.runs[0];
  const signature = JSON.stringify(latest);
  if (signature === latestSignature) return;
  latestSignature = signature;
  $("latest-details").disabled = !latest;
  const target = $("latest-models");
  target.replaceChildren();
  if (!latest?.models.length) {
    target.append(node("div", latest ? "等待样本结果" : "暂无记录", "empty"));
    return;
  }
  const table = node("table", undefined, "model-table");
  table.setAttribute("aria-label", "最近一轮模型结果");
  const header = node("tr");
  const animation = latest.contract.prompt_version === "sheep-submarine-html-v1";
  for (const text of ["模型", animation ? "生成 / 采样" : "通过 / 采样", "有效回答", "接口 / 截断异常", "Token"]) {
    const cell = node("th", text, text === "Token" ? "usage-column" : undefined);
    cell.scope = "col";
    header.append(cell);
  }
  const head = node("thead"), body = node("tbody");
  head.append(header);
  for (const model of latest.models) {
    const row = node("tr");
    const usage = !model.usage_complete && !model.total_tokens ? "未提供" : model.total_tokens.toLocaleString() + (model.usage_complete ? "" : "（部分）");
    const values = [model.model, model.in_progress ? "接收中 · " + model.received_characters + " 字符" : (animation ? model.generated : model.passed) + " / " + model.attempts, model.completed, model.errors, usage];
    values.forEach((text, index) => row.append(node("td", text, index === 4 ? "usage-column" : undefined)));
    body.append(row);
  }
  table.append(head, body);
  target.append(table);
}

function render() {
  const s = state.settings, latest = state.runs[0], scheduler = state.scheduler;
  $("daily-status").textContent = s.schedule.enabled ? s.schedule.daily_time : "已暂停";
  $("daily-detail").textContent = "UTC+8 · 每模型 " + s.schedule.attempts_per_model + " 次";
  $("task-status").textContent = names[scheduler.state] || scheduler.state;
  $("next-run").textContent = scheduler.state === "Ready" && scheduler.next_run ? "下次 " + scheduler.next_run.replace("T", " ") : "LabModelMonitor-Daily";
  $("key-status").textContent = state.credentials.api_key.configured ? "已配置" : "待配置";
  $("model-count").textContent = s.schedule.models.length + " 个模型 · " + s.api.api_mode;
  $("latest-status").textContent = latest ? names[latest.status] || latest.status : "暂无记录";
  $("latest-time").textContent = latest ? date(latest.created_at) : "—";
  $("overview-test").textContent = state.standard_test ? "糖果题 · 答案 21" : "自定义题 · 答案 " + s.test.expected_answer;
  $("overview-models").textContent = s.schedule.models.join("、");
  $("site-link").hidden = !s.site_url;
  if (s.site_url) $("site-link").href = s.site_url;
  document.querySelectorAll("[data-state]").forEach((el) => {
    const value = state.credentials[el.dataset.state];
    el.textContent = value.configured ? value.source === "environment" ? "环境变量" : "已配置" : "未配置";
    el.className = "credential-state" + (value.configured ? "" : " missing");
  });
  $("run").textContent = "立即检测 · " + s.schedule.models.length * s.schedule.attempts_per_model + " 次";
  $("run-count").textContent = state.runs.length;
  const job = state.job, jobEl = $("job-status");
  jobEl.hidden = !state.busy && job.state === "idle";
  jobEl.className = "job-status" + (job.state === "failed" ? " failed" : "");
  const action = {run: "检测", sync: "同步", models: "连接测试"}[job.action] || "操作";
  if (state.busy) {
    const active = state.runs.find((run) => run.status === "running");
    jobEl.textContent = action + "运行中" + (active ? " · 已记录 " + active.sample_count + " 个样本" : "");
  } else if (job.state === "success") {
    jobEl.textContent = action + "已完成 · " + date(job.ended_at);
  } else if (job.state === "failed") {
    jobEl.textContent = action + "存在异常" + (job.result?.http_status ? " · HTTP " + job.result.http_status : "") + "，详情见运行记录。";
  }
  if (job.id && job.id !== completedJob && job.state !== "running") {
    completedJob = job.id;
    if (job.action === "models" && job.result?.success) modelChoices(job.result.models);
  }
  renderLatest();
  renderRuns();
  editState();
}

function renderRuns() {
  const filter = $("run-filter").value;
  const runs = state.runs.filter((run) => filter === "all" || run.status === filter);
  $("history-count").textContent = runs.length + " / " + state.runs.length + " 轮";
  const signature = JSON.stringify([filter, state.runs]);
  if (signature === runSignature) return;
  runSignature = signature;
  const expanded = new Set([...$("runs").querySelectorAll(".run-card[open]")].map((el) => el.dataset.id));
  const list = $("runs");
  list.replaceChildren();
  if (!runs.length) { list.append(node("div", "暂无记录", "empty")); return; }
  for (const run of runs) {
    const item = node("details", undefined, "run-card");
    item.dataset.id = run.run_id;
    const summary = node("summary"), heading = node("div", undefined, "run-heading"), label = node("div");
    heading.append(node("span", names[run.status] || run.status, "status " + run.status));
    const animation = run.contract.prompt_version === "sheep-submarine-html-v1";
    label.append(node("strong", date(run.created_at)), node("span", (animation ? "动画生成 · SVG HTML" : (run.contract.prompt_version === "candy-shape-selection-v1" ? "糖果题" : "自定义题") + " · 答案 " + run.contract.expected_answer) + " · " + ({manual: "手动", scheduled: "定时", imported: "导入"}[run.origin] || run.origin)));
    heading.append(label);
    const models = node("div", undefined, "run-models");
    for (const model of run.models) models.append(node("div", model.model + " · " + (model.in_progress ? "接收中 · " + model.received_characters + " 字符" : (animation ? model.generated : model.passed) + "/" + model.attempts + (animation ? " 生成" : " 通过")) + (model.errors ? " · " + model.errors + " 接口/截断异常" : "")));
    summary.append(heading, models);
    const content = node("div", undefined, "run-content");
    item.append(summary, content);
    async function detail() {
      if (!item.open || content.dataset.loaded || content.dataset.loading) return;
      content.dataset.loading = "true";
      content.textContent = "加载中…";
      try {
        const result = await api("/api/runs/" + run.run_id);
        if (!item.isConnected) return;
        displayDetail(content, result.run);
        content.dataset.loaded = "true";
      } catch (error) { content.textContent = error.message; }
      finally { delete content.dataset.loading; }
    }
    item.addEventListener("toggle", detail);
    list.append(item);
    if (expanded.has(run.run_id)) { item.open = true; detail(); }
  }
}

function displayDetail(content, run) {
  content.replaceChildren();
  const deliveries = Object.entries(run.delivery).map(([name, result]) => ({site: "看板", feishu: "飞书"}[name] || name) + "：" + (result.success ? "成功" : "未完成") + "（" + (result.status || "—") + "）");
  if (deliveries.length) content.append(node("p", deliveries.join(" · "), "run-meta"));
  const method = node("details", undefined, "run-extra");
  method.append(node("summary", "题面与参数"), node("p", "ID " + run.run_id + "\nSHA256 " + run.contract.prompt_sha256 + "\n" + run.contract.api_mode + " · " + run.contract.reasoning_effort + " · " + run.contract.max_output_tokens + " Token · " + run.contract.timeout_seconds + " 秒", "run-meta"));
  if (run.method) method.append(node("pre", run.method.instructions + "\n\n" + run.method.prompt));
  content.append(method);
  for (const sample of run.samples) {
    const item = node("details", undefined, "sample"), title = node("summary");
    title.append(node("span", sample.requested_model + " · 第 " + sample.attempt + " 次", "sample-title"), node("span", names[sample.status] || sample.status, "status " + sample.status), node("span", (run.contract.prompt_version === "sheep-submarine-html-v1" ? "HTML" : "答案 " + (sample.answer ?? "—")) + " · " + (sample.elapsed_seconds ?? "—") + " 秒" + (sample.http_status ? " · HTTP " + sample.http_status : ""), "sample-info"));
    item.append(title, node("p", "Token " + (sample.total_tokens ?? "未提供") + (sample.returned_model ? " · 返回模型 " + sample.returned_model : ""), "sample-info secondary-info"), node("pre", sample.response_text || "无文本回答"));
    content.append(item);
  }
  if (!run.samples.length) content.append(node("p", "尚无已完成样本。", "run-meta"));
}

function validateForm() {
  const invalid = form.querySelector(":invalid");
  if (!invalid) return true;
  setTab(invalid.closest("[data-panel]").dataset.panel);
  let parent = invalid.parentElement;
  while (parent && parent !== form) {
    if (parent.tagName === "DETAILS") parent.open = true;
    parent = parent.parentElement;
  }
  invalid.reportValidity();
  invalid.focus();
  return false;
}

async function refresh(initial = false) {
  clearTimeout(timer);
  try {
    state = await api("/api/state");
    if (initial) hydrate();
    render();
  } catch (error) { notice(error.message, true); }
  finally { timer = setTimeout(() => refresh(), state?.busy ? 2500 : 12000); }
}

document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", () => setTab(button.dataset.tab));
  button.addEventListener("keydown", (event) => {
    let index = tabs.indexOf(currentTab);
    if (event.key === "ArrowRight") index = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") index = (index + tabs.length - 1) % tabs.length;
    else if (event.key === "Home") index = 0;
    else if (event.key === "End") index = tabs.length - 1;
    else return;
    event.preventDefault();
    setTab(tabs[index], true);
  });
});
document.querySelectorAll("[data-goto]").forEach((button) => button.addEventListener("click", () => setTab(button.dataset.goto)));
window.addEventListener("hashchange", () => setTab(location.hash.slice(1)));
form.addEventListener("input", (event) => {
  if (event.target.hasAttribute("data-ui")) return;
  dirty = true;
  editState();
});
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state || state.busy || saving || pendingAction || !validateForm()) return;
  try {
    const payload = {settings: settings(), credentials: {}, clear_credentials: []};
    document.querySelectorAll("[data-credential]").forEach((input) => { if (input.value.trim()) payload.credentials[input.dataset.credential] = input.value.trim(); });
    document.querySelectorAll("[data-clear]:checked").forEach((input) => {
      if (payload.credentials[input.dataset.clear]) throw new Error("同一凭据不能同时填入新值和清除。");
      payload.clear_credentials.push(input.dataset.clear);
    });
    saving = true;
    editState();
    state = await api("/api/settings", payload);
    hydrate();
    render();
    notice("已保存并应用。");
  } catch (error) { notice(error.message, true); }
  finally { saving = false; editState(); }
});
$("discard").addEventListener("click", () => { hydrate(); renderModelChoices(); notice("已撤销修改。"); });
$("restore-prompt").addEventListener("click", () => {
  const test = state.default_test;
  $("instructions").value = test.instructions;
  $("prompt").value = test.prompt;
  $("expected").value = test.expected_answer;
  dirty = true;
  editState();
});
$("model-filter").addEventListener("input", renderModelChoices);
$("run-filter").addEventListener("change", renderRuns);
$("latest-details").addEventListener("click", () => {
  $("run-filter").value = "all";
  renderRuns();
  setTab("history");
  const latest = $("runs").querySelector(".run-card");
  if (latest) latest.open = true;
});
for (const [id, action] of [["run", "run"], ["sync", "sync"], ["models-action", "models"]]) {
  $(id).addEventListener("click", async () => {
    pendingAction = true;
    editState();
    try { await api("/api/actions", {action}); await refresh(); }
    catch (error) { notice(error.message, true); }
    finally { pendingAction = false; editState(); }
  });
}
$("refresh").addEventListener("click", () => refresh());
$("close-notice").addEventListener("click", () => { $("notice").hidden = true; });
window.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s" && (dirty || currentTab === "detection" || currentTab === "connections")) {
    event.preventDefault();
    form.requestSubmit();
  }
});
window.addEventListener("beforeunload", (event) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
setTab(location.hash.slice(1));
refresh(true);

