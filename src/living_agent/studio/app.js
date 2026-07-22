"use strict";

const viewRoot = document.querySelector("#view-root");
const viewTitle = document.querySelector("#view-title");
const viewMeta = document.querySelector("#view-meta");
const runtimeStatus = document.querySelector("#runtime-status");
const actorInput = document.querySelector("#actor-id");
const managementTokenInput = document.querySelector("#management-token");
const modal = document.querySelector("#modal");
const modalForm = document.querySelector("#modal-form");
const modalTitle = document.querySelector("#modal-title");
const modalBody = document.querySelector("#modal-body");
const modalFooter = document.querySelector("#modal-footer");
const toastStack = document.querySelector("#toast-stack");

const PERSONA_LAYERS = ["identity", "values", "traits", "speech", "boundaries", "growth"];
const PROMPTS = [
  ["host", "root"],
  ["interaction", "turn"],
  ["psyche", "appraisal"],
  ["social", "reply"],
  ["executive", "task"],
  ["speech", "render"],
  ["memory", "candidate"],
  ["evaluation", "critic"],
];
const VIEW_META = {
  overview: ["总览", "运行时与控制面状态"],
  memories: ["记忆浏览器", "候选、记忆节点与来源"],
  persona: ["人格编辑器", "分层人格的暂存工作流"],
  prompts: ["提示词实验室", "渲染、测试与版本部署"],
  plugins: ["插件中心", "发现状态与运行时开关"],
  capabilities: ["能力管理器", "能力定义与临时授权"],
  tasks: ["任务控制台", "执行计划、证据与确认"],
  users: ["用户目录", "稳定身份与展示资料"],
  audit: ["审计日志", "权限、工具与配置变更"],
  versions: ["版本历史", "人格与提示词历史"],
  simulator: ["行为模拟器", "无副作用的参与决策预演"],
  life: ["生活管理", "项目、日记、睡眠与自我修改提案"],
};

const DISPLAY_LABELS = {
  active: "启用", completed: "已完成", success: "成功", verified: "已验证", deployed: "已部署", ok: "正常",
  allow: "允许", allow_once: "单次允许", allow_in_sandbox: "仅沙箱允许", allow_read_only: "仅只读允许",
  pending: "待处理", planned: "已规划", running: "执行中", waiting: "等待中", waiting_confirmation: "等待确认",
  staged: "已暂存", ask_owner: "询问所有者", ASK_OWNER: "询问所有者", failed: "失败", failure: "失败",
  denied: "已拒绝", deny: "拒绝", deleted: "已删除", rejected: "已驳回", cancelled: "已取消",
  disabled: "已禁用", required: "必需", host: "宿主", bound: "已绑定", grant: "按授权",
  persona: "人格", prompt: "提示词", low: "低风险", medium: "中风险", high: "高风险",
  reported: "转述", inferred: "推断", imagined: "想象", dream: "梦境", fictional: "虚构",
  episodic: "情景", semantic: "语义", relationship: "关系", self: "自我", core: "核心",
  direct_message: "私聊消息", group_message: "群聊消息", webpage: "网页", file: "文件", tool_result: "工具结果",
  plugin_result: "插件结果", authenticated: "已认证", unauthenticated: "未认证", mentioned: "已点名",
  observe: "观察", react: "短回应", engage: "主动参与", act: "执行", anonymous: "匿名", none: "无",
  brokered: "经权限代理", owner: "所有者", member: "成员", trusted: "可信", untrusted: "不可信",
  bootstrap: "初始版本", deploy: "部署", rollback: "回滚", tool: "工具",
  paused: "已暂停", archived: "已归档", in_progress: "进行中", skipped: "已跳过",
  draft: "草稿", published: "已发布", ready: "待审批", test_failed: "测试失败",
  superseded: "已失效", routine: "日常", project: "项目", social: "社交", creative: "创作", rest: "休息",
};

const ARTIFACT_LABELS = {
  identity: "身份", values: "价值观", traits: "特质", speech: "语言风格", boundaries: "边界", growth: "成长",
  "host/root": "宿主/根策略", "interaction/turn": "交互/参与判断", "psyche/appraisal": "心理/评估",
  "social/reply": "社交/回复", "executive/task": "执行/任务", "speech/render": "表达/渲染",
  "memory/candidate": "记忆/候选", "evaluation/critic": "评估/审查",
};

function displayLabel(value) {
  return DISPLAY_LABELS[String(value)] || String(value);
}

const state = {
  view: "overview",
  actorId: localStorage.getItem("living-agent.actor-id") || "owner-local",
  managementToken: sessionStorage.getItem("living-agent.management-token") || "",
  conversationId: localStorage.getItem("living-agent.conversation-id") || "",
  memoryMode: "nodes",
  memories: [],
  memoryCandidates: [],
  selectedMemoryIds: new Set(),
  selectedMemory: null,
  personaLayer: "identity",
  promptKey: "social/reply",
  artifact: null,
  artifactHistory: [],
  artifactStage: null,
  tasks: [],
  selectedTask: null,
  audit: [],
  simulatorResult: null,
  lifeMode: "projects",
};

actorInput.value = state.actorId;
managementTokenInput.value = state.managementToken;

class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

function apiErrorMessage(payload, status) {
  const detail = payload && typeof payload === "object" ? payload.detail : payload;
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const location = Array.isArray(item.loc) ? item.loc.slice(1).join(".") : "请求";
      return `${location || "请求"}: ${item.msg || "值无效"}`;
    }).join("; ");
  }
  if (detail && typeof detail === "object") return pretty(detail);
  return String(detail || `HTTP ${status}`);
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function shortId(value) {
  const text = String(value || "");
  return text.length > 16 ? `${text.slice(0, 8)}…${text.slice(-5)}` : text;
}

function statusClass(value) {
  const normalized = String(value || "").toLowerCase();
  if (["active", "completed", "success", "verified", "deployed", "allow", "allow_once", "allow_in_sandbox", "allow_read_only"].includes(normalized)) return "is-ok";
  if (["pending", "planned", "running", "waiting", "waiting_confirmation", "staged", "ask_owner"].includes(normalized)) return "is-warn";
  if (["failed", "failure", "denied", "deny", "deleted", "rejected", "cancelled"].includes(normalized)) return "is-error";
  return "is-info";
}

function badge(value) {
  return `<span class="badge ${statusClass(value)}">${esc(displayLabel(value))}</span>`;
}

function contentText(content) {
  return typeof content === "string" ? content : pretty(content);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-Actor-ID", state.actorId);
  if (state.managementToken) headers.set("Authorization", `Bearer ${state.managementToken}`);
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    method: options.method || "GET",
    headers,
    body: options.body === undefined
      ? undefined
      : options.body instanceof FormData
        ? options.body
        : JSON.stringify(options.body),
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }
  if (!response.ok) {
    throw new ApiError(apiErrorMessage(payload, response.status), response.status, payload);
  }
  return payload;
}

function toast(message, type = "ok") {
  const item = document.createElement("div");
  item.className = `toast ${type === "error" ? "is-error" : ""}`;
  item.textContent = message;
  toastStack.append(item);
  window.setTimeout(() => item.remove(), 4200);
}

function showLoading(label = "正在读取控制面") {
  viewRoot.innerHTML = `<div class="loading-state"><span></span>${esc(label)}</div>`;
}

function renderFailure(error) {
  const message = error instanceof ApiError ? error.message : "控制面请求失败";
  const authAction = error instanceof ApiError && [401, 403, 422].includes(error.status)
    ? '<button class="button is-primary" id="fix-identity">设置管理身份</button>'
    : '<button class="button" id="retry-view">重试</button>';
  viewRoot.innerHTML = `
    <div class="error-state">
      <div><strong>${esc(message)}</strong><div class="metric-note">HTTP ${esc(error.status || "离线")}</div></div>
      ${authAction}
    </div>`;
  document.querySelector("#retry-view")?.addEventListener("click", renderCurrentView);
  document.querySelector("#fix-identity")?.addEventListener("click", openIdentityDialog);
}

function askForm({ title, body, submitLabel = "确认", danger = false }) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      modalForm.onsubmit = null;
      modal.onclose = null;
      resolve(value);
    };
    modalTitle.textContent = title;
    modalBody.innerHTML = body;
    modalFooter.innerHTML = `
      <button type="button" class="button" id="modal-cancel">取消</button>
      <button type="submit" class="button ${danger ? "is-danger" : "is-primary"}">${esc(submitLabel)}</button>`;
    document.querySelector("#modal-cancel").onclick = () => modal.close();
    modalForm.onsubmit = (event) => {
      event.preventDefault();
      if (event.submitter && event.submitter.value === "cancel") {
        modal.close();
        return;
      }
      const data = new FormData(modalForm);
      finish(data);
      modal.close();
    };
    modal.onclose = () => finish(null);
    modal.showModal();
    modalBody.querySelector("input, textarea, select")?.focus();
  });
}

async function confirmAction(title, message, label = "确认", danger = false) {
  const result = await askForm({
    title,
    body: `<p>${esc(message)}</p>`,
    submitLabel: label,
    danger,
  });
  return result !== null;
}

async function requestSecondFactor() {
  const data = await askForm({
    title: "二次认证",
    body: `
      <div class="form-row">
        <label for="second-factor">安全根提示词凭据</label>
        <input class="field" id="second-factor" name="secondFactor" type="password" autocomplete="one-time-code" required>
      </div>`,
    submitLabel: "验证",
  });
  return data ? String(data.get("secondFactor") || "") : null;
}

async function checkHealth() {
  try {
    const health = await fetch("/health").then((response) => response.json());
    runtimeStatus.className = "runtime-status is-ok";
    runtimeStatus.innerHTML = `<i></i>${esc(displayLabel(health.status))} · ${esc(health.version)}`;
  } catch {
    runtimeStatus.className = "runtime-status is-error";
    runtimeStatus.innerHTML = "<i></i>离线";
  }
}

function setView(view) {
  if (!VIEW_META[view]) return;
  state.view = view;
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.view === view);
  });
  [viewTitle.textContent, viewMeta.textContent] = VIEW_META[view];
  window.history.replaceState(null, "", `/studio#${view}`);
  renderCurrentView();
}

async function renderCurrentView() {
  showLoading();
  try {
    const renderer = {
      overview: renderOverview,
      memories: renderMemories,
      persona: () => renderArtifactEditor("persona"),
      prompts: () => renderArtifactEditor("prompt"),
      plugins: renderPlugins,
      capabilities: renderCapabilities,
      tasks: renderTasks,
      users: renderUsers,
      audit: renderAudit,
      versions: renderVersions,
      simulator: renderSimulator,
      life: renderLife,
    }[state.view];
    await renderer();
  } catch (error) {
    console.error(error);
    renderFailure(error);
  }
}

async function renderOverview() {
  const [audit, tasks, users, plugins, capabilities, memories] = await Promise.all([
    api("/v1/audit?limit=12"),
    api("/v1/tasks?limit=100"),
    api("/v1/users?limit=100"),
    api("/v1/plugins"),
    api("/v1/capabilities"),
    api("/v1/memories?limit=100", { headers: state.conversationId ? { "X-Conversation-ID": state.conversationId } : {} }),
  ]);
  const pendingTasks = tasks.filter((item) => item.status === "waiting_confirmation").length;
  const enabledPlugins = plugins.filter((item) => item.enabled).length;
  viewRoot.innerHTML = `
    <div class="metric-grid">
      ${metric("长期记忆", memories.length, `${memories.filter((item) => item.status === "active").length} 条启用`)}
      ${metric("注册用户", users.length, "稳定平台身份")}
      ${metric("待确认任务", pendingTasks, `共 ${tasks.length} 项`)}
      ${metric("启用插件", enabledPlugins, `${capabilities.definitions.length} 项能力`)}
    </div>
    <section class="band">
      <div class="section-heading"><h2>执行状态</h2><button class="button is-small" data-go="tasks">打开任务台</button></div>
      ${taskStatusTable(tasks.slice(0, 6))}
    </section>
    <section class="band">
      <div class="section-heading"><h2>最近审计</h2><button class="button is-small" data-go="audit">查看全部</button></div>
      ${auditTable(audit.slice(0, 8))}
    </section>`;
  viewRoot.querySelectorAll("[data-go]").forEach((button) => {
    button.onclick = () => setView(button.dataset.go);
  });
}

function metric(label, value, note) {
  return `<article class="metric-card"><div class="metric-label">${esc(label)}</div><div class="metric-value">${esc(value)}</div><div class="metric-note">${esc(note)}</div></article>`;
}

function taskStatusTable(tasks) {
  if (!tasks.length) return '<div class="empty-state">没有任务记录</div>';
  return `<div class="table-wrap"><table><thead><tr><th>任务</th><th>状态</th><th>步骤</th><th>更新时间</th></tr></thead><tbody>${tasks.map((run) => `
    <tr><td><span class="mono">${esc(shortId(run.task.task_id))}</span><br><span class="metric-note">${esc(run.task.goal)}</span></td><td>${badge(run.status)}</td><td>${run.step_results.filter((item) => item.status === "completed").length}/${run.step_results.length}</td><td>${esc(formatDate(run.updated_at))}</td></tr>`).join("")}</tbody></table></div>`;
}

function auditTable(entries) {
  if (!entries.length) return '<div class="empty-state">没有审计记录</div>';
  return `<div class="table-wrap"><table><thead><tr><th>时间</th><th>动作</th><th>结果</th><th>操作者</th><th>会话</th></tr></thead><tbody>${entries.map((entry) => `
    <tr><td>${esc(formatDate(entry.created_at))}</td><td class="mono">${esc(entry.action)}</td><td>${badge(entry.outcome)}</td><td><span class="truncate">${esc(entry.actor_id || "-")}</span></td><td><span class="truncate mono">${esc(entry.conversation_id || "-")}</span></td></tr>`).join("")}</tbody></table></div>`;
}

async function renderMemories() {
  if (state.memoryMode === "candidates") {
    state.memoryCandidates = await api("/v1/memories/candidates?limit=200");
  } else {
    const query = document.querySelector("#memory-search")?.value || "";
    const includeDeleted = document.querySelector("#include-deleted")?.checked || false;
    const headers = state.conversationId ? { "X-Conversation-ID": state.conversationId } : {};
    state.memories = await api(`/v1/memories?query=${encodeURIComponent(query)}&include_deleted=${includeDeleted}&limit=300`, { headers });
  }
  const list = state.memoryMode === "nodes" ? renderMemoryNodes() : renderMemoryCandidates();
  viewRoot.innerHTML = `
    <div class="toolbar">
      <div class="segmented">
        <button data-memory-mode="nodes" class="${state.memoryMode === "nodes" ? "is-active" : ""}">记忆节点</button>
        <button data-memory-mode="candidates" class="${state.memoryMode === "candidates" ? "is-active" : ""}">候选队列</button>
      </div>
      ${state.memoryMode === "nodes" ? `
        <input class="field is-search" id="memory-search" placeholder="搜索内容或主题">
        <label class="check-row"><input type="checkbox" id="include-deleted">包含删除</label>
        <button class="button" id="search-memories">搜索</button>
        <div class="toolbar-spacer"></div>
        <button class="button" id="merge-memories" ${state.selectedMemoryIds.size < 2 ? "disabled" : ""}>合并 ${state.selectedMemoryIds.size || ""}</button>` : '<div class="toolbar-spacer"></div>'}
    </div>
    ${list}`;
  viewRoot.querySelectorAll("[data-memory-mode]").forEach((button) => {
    button.onclick = () => {
      state.memoryMode = button.dataset.memoryMode;
      state.selectedMemory = null;
      renderCurrentView();
    };
  });
  document.querySelector("#search-memories")?.addEventListener("click", renderMemories);
  document.querySelector("#memory-search")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") renderMemories();
  });
  document.querySelector("#merge-memories")?.addEventListener("click", mergeSelectedMemories);
  bindMemoryRows();
}

function renderMemoryNodes() {
  const detail = state.selectedMemory ? memoryDetail(state.selectedMemory) : '<div class="empty-state">选择一条记忆</div>';
  return `<div class="split-layout"><div class="split-main"><div class="table-wrap"><table><thead><tr><th></th><th>主题</th><th>类型</th><th>事实性</th><th>置信度</th><th>范围</th><th>状态</th></tr></thead><tbody>${state.memories.map((memory) => `
    <tr>
      <td><input type="checkbox" data-select-memory="${esc(memory.id)}" ${state.selectedMemoryIds.has(memory.id) ? "checked" : ""}></td>
      <td><button class="row-button" data-memory-id="${esc(memory.id)}"><strong>${esc(memory.subject)}</strong><span class="truncate metric-note">${esc(contentText(memory.content))}</span></button></td>
      <td>${esc(displayLabel(memory.type))}</td><td>${badge(memory.factuality)}</td><td>${Math.round(memory.confidence * 100)}%</td><td><span class="mono">${esc(memory.scope)}</span></td><td>${badge(memory.status)}</td>
    </tr>`).join("") || '<tr><td colspan="7"><div class="empty-state">没有匹配记忆</div></td></tr>'}</tbody></table></div></div><aside class="detail-pane" id="memory-detail">${detail}</aside></div>`;
}

function renderMemoryCandidates() {
  return `<div class="table-wrap"><table><thead><tr><th>主题</th><th>类型</th><th>来源信任</th><th>事实性</th><th>范围</th><th>状态</th><th></th></tr></thead><tbody>${state.memoryCandidates.map((item) => `
    <tr><td><strong>${esc(item.subject)}</strong><span class="truncate metric-note">${esc(contentText(item.content))}</span></td><td>${esc(displayLabel(item.type))}</td><td>${esc(displayLabel(item.source_trust))}</td><td>${badge(item.factuality)}</td><td class="mono">${esc(item.scope)}</td><td>${badge(item.status)}</td><td>${item.status === "pending" ? `<button class="button is-small is-primary" data-commit-candidate="${esc(item.candidate_id)}">提交</button>` : ""}</td></tr>`).join("") || '<tr><td colspan="7"><div class="empty-state">没有候选记忆</div></td></tr>'}</tbody></table></div>`;
}

function bindMemoryRows() {
  viewRoot.querySelectorAll("[data-memory-id]").forEach((button) => {
    button.onclick = () => {
      state.selectedMemory = state.memories.find((item) => item.id === button.dataset.memoryId) || null;
      document.querySelector("#memory-detail").innerHTML = state.selectedMemory ? memoryDetail(state.selectedMemory) : "";
      bindMemoryDetail();
    };
  });
  viewRoot.querySelectorAll("[data-select-memory]").forEach((checkbox) => {
    checkbox.onchange = () => {
      if (checkbox.checked) state.selectedMemoryIds.add(checkbox.dataset.selectMemory);
      else state.selectedMemoryIds.delete(checkbox.dataset.selectMemory);
      const merge = document.querySelector("#merge-memories");
      if (merge) {
        merge.disabled = state.selectedMemoryIds.size < 2;
        merge.textContent = `合并 ${state.selectedMemoryIds.size || ""}`;
      }
    };
  });
  viewRoot.querySelectorAll("[data-commit-candidate]").forEach((button) => {
    button.onclick = async () => {
      try {
        const result = await api(`/v1/memories/candidates/${encodeURIComponent(button.dataset.commitCandidate)}/commit`, { method: "POST" });
        toast(result.decision.allowed ? "候选记忆已提交" : `候选被拒绝：${result.decision.reason_code}`);
        renderMemories();
      } catch (error) { toast(error.message, "error"); }
    };
  });
  bindMemoryDetail();
}

function memoryDetail(memory) {
  return `
    <div class="section-heading"><h2>${esc(memory.subject)}</h2>${badge(memory.status)}</div>
    <dl class="detail-grid">
      <dt>ID</dt><dd class="mono">${esc(memory.id)}</dd>
      <dt>类型</dt><dd>${esc(displayLabel(memory.type))}</dd>
      <dt>事实性</dt><dd>${esc(displayLabel(memory.factuality))}</dd>
      <dt>置信度</dt><dd>${Math.round(memory.confidence * 100)}%</dd>
      <dt>重要度</dt><dd>${Math.round(memory.importance * 100)}%</dd>
      <dt>范围</dt><dd class="mono">${esc(memory.scope)}</dd>
      <dt>版本</dt><dd>${memory.version}</dd>
      <dt>更新时间</dt><dd>${esc(formatDate(memory.updated_at))}</dd>
    </dl>
    <pre class="content-block">${esc(contentText(memory.content))}</pre>
    <div class="toolbar band">
      <button class="button is-small" id="edit-memory">编辑</button>
      <button class="button is-small" id="inspect-memory">来源与历史</button>
      <button class="button is-small" id="split-memory">拆分</button>
      <div class="toolbar-spacer"></div>
      ${memory.status === "active" ? '<button class="button is-small is-danger" id="delete-memory">删除</button>' : '<button class="button is-small is-primary" id="restore-memory">恢复</button>'}
    </div>
    <div id="memory-evidence"></div>`;
}

function bindMemoryDetail() {
  const memory = state.selectedMemory;
  if (!memory) return;
  document.querySelector("#edit-memory")?.addEventListener("click", () => editMemory(memory));
  document.querySelector("#inspect-memory")?.addEventListener("click", () => inspectMemory(memory));
  document.querySelector("#split-memory")?.addEventListener("click", () => splitMemory(memory));
  document.querySelector("#delete-memory")?.addEventListener("click", () => changeMemoryStatus(memory, "delete"));
  document.querySelector("#restore-memory")?.addEventListener("click", () => changeMemoryStatus(memory, "restore"));
}

async function editMemory(memory) {
  const data = await askForm({
    title: "编辑记忆",
    body: `<div class="inline-form">
      <div class="form-row is-full"><label>主题</label><input class="field" name="subject" value="${esc(memory.subject)}" required></div>
      <div class="form-row is-full"><label>内容</label><textarea class="textarea" name="content" required>${esc(contentText(memory.content))}</textarea></div>
      <div class="form-row"><label>事实性</label><select class="select" name="factuality">${["verified", "reported", "inferred", "imagined", "dream", "fictional"].map((value) => `<option value="${value}" ${value === memory.factuality ? "selected" : ""}>${displayLabel(value)}</option>`).join("")}</select></div>
      <div class="form-row"><label>置信度</label><input class="field" name="confidence" type="number" min="0" max="1" step="0.01" value="${memory.confidence}"></div>
      <div class="form-row"><label>重要度</label><input class="field" name="importance" type="number" min="0" max="1" step="0.01" value="${memory.importance}"></div>
    </div>`,
    submitLabel: "保存版本",
  });
  if (!data) return;
  let content = String(data.get("content"));
  try { if (content.trim().startsWith("{")) content = JSON.parse(content); } catch { /* keep text */ }
  try {
    const updated = await api(`/v1/memories/${encodeURIComponent(memory.id)}`, {
      method: "PATCH",
      body: {
        expected_version: memory.version,
        subject: String(data.get("subject")),
        content,
        factuality: String(data.get("factuality")),
        confidence: Number(data.get("confidence")),
        importance: Number(data.get("importance")),
      },
    });
    state.selectedMemory = updated;
    toast("记忆版本已更新");
    renderMemories();
  } catch (error) { toast(error.message, "error"); }
}

async function inspectMemory(memory) {
  const headers = state.conversationId ? { "X-Conversation-ID": state.conversationId } : {};
  try {
    const [versions, sources, usages] = await Promise.all([
      api(`/v1/memories/${encodeURIComponent(memory.id)}/versions`, { headers }),
      api(`/v1/memories/${encodeURIComponent(memory.id)}/sources`, { headers }),
      api(`/v1/memories/${encodeURIComponent(memory.id)}/usages`, { headers }),
    ]);
    document.querySelector("#memory-evidence").innerHTML = `
      <div class="band"><h3>版本 ${versions.length}</h3><pre class="json-block">${esc(pretty(versions))}</pre></div>
      <div class="band"><h3>来源 ${sources.length}</h3><pre class="json-block">${esc(pretty(sources))}</pre></div>
      <div class="band"><h3>使用记录 ${usages.length}</h3><pre class="json-block">${esc(pretty(usages))}</pre></div>`;
  } catch (error) { toast(error.message, "error"); }
}

async function changeMemoryStatus(memory, action) {
  const approved = await confirmAction(action === "delete" ? "删除记忆" : "恢复记忆", `${memory.subject} · v${memory.version}`, action === "delete" ? "删除" : "恢复", action === "delete");
  if (!approved) return;
  const method = action === "delete" ? "DELETE" : "POST";
  const suffix = action === "delete" ? "" : "/restore";
  try {
    await api(`/v1/memories/${encodeURIComponent(memory.id)}${suffix}?expected_version=${memory.version}`, { method });
    state.selectedMemory = null;
    toast(action === "delete" ? "记忆已软删除" : "记忆已恢复");
    renderMemories();
  } catch (error) { toast(error.message, "error"); }
}

async function mergeSelectedMemories() {
  const selected = state.memories.filter((item) => state.selectedMemoryIds.has(item.id));
  if (selected.length < 2) return;
  const first = selected[0];
  const data = await askForm({
    title: `合并 ${selected.length} 条记忆`,
    body: `<div class="inline-form">
      <div class="form-row is-full"><label>主题</label><input class="field" name="subject" value="${esc(first.subject)}" required></div>
      <div class="form-row is-full"><label>合并内容</label><textarea class="textarea" name="content" required>${esc(selected.map((item) => contentText(item.content)).join("\n"))}</textarea></div>
      <div class="form-row"><label>类型</label><select class="select" name="type">${["episodic", "semantic", "relationship", "self", "core"].map((value) => `<option value="${value}" ${value === first.type ? "selected" : ""}>${displayLabel(value)}</option>`).join("")}</select></div>
      <div class="form-row"><label>事实性</label><select class="select" name="factuality">${["verified", "reported", "inferred", "imagined", "dream", "fictional"].map((value) => `<option value="${value}" ${value === first.factuality ? "selected" : ""}>${displayLabel(value)}</option>`).join("")}</select></div>
      <div class="form-row"><label>范围</label><input class="field" name="scope" value="${esc(first.scope)}" required></div>
      <div class="form-row"><label>置信度</label><input class="field" name="confidence" type="number" min="0" max="1" step="0.01" value="${first.confidence}"></div>
      <div class="form-row"><label>重要度</label><input class="field" name="importance" type="number" min="0" max="1" step="0.01" value="${first.importance}"></div>
    </div>`,
    submitLabel: "创建合并版本",
  });
  if (!data) return;
  try {
    await api("/v1/memories/merge", { method: "POST", body: {
      memory_ids: selected.map((item) => item.id),
      type: String(data.get("type")), content: String(data.get("content")), subject: String(data.get("subject")),
      factuality: String(data.get("factuality")), confidence: Number(data.get("confidence")), importance: Number(data.get("importance")), scope: String(data.get("scope")),
    }});
    state.selectedMemoryIds.clear();
    state.selectedMemory = null;
    toast("记忆已合并");
    renderMemories();
  } catch (error) { toast(error.message, "error"); }
}

async function splitMemory(memory) {
  const seed = [1, 2].map((index) => ({
    type: memory.type,
    content: `${contentText(memory.content)} (${index})`,
    subject: `${memory.subject} ${index}`,
    factuality: memory.factuality,
    confidence: memory.confidence,
    importance: memory.importance,
    scope: memory.scope,
  }));
  const data = await askForm({
    title: "拆分记忆",
    body: `<div class="form-row"><label>拆分部分（JSON）</label><textarea class="textarea" name="parts" required>${esc(pretty(seed))}</textarea></div>`,
    submitLabel: "验证并拆分",
  });
  if (!data) return;
  try {
    const parts = JSON.parse(String(data.get("parts")));
    await api(`/v1/memories/${encodeURIComponent(memory.id)}/split`, { method: "POST", body: { parts } });
    state.selectedMemory = null;
    toast("记忆已拆分");
    renderMemories();
  } catch (error) { toast(error.message, "error"); }
}

async function renderArtifactEditor(kind) {
  const isPersona = kind === "persona";
  const key = isPersona ? state.personaLayer : state.promptKey;
  const [category, name] = isPersona ? [null, key] : key.split("/");
  const base = isPersona ? `/v1/persona/${key}` : `/v1/prompts/${category}/${name}`;
  const [artifact, history] = await Promise.all([api(base), api(`${base}/history`)]);
  state.artifact = artifact;
  state.artifactHistory = history;
  state.artifactStage = null;
  const choices = isPersona ? PERSONA_LAYERS.map((item) => [item, ARTIFACT_LABELS[item]]) : PROMPTS.map(([cat, prompt]) => [`${cat}/${prompt}`, ARTIFACT_LABELS[`${cat}/${prompt}`]]);
  viewRoot.innerHTML = `
    <div class="editor-layout">
      <aside class="artifact-list">${choices.map(([value, label]) => `<button data-artifact-key="${esc(value)}" class="${value === key ? "is-active" : ""}">${esc(label)}</button>`).join("")}</aside>
      <section class="editor-workspace">
        <div class="toolbar">
          <strong class="mono">${esc(artifact.artifact_path)}</strong>
          <span class="badge is-info">v${artifact.version}</span>
          ${!isPersona ? `<span class="badge">约 ${artifact.token_estimate} 个令牌</span><span class="badge">${esc((artifact.variables || []).join(", ") || "无变量")}</span>` : ""}
          <div class="toolbar-spacer"></div>
          ${!isPersona ? '<button class="button is-small" id="render-artifact">测试渲染</button>' : ""}
          <button class="button is-small" id="rollback-artifact" ${history.length < 2 ? "disabled" : ""}>回滚</button>
          <button class="button is-primary" id="stage-artifact">创建暂存版本</button>
        </div>
        <textarea class="textarea editor-textarea" id="artifact-content" spellcheck="false">${esc(artifact.content)}</textarea>
        <div id="artifact-stage"></div>
      </section>
    </div>`;
  viewRoot.querySelectorAll("[data-artifact-key]").forEach((button) => {
    button.onclick = () => {
      if (isPersona) state.personaLayer = button.dataset.artifactKey;
      else state.promptKey = button.dataset.artifactKey;
      renderCurrentView();
    };
  });
  document.querySelector("#stage-artifact").onclick = () => stageArtifact(kind, base);
  document.querySelector("#rollback-artifact").onclick = () => rollbackArtifact(kind, base);
  document.querySelector("#render-artifact")?.addEventListener("click", () => renderPrompt(base));
}

async function rootHeadersIfNeeded(kind) {
  if (kind !== "prompt" || state.promptKey !== "host/root") return {};
  const secondFactor = await requestSecondFactor();
  if (secondFactor === null) return null;
  return { "X-Second-Factor": secondFactor };
}

async function stageArtifact(kind, base) {
  const headers = await rootHeadersIfNeeded(kind);
  if (headers === null) return;
  const content = document.querySelector("#artifact-content").value;
  try {
    state.artifactStage = await api(`${base}/stage`, { method: "POST", headers, body: { content, expected_version: state.artifact.version } });
    renderArtifactStage(kind);
    toast("暂存版本已创建");
  } catch (error) { toast(error.message, "error"); }
}

function renderArtifactStage(kind) {
  const stage = state.artifactStage;
  if (!stage) return;
  document.querySelector("#artifact-stage").innerHTML = `
    <section class="band">
      <div class="section-heading"><h2>暂存版本 ${esc(shortId(stage.stage_id))}</h2>${badge(stage.status)}</div>
      <div class="editor-meta"><span>基于 v${stage.base_version}</span><span>${stage.tested ? "已测试" : "未测试"}</span><span>${esc(formatDate(stage.updated_at))}</span></div>
      <pre class="diff-block">${esc(stage.diff || "没有差异")}</pre>
      ${Object.keys(stage.test_results || {}).length ? `<pre class="json-block">${esc(pretty(stage.test_results))}</pre>` : ""}
      <div class="toolbar"><button class="button" id="test-stage">运行测试</button><button class="button is-primary" id="deploy-stage" ${stage.tested ? "" : "disabled"}>部署</button></div>
    </section>`;
  document.querySelector("#test-stage").onclick = () => testArtifactStage(kind);
  document.querySelector("#deploy-stage").onclick = () => deployArtifactStage(kind);
}

async function testArtifactStage(kind) {
  try {
    state.artifactStage = await api(`/v1/${kind === "persona" ? "persona" : "prompts"}/stages/${encodeURIComponent(state.artifactStage.stage_id)}/test`, { method: "POST" });
    renderArtifactStage(kind);
    toast(state.artifactStage.tested ? "暂存版本测试通过" : "暂存版本测试失败", state.artifactStage.tested ? "ok" : "error");
  } catch (error) { toast(error.message, "error"); }
}

async function deployArtifactStage(kind) {
  const headers = await rootHeadersIfNeeded(kind);
  if (headers === null) return;
  const approved = await confirmAction("部署变更", `${state.artifactStage.artifact_path} · 基于 v${state.artifactStage.base_version}`, "部署");
  if (!approved) return;
  try {
    const result = await api(`/v1/${kind === "persona" ? "persona" : "prompts"}/stages/${encodeURIComponent(state.artifactStage.stage_id)}/deploy`, { method: "POST", headers });
    toast(result.restart_required ? "已部署，重启后生效" : "已部署");
    renderCurrentView();
  } catch (error) { toast(error.message, "error"); }
}

async function rollbackArtifact(kind, base) {
  const options = state.artifactHistory.filter((item) => item.version !== state.artifact.version).map((item) => `<option value="${item.version}">v${item.version} · ${esc(item.change_type)} · ${esc(formatDate(item.created_at))}</option>`).join("");
  const data = await askForm({ title: "回滚版本", body: `<div class="form-row"><label>目标版本</label><select class="select" name="version" required>${options}</select></div>`, submitLabel: "测试并回滚", danger: true });
  if (!data) return;
  const headers = await rootHeadersIfNeeded(kind);
  if (headers === null) return;
  try {
    const result = await api(`${base}/rollback`, { method: "POST", headers, body: { target_version: Number(data.get("version")) } });
    toast(result.restart_required ? "已回滚，重启后生效" : "已回滚");
    renderCurrentView();
  } catch (error) { toast(error.message, "error"); }
}

async function renderPrompt(base) {
  const fields = (state.artifact.variables || []).map((name) => `<div class="form-row"><label>${esc(name)}</label><input class="field" name="${esc(name)}" required></div>`).join("");
  const data = await askForm({ title: "测试渲染", body: fields || '<div class="empty-state">该提示词没有变量</div>', submitLabel: "渲染" });
  if (!data) return;
  const variables = {};
  for (const name of state.artifact.variables || []) variables[name] = String(data.get(name));
  try {
    const result = await api(`${base}/render`, { method: "POST", body: { variables } });
    await askForm({ title: `渲染结果 · ${result.token_estimate} 个令牌`, body: `<pre class="content-block">${esc(result.rendered)}</pre>`, submitLabel: "关闭" });
  } catch (error) { toast(error.message, "error"); }
}

async function renderPlugins() {
  const plugins = await api("/v1/plugins");
  viewRoot.innerHTML = `<div class="plugin-grid">${plugins.map((plugin) => `
    <article class="item-card">
      <div class="item-card-header"><div><h2 class="item-card-title">${esc(plugin.name)}</h2><div class="item-card-subtitle mono">${esc(plugin.id)} · v${esc(plugin.version)}</div></div>${badge(plugin.enabled ? "active" : "disabled")}</div>
      <div class="status-strip">${plugin.operations.map((operation) => `<span class="badge">${esc(operation)}</span>`).join("")}<span class="badge ${plugin.risk_level === "high" ? "is-error" : "is-info"}">${esc(displayLabel(plugin.risk_level))}</span></div>
      <div class="item-card-actions"><button class="button is-small ${plugin.enabled ? "is-danger" : "is-primary"}" data-plugin="${esc(plugin.id)}" data-enabled="${plugin.enabled}">${plugin.enabled ? "禁用" : "启用"}</button></div>
    </article>`).join("") || '<div class="empty-state">没有发现插件</div>'}</div>`;
  viewRoot.querySelectorAll("[data-plugin]").forEach((button) => {
    button.onclick = async () => {
      const enabling = button.dataset.enabled !== "true";
      if (!await confirmAction(enabling ? "启用插件" : "禁用插件", button.dataset.plugin, enabling ? "启用" : "禁用", !enabling)) return;
      try {
        await api(`/v1/plugins/${encodeURIComponent(button.dataset.plugin)}/${enabling ? "enable" : "disable"}`, { method: "POST" });
        toast(enabling ? "插件已启用" : "插件已禁用");
        renderPlugins();
      } catch (error) { toast(error.message, "error"); }
    };
  });
}

async function renderCapabilities() {
  const snapshot = await api("/v1/capabilities");
  viewRoot.innerHTML = `
    <section><div class="section-heading"><h2>已注册能力</h2><span class="badge">${snapshot.definitions.length}</span></div>
      <div class="table-wrap"><table><thead><tr><th>能力</th><th>操作</th><th>参数模式</th><th>沙箱</th><th>范围绑定</th></tr></thead><tbody>${snapshot.definitions.map((item) => `<tr><td class="mono">${esc(item.name)}</td><td>${item.operations.map((value) => `<span class="badge">${esc(value)}</span>`).join(" ")}</td><td class="mono">${esc(item.argument_schema)}</td><td>${badge(item.sandbox_required ? "required" : "host")}</td><td>${badge(item.scope_bound ? "bound" : "grant")}</td></tr>`).join("")}</tbody></table></div>
    </section>
    <section class="band"><div class="section-heading"><h2>临时授权</h2><span class="badge ${snapshot.active_grants.length ? "is-warn" : "is-ok"}">${snapshot.active_grants.length}</span></div>
      <div class="table-wrap"><table><thead><tr><th>授权</th><th>操作者</th><th>能力</th><th>操作</th><th>范围</th><th></th></tr></thead><tbody>${snapshot.active_grants.map((grant) => `<tr><td class="mono">${esc(shortId(grant.grant_id))}</td><td>${esc(grant.actor_id)}</td><td class="mono">${esc(grant.capability)}</td><td>${esc([...grant.operations].join(", "))}</td><td><span class="truncate mono">${esc([...grant.resource_scopes].join(", "))}</span></td><td><button class="button is-small is-danger" data-revoke-grant="${esc(grant.grant_id)}">撤销</button></td></tr>`).join("") || '<tr><td colspan="6"><div class="empty-state">当前没有临时授权</div></td></tr>'}</tbody></table></div>
    </section>`;
  viewRoot.querySelectorAll("[data-revoke-grant]").forEach((button) => {
    button.onclick = async () => {
      if (!await confirmAction("撤销临时授权", button.dataset.revokeGrant, "撤销", true)) return;
      try {
        await api(`/v1/capabilities/grants/${encodeURIComponent(button.dataset.revokeGrant)}`, { method: "DELETE" });
        toast("临时授权已撤销");
        renderCapabilities();
      } catch (error) { toast(error.message, "error"); }
    };
  });
}

async function renderTasks() {
  const statusFilter = document.querySelector("#task-status")?.value || "";
  state.tasks = await api(`/v1/tasks?limit=300${statusFilter ? `&status=${encodeURIComponent(statusFilter)}` : ""}`);
  const detail = state.selectedTask ? taskDetail(state.selectedTask) : '<div class="empty-state">选择一个任务</div>';
  viewRoot.innerHTML = `
    <div class="toolbar"><select class="select" id="task-status"><option value="">全部状态</option>${["planned", "running", "waiting_confirmation", "completed", "failed", "cancelled"].map((value) => `<option value="${value}" ${value === statusFilter ? "selected" : ""}>${displayLabel(value)}</option>`).join("")}</select><button class="button" id="filter-tasks">筛选</button></div>
    <div class="split-layout"><div class="split-main"><div class="table-wrap"><table><thead><tr><th>任务</th><th>请求者</th><th>状态</th><th>步骤</th><th>更新时间</th></tr></thead><tbody>${state.tasks.map((run) => `<tr><td><button class="row-button" data-task-id="${esc(run.task.task_id)}"><strong>${esc(run.task.goal)}</strong><span class="metric-note mono">${esc(shortId(run.task.task_id))}</span></button></td><td><span class="truncate">${esc(run.task.requester_id)}</span></td><td>${badge(run.status)}</td><td>${run.step_results.filter((item) => item.status === "completed").length}/${run.step_results.length}</td><td>${esc(formatDate(run.updated_at))}</td></tr>`).join("") || '<tr><td colspan="5"><div class="empty-state">没有任务记录</div></td></tr>'}</tbody></table></div></div><aside class="detail-pane" id="task-detail">${detail}</aside></div>`;
  document.querySelector("#filter-tasks").onclick = renderTasks;
  viewRoot.querySelectorAll("[data-task-id]").forEach((button) => {
    button.onclick = () => {
      state.selectedTask = state.tasks.find((item) => item.task.task_id === button.dataset.taskId);
      document.querySelector("#task-detail").innerHTML = taskDetail(state.selectedTask);
      bindTaskDetail();
    };
  });
  bindTaskDetail();
}

function taskDetail(run) {
  return `
    <div class="section-heading"><h2>${esc(run.task.goal)}</h2>${badge(run.status)}</div>
    <dl class="detail-grid"><dt>任务 ID</dt><dd class="mono">${esc(run.task.task_id)}</dd><dt>请求者</dt><dd>${esc(run.task.requester_id)}</dd><dt>会话</dt><dd class="mono">${esc(run.conversation_id || "-")}</dd><dt>版本</dt><dd>${run.version}</dd><dt>允许能力</dt><dd>${run.task.allowed_capabilities.map((value) => `<span class="badge">${esc(value)}</span>`).join(" ")}</dd></dl>
    <div class="band"><h3>执行步骤</h3>${run.plan.steps.map((step) => {
      const result = run.step_results.find((item) => item.step_id === step.step_id);
      return `<div class="item-card"><div class="item-card-header"><strong>${esc(step.title)}</strong>${badge(result?.status || "pending")}</div><div class="item-card-subtitle mono">${esc(step.action.capability_request.capability)} / ${esc(step.action.capability_request.operation)} · 尝试 ${result?.attempts || 0}/${step.max_attempts}</div>${result?.errors?.length ? `<div class="status-strip">${result.errors.map((error) => `<span class="badge is-error">${esc(error)}</span>`).join("")}</div>` : ""}${result?.output ? `<pre class="json-block">${esc(pretty(result.output))}</pre>` : ""}</div>`;
    }).join("")}</div>
    <div class="toolbar band">
      ${run.status === "waiting_confirmation" ? '<button class="button is-primary" id="confirm-task">确认写入</button>' : ""}
      ${["planned", "running", "waiting_confirmation"].includes(run.status) ? '<button class="button is-danger" id="cancel-task">取消任务</button>' : ""}
      ${run.status === "completed" && run.plan.steps.some((step) => step.action.handler === "task_report") ? '<button class="button" id="view-task-report">查看报告</button>' : ""}
    </div>`;
}

function bindTaskDetail() {
  const run = state.selectedTask;
  if (!run) return;
  document.querySelector("#confirm-task")?.addEventListener("click", async () => {
    if (!await confirmAction("确认任务写入", run.task.task_id, "确认写入")) return;
    try { state.selectedTask = await api(`/v1/tasks/${run.task.task_id}/confirm`, { method: "POST" }); toast("任务已继续执行"); renderTasks(); } catch (error) { toast(error.message, "error"); }
  });
  document.querySelector("#cancel-task")?.addEventListener("click", async () => {
    if (!await confirmAction("取消任务", run.task.task_id, "取消任务", true)) return;
    try { await api(`/v1/tasks/${run.task.task_id}/cancel`, { method: "POST" }); state.selectedTask = null; toast("任务已取消"); renderTasks(); } catch (error) { toast(error.message, "error"); }
  });
  document.querySelector("#view-task-report")?.addEventListener("click", async () => {
    try { const report = await api(`/v1/tasks/${run.task.task_id}/report`); await askForm({ title: "任务报告", body: `<pre class="content-block">${esc(report.content)}</pre>`, submitLabel: "关闭" }); } catch (error) { toast(error.message, "error"); }
  });
}

async function renderUsers() {
  const query = document.querySelector("#user-search")?.value || "";
  const users = await api(`/v1/users?query=${encodeURIComponent(query)}&limit=300`);
  viewRoot.innerHTML = `<div class="toolbar"><input class="field is-search" id="user-search" placeholder="搜索稳定 ID 或昵称"><button class="button" id="search-users">搜索</button></div>
    <div class="table-wrap"><table><thead><tr><th>展示名</th><th>稳定标识符</th><th>来源</th><th>消息数</th><th>首次出现</th><th>最近出现</th><th>最近会话</th></tr></thead><tbody>${users.map((user) => `<tr><td><strong>${esc(user.display_name || "-")}</strong></td><td class="mono">${esc(user.user_id)}</td><td>${esc(displayLabel(user.source_type))}</td><td>${user.message_count}</td><td>${esc(formatDate(user.first_seen_at))}</td><td>${esc(formatDate(user.last_seen_at))}</td><td><span class="truncate mono">${esc(user.last_conversation_id || "-")}</span></td></tr>`).join("") || '<tr><td colspan="7"><div class="empty-state">没有用户记录</div></td></tr>'}</tbody></table></div>`;
  document.querySelector("#search-users").onclick = renderUsers;
  document.querySelector("#user-search").onkeydown = (event) => { if (event.key === "Enter") renderUsers(); };
}

const LIFE_MODES = [
  ["projects", "私人项目"],
  ["plans", "每日计划"],
  ["activities", "活动记录"],
  ["diary", "日记"],
  ["sleep", "睡眠与梦境"],
  ["changes", "修改提案"],
];

function todayValue() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function lifeToolbar() {
  return `<div class="toolbar"><div class="segmented life-segments">${LIFE_MODES.map(([mode, label]) => `
    <button data-life-mode="${mode}" class="${state.lifeMode === mode ? "is-active" : ""}">${label}</button>`).join("")}
  </div></div>`;
}

async function renderLife() {
  const renderer = {
    projects: renderLifeProjects,
    plans: renderLifePlans,
    activities: renderLifeActivities,
    diary: renderLifeDiary,
    sleep: renderLifeSleep,
    changes: renderLifeChanges,
  }[state.lifeMode];
  viewRoot.innerHTML = `${lifeToolbar()}<div id="life-content"><div class="loading-state"><span></span>正在读取生活记录</div></div>`;
  viewRoot.querySelectorAll("[data-life-mode]").forEach((button) => {
    button.onclick = () => {
      state.lifeMode = button.dataset.lifeMode;
      renderLife();
    };
  });
  await renderer();
}

async function renderLifeProjects() {
  const projects = await api("/v1/life/projects?include_archived=true&limit=300");
  document.querySelector("#life-content").innerHTML = `
    <div class="toolbar"><button class="button is-primary" id="create-life-project">新建项目</button><div class="toolbar-spacer"></div><span class="badge">${projects.length}</span></div>
    <div class="table-wrap"><table><thead><tr><th>项目</th><th>目标</th><th>状态</th><th>版本</th><th>更新时间</th><th></th></tr></thead><tbody>${projects.map((project) => `
      <tr><td><strong>${esc(project.title)}</strong><span class="truncate metric-note">${esc(project.summary)}</span></td><td>${project.goals.map((goal) => `<span class="badge">${esc(goal)}</span>`).join(" ") || "-"}</td><td>${badge(project.status)}</td><td>v${project.version}</td><td>${esc(formatDate(project.updated_at))}</td><td><button class="button is-small" data-edit-life-project="${esc(project.project_id)}">编辑</button></td></tr>`).join("") || '<tr><td colspan="6"><div class="empty-state">没有私人项目</div></td></tr>'}</tbody></table></div>`;
  document.querySelector("#create-life-project").onclick = () => editLifeProject(null);
  document.querySelectorAll("[data-edit-life-project]").forEach((button) => {
    button.onclick = () => editLifeProject(projects.find((item) => item.project_id === button.dataset.editLifeProject));
  });
}

async function editLifeProject(project) {
  const data = await askForm({
    title: project ? "编辑私人项目" : "新建私人项目",
    body: `<div class="inline-form">
      <div class="form-row is-full"><label>标题</label><input class="field" name="title" value="${esc(project?.title || "")}" required></div>
      <div class="form-row is-full"><label>摘要</label><textarea class="textarea is-compact" name="summary" required>${esc(project?.summary || "")}</textarea></div>
      <div class="form-row is-full"><label>目标（每行一项）</label><textarea class="textarea is-compact" name="goals">${esc((project?.goals || []).join("\n"))}</textarea></div>
      ${project ? `<div class="form-row"><label>状态</label><select class="select" name="status">${["active", "paused", "completed", "archived"].map((value) => `<option value="${value}" ${project.status === value ? "selected" : ""}>${displayLabel(value)}</option>`).join("")}</select></div>` : ""}
    </div>`,
    submitLabel: "保存",
  });
  if (!data) return;
  const body = {
    title: String(data.get("title")).trim(),
    summary: String(data.get("summary")).trim(),
    goals: String(data.get("goals") || "").split("\n").map((value) => value.trim()).filter(Boolean),
  };
  if (project) {
    body.expected_version = project.version;
    body.status = String(data.get("status"));
  }
  try {
    await api(project ? `/v1/life/projects/${encodeURIComponent(project.project_id)}` : "/v1/life/projects", {
      method: project ? "PATCH" : "POST",
      body,
    });
    toast("项目已保存");
    renderLife();
  } catch (error) { toast(error.message, "error"); }
}

async function renderLifePlans() {
  const plans = await api("/v1/life/daily-plans?limit=180");
  const rows = plans.flatMap((plan) => plan.items.map((item) => ({ plan, item })));
  document.querySelector("#life-content").innerHTML = `
    <div class="toolbar"><button class="button is-primary" id="create-life-plan">新建计划</button><div class="toolbar-spacer"></div><span class="badge">${plans.length} 天</span></div>
    <div class="table-wrap"><table><thead><tr><th>日期</th><th>安排</th><th>类型</th><th>预计</th><th>状态</th><th></th></tr></thead><tbody>${rows.map(({ plan, item }) => `
      <tr><td><strong>${esc(plan.plan_date)}</strong><span class="metric-note">v${plan.version} · ${esc(plan.intention)}</span></td><td>${esc(item.title)}</td><td>${badge(item.kind)}</td><td>${item.expected_minutes} 分钟</td><td>${badge(item.status)}</td><td><button class="button is-small" data-transition-plan="${esc(plan.plan_id)}" data-plan-item="${esc(item.item_id)}">更新状态</button> <button class="button is-small" data-edit-life-plan="${esc(plan.plan_id)}">编辑计划</button></td></tr>`).join("") || '<tr><td colspan="6"><div class="empty-state">没有每日计划</div></td></tr>'}</tbody></table></div>`;
  document.querySelector("#create-life-plan").onclick = () => editLifePlan(null);
  document.querySelectorAll("[data-edit-life-plan]").forEach((button) => {
    button.onclick = () => editLifePlan(plans.find((item) => item.plan_id === button.dataset.editLifePlan));
  });
  document.querySelectorAll("[data-transition-plan]").forEach((button) => {
    const plan = plans.find((item) => item.plan_id === button.dataset.transitionPlan);
    const item = plan?.items.find((entry) => entry.item_id === button.dataset.planItem);
    button.onclick = () => transitionLifePlanItem(plan, item);
  });
}

async function editLifePlan(plan) {
  const defaultItems = plan?.items || [{ title: "", kind: "routine", expected_minutes: 30 }];
  const data = await askForm({
    title: plan ? "编辑每日计划" : "新建每日计划",
    body: `<div class="inline-form">
      <div class="form-row"><label>日期</label><input class="field" name="planDate" type="date" value="${esc(plan?.plan_date || todayValue())}" ${plan ? "disabled" : ""} required></div>
      <div class="form-row is-full"><label>当天意图</label><input class="field" name="intention" value="${esc(plan?.intention || "")}" required></div>
      <div class="form-row is-full"><label>计划项目（JSON）</label><textarea class="textarea" name="items" required>${esc(pretty(defaultItems))}</textarea></div>
    </div>`,
    submitLabel: "保存",
  });
  if (!data) return;
  let items;
  try { items = JSON.parse(String(data.get("items"))); } catch { toast("计划项目不是有效 JSON", "error"); return; }
  const planDate = plan?.plan_date || String(data.get("planDate"));
  const body = { intention: String(data.get("intention")).trim(), items };
  if (plan) body.expected_version = plan.version;
  try {
    await api(`/v1/life/daily-plans/${encodeURIComponent(planDate)}`, { method: "PUT", body });
    toast("每日计划已保存");
    renderLife();
  } catch (error) { toast(error.message, "error"); }
}

async function transitionLifePlanItem(plan, item) {
  if (!plan || !item) return;
  const data = await askForm({
    title: item.title,
    body: `<div class="form-row"><label>状态</label><select class="select" name="status">${["planned", "in_progress", "completed", "skipped"].map((value) => `<option value="${value}" ${item.status === value ? "selected" : ""}>${displayLabel(value)}</option>`).join("")}</select></div>`,
    submitLabel: "更新",
  });
  if (!data) return;
  try {
    await api(`/v1/life/daily-plans/${encodeURIComponent(plan.plan_date)}/items/${encodeURIComponent(item.item_id)}/status`, {
      method: "POST",
      body: { expected_version: plan.version, status: String(data.get("status")) },
    });
    toast("安排状态已更新");
    renderLife();
  } catch (error) { toast(error.message, "error"); }
}

async function renderLifeActivities() {
  const activities = await api("/v1/life/activities?limit=300");
  document.querySelector("#life-content").innerHTML = `
    <div class="toolbar"><button class="button is-primary" id="start-life-activity">开始活动</button><div class="toolbar-spacer"></div><span class="badge">${activities.length}</span></div>
    <div class="table-wrap"><table><thead><tr><th>活动</th><th>类型</th><th>状态</th><th>开始</th><th>结束</th><th>证据</th><th></th></tr></thead><tbody>${activities.map((activity) => `
      <tr><td><strong>${esc(activity.title)}</strong><span class="truncate metric-note">${esc(activity.summary || "-")}</span></td><td class="mono">${esc(activity.kind)}</td><td>${badge(activity.status)}</td><td>${esc(formatDate(activity.started_at))}</td><td>${esc(formatDate(activity.finished_at))}</td><td>${activity.evidence_ids.map((value) => `<span class="badge">${esc(shortId(value))}</span>`).join(" ") || "-"}</td><td>${activity.status === "running" ? `<button class="button is-small" data-finish-activity="${esc(activity.activity_id)}">结束</button>` : ""}</td></tr>`).join("") || '<tr><td colspan="7"><div class="empty-state">没有活动记录</div></td></tr>'}</tbody></table></div>`;
  document.querySelector("#start-life-activity").onclick = startLifeActivity;
  document.querySelectorAll("[data-finish-activity]").forEach((button) => {
    button.onclick = () => finishLifeActivity(activities.find((item) => item.activity_id === button.dataset.finishActivity));
  });
}

async function startLifeActivity() {
  const data = await askForm({
    title: "开始活动",
    body: `<div class="inline-form"><div class="form-row"><label>类型</label><input class="field" name="kind" value="routine" required></div><div class="form-row"><label>标题</label><input class="field" name="title" required></div><div class="form-row is-full"><label>摘要</label><textarea class="textarea is-compact" name="summary"></textarea></div></div>`,
    submitLabel: "开始",
  });
  if (!data) return;
  try {
    await api("/v1/life/activities", { method: "POST", body: { kind: String(data.get("kind")), title: String(data.get("title")), summary: String(data.get("summary") || "") } });
    toast("活动已开始");
    renderLife();
  } catch (error) { toast(error.message, "error"); }
}

async function finishLifeActivity(activity) {
  if (!activity) return;
  const data = await askForm({
    title: `结束活动 · ${activity.title}`,
    body: `<div class="inline-form"><div class="form-row"><label>结果</label><select class="select" name="status"><option value="completed">已完成</option><option value="failed">失败</option><option value="cancelled">已取消</option></select></div><div class="form-row is-full"><label>摘要</label><textarea class="textarea is-compact" name="summary">${esc(activity.summary)}</textarea></div><div class="form-row is-full"><label>证据 ID（每行一项）</label><textarea class="textarea is-compact" name="evidence"></textarea></div></div>`,
    submitLabel: "结束",
  });
  if (!data) return;
  try {
    await api(`/v1/life/activities/${encodeURIComponent(activity.activity_id)}/finish`, { method: "POST", body: { status: String(data.get("status")), summary: String(data.get("summary")), evidence_ids: String(data.get("evidence") || "").split("\n").map((value) => value.trim()).filter(Boolean) } });
    toast("活动已结束");
    renderLife();
  } catch (error) { toast(error.message, "error"); }
}

async function renderLifeDiary() {
  const diaries = await api("/v1/life/diary?limit=180");
  document.querySelector("#life-content").innerHTML = `
    <div class="toolbar"><button class="button is-primary" id="create-diary">新建日记</button><div class="toolbar-spacer"></div><span class="badge">${diaries.length}</span></div>
    <div class="table-wrap"><table><thead><tr><th>日期</th><th>内容</th><th>心情</th><th>状态</th><th>来源</th><th>版本</th><th></th></tr></thead><tbody>${diaries.map((diary) => `
      <tr><td><strong>${esc(diary.entry_date)}</strong><span class="metric-note">${esc(diary.generated_by)}</span></td><td><span class="truncate">${esc(diary.content)}</span></td><td>${esc(diary.mood_summary || "-")}</td><td>${badge(diary.status)}</td><td>${diary.source_activity_ids.length} 活动 · ${diary.source_memory_ids.length} 记忆 · ${diary.dream_record_ids.length} 梦境</td><td>v${diary.version}</td><td><button class="button is-small" data-edit-diary="${esc(diary.diary_id)}">编辑</button></td></tr>`).join("") || '<tr><td colspan="7"><div class="empty-state">没有日记</div></td></tr>'}</tbody></table></div>`;
  document.querySelector("#create-diary").onclick = () => editLifeDiary(null);
  document.querySelectorAll("[data-edit-diary]").forEach((button) => {
    button.onclick = () => editLifeDiary(diaries.find((item) => item.diary_id === button.dataset.editDiary));
  });
}

async function editLifeDiary(diary) {
  const data = await askForm({
    title: diary ? "编辑日记" : "新建日记",
    body: `<div class="inline-form"><div class="form-row"><label>日期</label><input class="field" name="entryDate" type="date" value="${esc(diary?.entry_date || todayValue())}" ${diary ? "disabled" : ""} required></div><div class="form-row"><label>状态</label><select class="select" name="status"><option value="draft" ${diary?.status !== "published" ? "selected" : ""}>草稿</option><option value="published" ${diary?.status === "published" ? "selected" : ""}>已发布</option></select></div><div class="form-row is-full"><label>内容</label><textarea class="textarea" name="content" required>${esc(diary?.content || "")}</textarea></div><div class="form-row is-full"><label>心情摘要</label><input class="field" name="mood" value="${esc(diary?.mood_summary || "")}"></div></div>`,
    submitLabel: "保存",
  });
  if (!data) return;
  const body = {
    content: String(data.get("content")), mood_summary: String(data.get("mood") || ""), status: String(data.get("status")),
    source_activity_ids: diary?.source_activity_ids || [], source_memory_ids: diary?.source_memory_ids || [], dream_record_ids: diary?.dream_record_ids || [],
  };
  if (diary) body.expected_version = diary.version;
  try {
    await api(`/v1/life/diary/${encodeURIComponent(diary?.entry_date || String(data.get("entryDate")))}`, { method: "PUT", body });
    toast("日记已保存");
    renderLife();
  } catch (error) { toast(error.message, "error"); }
}

async function renderLifeSleep() {
  const [cycles, dreams] = await Promise.all([api("/v1/life/sleep-cycles?limit=180"), api("/v1/life/dreams?limit=180")]);
  document.querySelector("#life-content").innerHTML = `
    <div class="toolbar"><input class="field" id="sleep-cycle-date" type="date" value="${todayValue()}"><button class="button is-primary" id="run-sleep-cycle">运行睡眠周期</button><div class="toolbar-spacer"></div><span class="badge is-ok">现实记忆自动写入 0</span></div>
    <section><div class="section-heading"><h2>睡眠周期</h2><span class="badge">${cycles.length}</span></div><div class="table-wrap"><table><thead><tr><th>日期</th><th>状态</th><th>触发</th><th>现实记忆</th><th>候选审查</th><th>重复簇</th><th>自动写入</th><th>结束</th></tr></thead><tbody>${cycles.map((cycle) => `<tr><td>${esc(cycle.cycle_date)}</td><td>${badge(cycle.status)}</td><td>${esc(cycle.trigger)}</td><td>${cycle.reality_memory_ids.length}</td><td>${cycle.candidate_review_ids.length}</td><td>${cycle.duplicate_memory_clusters.length}</td><td>${cycle.automatic_memory_writes}</td><td>${esc(formatDate(cycle.finished_at))}</td></tr>`).join("") || '<tr><td colspan="8"><div class="empty-state">没有睡眠周期</div></td></tr>'}</tbody></table></div></section>
    <section class="band"><div class="section-heading"><h2>梦境</h2><span class="badge">${dreams.length}</span></div><div class="table-wrap"><table><thead><tr><th>日期</th><th>内容</th><th>事实性</th><th>现实可用</th><th>种子</th><th></th></tr></thead><tbody>${dreams.map((dream) => `<tr><td>${esc(dream.dream_date)}</td><td><span class="truncate">${esc(dream.content)}</span></td><td>${badge(dream.factuality)}</td><td>${dream.reality_eligible ? badge("allow") : badge("deny")}</td><td>${dream.seed_activity_ids.length} 活动 · ${dream.seed_memory_ids.length} 记忆</td><td><button class="button is-small" data-view-dream="${esc(dream.dream_id)}">查看</button></td></tr>`).join("") || '<tr><td colspan="6"><div class="empty-state">没有梦境</div></td></tr>'}</tbody></table></div></section>`;
  document.querySelector("#run-sleep-cycle").onclick = async () => {
    const cycleDate = document.querySelector("#sleep-cycle-date").value;
    if (!await confirmAction("运行睡眠周期", cycleDate, "运行")) return;
    try { await api("/v1/life/sleep-cycles/run", { method: "POST", body: { cycle_date: cycleDate } }); toast("睡眠周期已完成"); renderLife(); } catch (error) { toast(error.message, "error"); }
  };
  document.querySelectorAll("[data-view-dream]").forEach((button) => {
    button.onclick = async () => {
      const dream = dreams.find((item) => item.dream_id === button.dataset.viewDream);
      await askForm({ title: `梦境 · ${dream.dream_date}`, body: `<div class="status-strip">${badge(dream.factuality)}<span class="badge is-error">不可写入现实记忆</span></div><pre class="content-block">${esc(dream.content)}</pre><pre class="json-block">${esc(pretty({ seed_activity_ids: dream.seed_activity_ids, seed_memory_ids: dream.seed_memory_ids }))}</pre>`, submitLabel: "关闭" });
    };
  });
}

async function renderLifeChanges() {
  const proposals = await api("/v1/life/self-change-proposals?limit=300");
  document.querySelector("#life-content").innerHTML = `
    <div class="table-wrap"><table><thead><tr><th>目标</th><th>理由</th><th>基础版本</th><th>测试</th><th>状态</th><th>创建时间</th><th></th></tr></thead><tbody>${proposals.map((proposal) => `
      <tr><td>${badge(proposal.target_kind)} <span class="mono">${esc(proposal.target_path)}</span></td><td><span class="truncate">${esc(proposal.rationale)}</span></td><td>v${proposal.base_version}</td><td>${proposal.test_results.passed ? badge("success") : badge("failed")}</td><td>${badge(proposal.status)}</td><td>${esc(formatDate(proposal.created_at))}</td><td><button class="button is-small" data-view-proposal="${esc(proposal.proposal_id)}">详情</button> ${["ready", "test_failed"].includes(proposal.status) ? `<button class="button is-small is-danger" data-reject-proposal="${esc(proposal.proposal_id)}">拒绝</button>` : ""} ${proposal.status === "ready" ? `<button class="button is-small is-primary" data-approve-proposal="${esc(proposal.proposal_id)}">批准部署</button>` : ""}</td></tr>`).join("") || '<tr><td colspan="7"><div class="empty-state">没有自我修改提案</div></td></tr>'}</tbody></table></div>`;
  document.querySelectorAll("[data-view-proposal]").forEach((button) => {
    button.onclick = async () => {
      const proposal = proposals.find((item) => item.proposal_id === button.dataset.viewProposal);
      await askForm({ title: `${proposal.target_path} · ${displayLabel(proposal.status)}`, body: `<dl class="detail-grid"><dt>提案者</dt><dd>${esc(proposal.proposer_id)}</dd><dt>理由</dt><dd>${esc(proposal.rationale)}</dd><dt>来源日记</dt><dd>${proposal.source_diary_ids.map((value) => esc(shortId(value))).join(", ") || "-"}</dd><dt>来源梦境</dt><dd>${proposal.source_dream_ids.map((value) => esc(shortId(value))).join(", ") || "-"}</dd></dl><pre class="diff-block">${esc(proposal.diff)}</pre><pre class="json-block">${esc(pretty(proposal.test_results))}</pre>`, submitLabel: "关闭" });
    };
  });
  document.querySelectorAll("[data-approve-proposal]").forEach((button) => {
    button.onclick = async () => {
      if (!await confirmAction("批准并部署", button.dataset.approveProposal, "部署")) return;
      try { await api(`/v1/life/self-change-proposals/${encodeURIComponent(button.dataset.approveProposal)}/approve`, { method: "POST" }); toast("提案已部署"); renderLife(); } catch (error) { toast(error.message, "error"); }
    };
  });
  document.querySelectorAll("[data-reject-proposal]").forEach((button) => {
    button.onclick = async () => {
      if (!await confirmAction("拒绝提案", button.dataset.rejectProposal, "拒绝", true)) return;
      try { await api(`/v1/life/self-change-proposals/${encodeURIComponent(button.dataset.rejectProposal)}/reject`, { method: "POST" }); toast("提案已拒绝"); renderLife(); } catch (error) { toast(error.message, "error"); }
    };
  });
}

async function renderAudit() {
  state.audit = await api("/v1/audit?limit=500");
  const filter = document.querySelector("#audit-filter")?.value.toLowerCase() || "";
  const outcome = document.querySelector("#audit-outcome")?.value || "";
  const entries = state.audit.filter((entry) => (!filter || `${entry.action} ${entry.actor_id} ${entry.conversation_id}`.toLowerCase().includes(filter)) && (!outcome || entry.outcome === outcome));
  viewRoot.innerHTML = `<div class="toolbar"><input class="field is-search" id="audit-filter" placeholder="动作、操作者或会话"><select class="select" id="audit-outcome"><option value="">全部结果</option>${[...new Set(state.audit.map((entry) => entry.outcome))].sort().map((value) => `<option value="${esc(value)}" ${value === outcome ? "selected" : ""}>${esc(displayLabel(value))}</option>`).join("")}</select><button class="button" id="filter-audit">筛选</button><div class="toolbar-spacer"></div><span class="badge">${entries.length} / ${state.audit.length}</span></div>
    <div class="table-wrap"><table><thead><tr><th>时间</th><th>动作</th><th>结果</th><th>操作者</th><th>会话</th><th></th></tr></thead><tbody>${entries.map((entry) => `<tr><td>${esc(formatDate(entry.created_at))}</td><td class="mono">${esc(entry.action)}</td><td>${badge(entry.outcome)}</td><td><span class="truncate">${esc(entry.actor_id || "-")}</span></td><td><span class="truncate mono">${esc(entry.conversation_id || "-")}</span></td><td><button class="button is-small" data-audit-id="${esc(entry.audit_id)}">详情</button></td></tr>`).join("")}</tbody></table></div>`;
  document.querySelector("#filter-audit").onclick = renderAudit;
  viewRoot.querySelectorAll("[data-audit-id]").forEach((button) => {
    button.onclick = async () => {
      const entry = entries.find((item) => item.audit_id === button.dataset.auditId);
      await askForm({ title: entry.action, body: `<pre class="json-block">${esc(pretty(entry))}</pre>`, submitLabel: "关闭" });
    };
  });
}

async function renderVersions() {
  const personaRequests = PERSONA_LAYERS.map(async (layer) => ({ kind: "persona", key: layer, items: await api(`/v1/persona/${layer}/history`) }));
  const promptRequests = PROMPTS.map(async ([category, name]) => ({ kind: "prompt", key: `${category}/${name}`, items: await api(`/v1/prompts/${category}/${name}/history`) }));
  const groups = await Promise.all([...personaRequests, ...promptRequests]);
  const versions = groups.flatMap((group) => group.items.map((item) => ({ ...item, uiKind: group.kind, uiKey: group.key }))).sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  viewRoot.innerHTML = `<div class="table-wrap"><table><thead><tr><th>类型</th><th>路径</th><th>版本</th><th>变更</th><th>操作者</th><th>时间</th><th></th></tr></thead><tbody>${versions.map((item, index) => `<tr><td>${badge(item.uiKind)}</td><td class="mono">${esc(item.artifact_path)}</td><td>v${item.version}</td><td>${esc(displayLabel(item.change_type))}</td><td>${esc(item.actor_id)}</td><td>${esc(formatDate(item.created_at))}</td><td><button class="button is-small" data-version-index="${index}">查看</button> <button class="button is-small" data-edit-version="${index}">打开编辑器</button></td></tr>`).join("")}</tbody></table></div>`;
  viewRoot.querySelectorAll("[data-version-index]").forEach((button) => {
    button.onclick = async () => {
      const item = versions[Number(button.dataset.versionIndex)];
      await askForm({ title: `${item.artifact_path} · v${item.version}`, body: `<pre class="content-block">${esc(item.content)}</pre>`, submitLabel: "关闭" });
    };
  });
  viewRoot.querySelectorAll("[data-edit-version]").forEach((button) => {
    button.onclick = () => {
      const item = versions[Number(button.dataset.editVersion)];
      if (item.uiKind === "persona") state.personaLayer = item.uiKey;
      else state.promptKey = item.uiKey;
      setView(item.uiKind === "persona" ? "persona" : "prompts");
    };
  });
}

async function renderSimulator() {
  viewRoot.innerHTML = `
    <div class="simulator-layout">
      <form class="simulator-form" id="simulator-form">
        <div class="inline-form">
          <div class="form-row is-full"><label>消息内容</label><textarea class="textarea" name="content" required>${esc(state.simulatorResult?.event?.content?.text || "你觉得这个计划怎么样？")}</textarea></div>
          <div class="form-row"><label>来源类型</label><select class="select" name="source_type">${["direct_message", "group_message", "webpage", "file", "tool_result", "plugin_result"].map((value) => `<option value="${value}">${displayLabel(value)}</option>`).join("")}</select></div>
          <div class="form-row"><label>来源标识符</label><input class="field" name="source_identity" value="simulator-user"></div>
          <div class="form-row"><label>会话</label><input class="field" name="conversation_id" value="simulator-conversation"></div>
          <div class="form-row"><label>认证状态</label><select class="select" name="authenticated"><option value="true">已认证</option><option value="false">未认证</option></select></div>
          <div class="form-row"><label>群聊点名</label><select class="select" name="mentions_agent"><option value="true">已点名</option><option value="false">未点名</option></select></div>
        </div>
        <div class="toolbar band"><button class="button is-primary" type="submit">运行模拟</button><span class="badge is-info">不持久化</span><span class="badge is-info">无实际影响</span></div>
      </form>
      <section id="simulator-result">${state.simulatorResult ? simulatorResult(state.simulatorResult) : '<div class="empty-state">等待模拟输入</div>'}</section>
    </div>`;
  document.querySelector("#simulator-form").onsubmit = async (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const sourceType = String(data.get("source_type"));
    const content = {
      text: String(data.get("content")),
      mentions_agent: String(data.get("mentions_agent")) === "true",
    };
    try {
      state.simulatorResult = await api("/v1/simulator/turn", { method: "POST", body: {
        content,
        source_type: sourceType,
        source_identity: String(data.get("source_identity")) || null,
        conversation_id: String(data.get("conversation_id")) || null,
        authenticated: String(data.get("authenticated")) === "true",
      }});
      document.querySelector("#simulator-result").innerHTML = simulatorResult(state.simulatorResult);
    } catch (error) { toast(error.message, "error"); }
  };
}

function simulatorResult(result) {
  return `
    <div class="decision-banner"><div class="decision-mode">${esc(displayLabel(result.turn.mode))}</div><div><strong>${esc(result.turn.reason_code)}</strong><div class="metric-note">紧急度 ${result.turn.urgency} · ${result.turn.expected_units_min}-${result.turn.expected_units_max} 个消息单元</div></div></div>
    <section class="band"><h3>可信边界</h3><dl class="detail-grid"><dt>身份</dt><dd>${esc(result.event.source_identity || "匿名")}</dd><dt>信任</dt><dd>${badge(result.event.trust_level)}</dd><dt>权限</dt><dd>${badge(result.event.authority_level)}</dd><dt>污染标签</dt><dd>${[...result.event.taint_labels].map((value) => `<span class="badge is-warn">${esc(value)}</span>`).join(" ") || "无"}</dd></dl></section>
    <section class="band"><h3>会话动量</h3><pre class="json-block">${esc(pretty(result.momentum))}</pre></section>
    <section class="band"><h3>上下文区段</h3><div class="status-strip">${result.context_sections.map((value) => `<span class="badge">${esc(value)}</span>`).join("")}</div></section>
    ${result.task_steps.length ? `<section class="band"><h3>${esc(result.task_goal)}</h3>${result.task_steps.map((step) => `<div class="item-card"><div class="item-card-header"><strong>${esc(step.title)}</strong>${badge(step.requires_confirmation ? "ASK_OWNER" : "brokered")}</div><div class="item-card-subtitle mono">${esc(step.capability)} / ${esc(step.operation)} / ${esc(step.handler)}</div></div>`).join("")}</section>` : ""}
    <section class="band"><div class="status-strip"><span class="badge ${result.would_call_model ? "is-warn" : "is-ok"}">模型调用：${result.would_call_model ? "是" : "否"}</span><span class="badge ${result.would_execute_tools ? "is-warn" : "is-ok"}">工具：${result.would_execute_tools ? "已提议" : "无"}</span><span class="badge is-ok">未持久化</span><span class="badge is-ok">无实际影响</span></div></section>`;
}

async function openIdentityDialog() {
  const data = await askForm({
    title: "管理认证",
    body: `<div class="form-row"><label>所有者稳定 ID</label><input class="field" name="actorId" value="${esc(state.actorId)}" autocomplete="off" required></div><div class="form-row"><label>管理令牌</label><input class="field" name="managementToken" type="password" autocomplete="off" placeholder="${state.managementToken ? "已在当前会话设置" : "未设置"}"></div>`,
    submitLabel: "应用",
  });
  if (!data) return;
  state.actorId = String(data.get("actorId")).trim();
  const suppliedToken = String(data.get("managementToken") || "");
  if (suppliedToken) state.managementToken = suppliedToken;
  actorInput.value = state.actorId;
  managementTokenInput.value = state.managementToken;
  localStorage.setItem("living-agent.actor-id", state.actorId);
  sessionStorage.setItem("living-agent.management-token", state.managementToken);
  toast("管理认证已更新");
  renderCurrentView();
}

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});
document.querySelector("#refresh-view").addEventListener("click", renderCurrentView);
document.querySelector("#open-auth").addEventListener("click", openIdentityDialog);
document.querySelector("#save-actor").addEventListener("click", () => {
  state.actorId = actorInput.value.trim();
  localStorage.setItem("living-agent.actor-id", state.actorId);
  toast("管理身份已应用");
  renderCurrentView();
});
document.querySelector("#save-token").addEventListener("click", () => {
  state.managementToken = managementTokenInput.value;
  sessionStorage.setItem("living-agent.management-token", state.managementToken);
  toast("管理令牌已应用");
  renderCurrentView();
});
document.querySelector("#mobile-menu").addEventListener("click", () => {
  document.querySelector(".primary-nav").scrollIntoView({ behavior: "smooth", block: "nearest" });
});

const initialView = window.location.hash.slice(1);
if (VIEW_META[initialView]) state.view = initialView;
document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("is-active", item.dataset.view === state.view));
[viewTitle.textContent, viewMeta.textContent] = VIEW_META[state.view];
checkHealth();
renderCurrentView();
