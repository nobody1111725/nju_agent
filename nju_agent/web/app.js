const MAX_ATTACHMENTS_PER_TURN = 10;
const MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024;
const state = { sessionId: null, sending: false, uploading: false, messages: [], attachments: [], toolRuns: [], answerTyping: null, answerTypingTimer: null, pendingComplete: null };
const $ = (id) => document.getElementById(id);
const messages = $("messages");
const prompt = $("prompt");

function escapeHtml(value) { return String(value).replace(/[&<>"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch])); }
function inlineMarkdown(value) {
  const tokens = [];
  let text = escapeHtml(value);
  text = text.replace(/`([^`\n]+)`/g, (_, code) => { tokens.push(`<code>${code}</code>`); return `\u0000${tokens.length - 1}\u0000`; });
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) => `<a href="${url}" target="_blank" rel="noreferrer">${label}</a>`);
  text = text.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>").replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
  text = text.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>").replace(/(^|[^_])_([^_\n]+)_(?!_)/g, "$1<em>$2</em>");
  return text.replace(/\u0000(\d+)\u0000/g, (_, index) => tokens[Number(index)]);
}
function markdownToHtml(value) {
  const lines = String(value).replace(/\r\n?/g, "\n").split("\n");
  const output = []; let paragraph = []; let list = null; let inCode = false; let codeLanguage = ""; let code = [];
  const flushParagraph = () => { if (paragraph.length) { output.push(`<p>${inlineMarkdown(paragraph.join("\n")).replace(/\n/g, "<br>")}</p>`); paragraph = []; } };
  const flushList = () => { if (!list) return; output.push(`<${list.type}>${list.items.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</${list.type}>`); list = null; };
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]; const fence = line.match(/^\s*```\s*([\w+-]*)\s*$/);
    if (fence) { if (!inCode) { flushParagraph(); flushList(); inCode = true; codeLanguage = fence[1]; code = []; } else { output.push(`<pre><code${codeLanguage ? ` class="language-${escapeHtml(codeLanguage)}"` : ""}>${escapeHtml(code.join("\n"))}</code></pre>`); inCode = false; codeLanguage = ""; } continue; }
    if (inCode) { code.push(line); continue; }
    const heading = line.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) { flushParagraph(); flushList(); const level = heading[1].length; output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`); continue; }
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/); const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (unordered || ordered) { flushParagraph(); const type = unordered ? "ul" : "ol"; if (!list || list.type !== type) { flushList(); list = { type, items: [] }; } list.items.push((unordered || ordered)[1]); continue; }
    if (/^\s*$/.test(line)) { flushParagraph(); flushList(); continue; }
    const next = lines[index + 1] || "";
    if (/^\s*\|?.+\|.+\|?\s*$/.test(line) && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(next)) {
      flushParagraph(); flushList();
      const cells = (row) => row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => inlineMarkdown(cell.trim()));
      const headers = cells(line); index += 1; const rows = [];
      while (index + 1 < lines.length && /^\s*\|?.+\|.+\|?\s*$/.test(lines[index + 1])) { index += 1; rows.push(cells(lines[index])); }
      output.push(`<div class="table-scroll"><table><thead><tr>${headers.map((cell) => `<th>${cell}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((_, cellIndex) => `<td>${row[cellIndex] || ""}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`); continue;
    }
    paragraph.push(line);
  }
  if (inCode) output.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
  flushParagraph(); flushList(); return output.join("");
}
function renderMessages(items) {
  const indexedRuns = new Map();
  const legacyRuns = [];
  (Array.isArray(state.toolRuns) ? state.toolRuns : []).forEach((run) => {
    if (run && Object.prototype.hasOwnProperty.call(run, "assistant_message_index")) {
      if (Number.isInteger(run.assistant_message_index)) indexedRuns.set(run.assistant_message_index, run);
    } else legacyRuns.push(run);
  });
  let completedTurn = 0;
  messages.innerHTML = items.length ? items.map((item, messageIndex) => {
    let toolRun = "";
    if (item.role === "assistant") {
      toolRun = renderToolRun(indexedRuns.get(messageIndex) || legacyRuns[completedTurn], completedTurn);
      completedTurn += 1;
    }
    const attachments = item.role === "user" ? renderMessageAttachments(item.attachments) : "";
    return `<article class="message ${item.role}"><div class="avatar ${item.role}">${item.role === "user" ? "你" : "N"}</div><div class="message-content"><div class="message-body">${item.role === "assistant" ? markdownToHtml(item.content) : escapeHtml(item.content)}</div>${attachments}${toolRun}</div></article>`;
  }).join("") : `<div class="empty-state"><div class="empty-mark">N</div><h1>开始编程工作</h1><p>描述要修改、检查或运行的代码任务。</p></div>`;
  if (state.sending) {
    const currentTurn = messages.querySelector(".message.user:last-of-type .message-content");
    if (currentTurn) {
      const rail = document.createElement("div");
      rail.id = "toolRail";
      rail.className = "tool-rail";
      currentTurn.appendChild(rail);
    }
  }
  messages.querySelectorAll("details[data-run-id]").forEach((detail) => detail.addEventListener("toggle", () => saveToolRunOpen(detail.dataset.runId, detail.open)));
  renderTypingAnswer();
  messages.scrollTop = messages.scrollHeight;
}
function stopAnswerTypingTimer() {
  if (state.answerTypingTimer !== null) window.clearTimeout(state.answerTypingTimer);
  state.answerTypingTimer = null;
}
function renderTypingAnswer() {
  let node = messages.querySelector("#typingAnswer");
  if (!state.answerTyping) { if (node) node.remove(); return; }
  if (!node) {
    node = document.createElement("article");
    node.id = "typingAnswer";
    node.className = "message agent";
    node.innerHTML = '<div class="avatar agent">N</div><div class="message-content"><div class="message-body"></div></div>';
    messages.appendChild(node);
  }
  const chars = Array.from(state.answerTyping.text);
  const visible = chars.slice(0, state.answerTyping.index).join("");
  const body = node.querySelector(".message-body");
  body.innerHTML = `${markdownToHtml(visible)}<span class="typing-cursor" aria-hidden="true"></span>`;
  messages.scrollTop = messages.scrollHeight;
}
function advanceAnswerTyping() {
  const typing = state.answerTyping;
  if (!typing) return;
  const length = Array.from(typing.text).length;
  if (typing.index < length) {
    typing.index += 1;
    renderTypingAnswer();
  }
  if (typing.index < length) {
    state.answerTypingTimer = window.setTimeout(advanceAnswerTyping, 16);
  } else {
    state.answerTypingTimer = null;
    if (state.pendingComplete) finishComplete(state.pendingComplete);
  }
}
function startAnswerTyping(answer) {
  stopAnswerTypingTimer();
  state.pendingComplete = null;
  state.answerTyping = { text: String(answer || ""), index: 0 };
  setThinking(false);
  renderTypingAnswer();
  advanceAnswerTyping();
}
function finishComplete(data) {
  stopAnswerTypingTimer();
  state.answerTyping = null;
  state.pendingComplete = null;
  setThinking(false);
  if (data.id) state.sessionId = data.id;
  if (Array.isArray(data.messages)) {
    state.messages = data.messages;
    $("sessionTitle").textContent = state.messages.find((m) => m.role === "user")?.content || "已保存会话";
  }
  if (Array.isArray(data.tool_runs)) state.toolRuns = data.tool_runs;
  state.sending = false;
  renderMessages(state.messages);
  renderModifiedFiles();
  if (data.error) throw new Error(data.error);
  state.attachments = [];
  renderAttachments();
  setAttachmentNotice("");
  $("send").disabled = false;
  $("attachments").disabled = false;
  prompt.focus();
}
function renderMessageAttachments(attachments) {
  const values = Array.isArray(attachments) ? attachments.filter((item) => item && typeof item.name === "string" && Number.isFinite(item.size)) : [];
  if (!values.length) return "";
  return `<div class="message-attachments">${values.map((item) => `<span class="message-attachment" title="${escapeHtml(item.name)}">${escapeHtml(item.name)} <small>${formatBytes(item.size)}</small></span>`).join("")}</div>`;
}
function setThinking(visible) {
  const rail = $("toolRail");
  const existing = rail.querySelector(".thinking-indicator");
  if (!visible) { if (existing) existing.remove(); return; }
  if (existing) return;
  const node = document.createElement("div");
  node.className = "thinking-indicator";
  node.innerHTML = '<span class="thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span><span>正在思考</span>';
  rail.appendChild(node);
  messages.scrollTop = messages.scrollHeight;
}
function renderDiff(diff) {
  if (!diff || !Array.isArray(diff.lines) || !diff.lines.length) return null;
  const summary = `修改前后差异 · ${diff.path} (+${diff.added || 0} / -${diff.removed || 0})`;
  const lines = diff.lines.map((line) => {
    let kind = "context";
    if (line.startsWith("@@") || line.startsWith("---") || line.startsWith("+++")) kind = "meta";
    else if (line.startsWith("+")) kind = "added";
    else if (line.startsWith("-")) kind = "removed";
    return `<div class="diff-line ${kind}"><span>${escapeHtml(line)}</span></div>`;
  }).join("");
  return `<details class="diff-view" open><summary>${escapeHtml(summary)}</summary><div class="diff-lines">${lines}</div></details>`;
}
function toolRunStorageKey(runId) { return `nju-agent:tool-run:${state.sessionId || "new"}:${runId}`; }
function getToolRunOpen(runId) {
  try { return localStorage.getItem(toolRunStorageKey(runId)) !== "collapsed"; } catch (_) { return true; }
}
function saveToolRunOpen(runId, open) {
  try { localStorage.setItem(toolRunStorageKey(runId), open ? "open" : "collapsed"); } catch (_) { /* Browser storage can be disabled. */ }
}
function renderToolRun(run, index) {
  if (!run || typeof run !== "object") return "";
  const id = typeof run.id === "string" ? run.id : `legacy-${index}`;
  const events = Array.isArray(run.events) ? run.events : [];
  if (!events.length) return "";
  const details = events.map((event) => `<div class="tool-history-event ${escapeHtml(event.status || "failed")}"><span>${event.status === "done" ? "✓" : "×"}  ${escapeHtml(event.label || event.name || "工具调用")}</span>${renderDiff(event.diff) || ""}</div>`).join("");
  return `<details class="tool-run" data-run-id="${escapeHtml(id)}"${getToolRunOpen(id) ? " open" : ""}><summary>运行指令 <small>${events.length} 项</small></summary><div class="tool-history-events">${details}</div></details>`;
}
function renderModifiedFiles() {
  const panel = $("modifiedFilesPanel");
  const list = $("modifiedFiles");
  const files = new Map();
  (Array.isArray(state.toolRuns) ? state.toolRuns : []).forEach((run) => (Array.isArray(run?.events) ? run.events : []).forEach((event) => {
    const path = event?.diff?.path;
    if (typeof path === "string" && path.trim()) files.set(path, (files.get(path) || 0) + 1);
  }));
  panel.hidden = files.size === 0 || !state.sessionId;
  list.innerHTML = [...files.entries()].map(([path, count]) => `<a class="modified-file" href="/api/modified-file?session_id=${encodeURIComponent(state.sessionId)}&path=${encodeURIComponent(path)}" target="_blank" rel="noreferrer" title="打开 ${escapeHtml(path)}"><span>${escapeHtml(path)}</span><small>${count} 次</small></a>`).join("");
}
async function loadSessions() {
  const response = await fetch("/api/sessions");
  const data = await response.json();
  const list = $("sessions");
  list.innerHTML = (data.sessions || []).map((item) => `<div class="session-row"><button class="session-item ${item.id === state.sessionId ? "active" : ""}" data-id="${escapeHtml(item.id)}">${escapeHtml(item.messages.find((m) => m.role === "user")?.content || "新会话")}<small>${escapeHtml(item.short_id)}</small></button><button class="session-delete" data-id="${escapeHtml(item.id)}" title="删除会话" aria-label="删除会话 ${escapeHtml(item.short_id)}">&#128465;</button></div>`).join("");
  list.querySelectorAll(".session-item").forEach((button) => button.addEventListener("click", () => openSession(button.dataset.id)));
  list.querySelectorAll(".session-delete").forEach((button) => button.addEventListener("click", (event) => { event.stopPropagation(); deleteSession(button.dataset.id); }));
}
async function openSession(id) {
  const response = await fetch(`/api/sessions/${encodeURIComponent(id)}`);
  if (!response.ok) return;
  const data = await response.json(); state.sessionId = data.id; state.messages = Array.isArray(data.messages) ? data.messages : []; state.toolRuns = Array.isArray(data.tool_runs) ? data.tool_runs : []; $("sessionTitle").textContent = state.messages.find((m) => m.role === "user")?.content || "已恢复会话"; renderMessages(state.messages); renderModifiedFiles(); await loadSessions();
}
function newChat() { stopAnswerTypingTimer(); state.answerTyping = null; state.pendingComplete = null; state.sessionId = null; state.messages = []; state.attachments = []; state.toolRuns = []; renderAttachments(); $("sessionTitle").textContent = "新对话"; renderMessages(state.messages); renderModifiedFiles(); loadSessions(); prompt.focus(); }
async function deleteSession(id) {
  if (state.sending || state.uploading || !id) return;
  if (!window.confirm("确定删除这个会话及其全部聊天记录吗？此操作不可撤销。")) return;
  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "删除会话失败");
    if (state.sessionId === id) newChat();
    else await loadSessions();
  } catch (error) { window.alert(`删除会话失败：${error.message}`); }
}
function renderAttachments() {
  const list = $("attachmentList");
  list.innerHTML = state.attachments.map((item, index) => `<span class="attachment-chip"><span class="attachment-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span><small>${formatBytes(item.size)}</small><button type="button" data-attachment-index="${index}" title="取消上传" aria-label="取消上传 ${escapeHtml(item.name)}">×</button></span>`).join("");
  list.querySelectorAll("button[data-attachment-index]").forEach((button) => button.addEventListener("click", () => removeAttachment(Number(button.dataset.attachmentIndex))));
}
async function removeAttachment(index) {
  if (state.sending || state.uploading || !state.attachments[index]) return;
  const attachment = state.attachments[index];
  try {
    const response = await fetch(`/api/uploads?path=${encodeURIComponent(attachment.path)}`, { method: "DELETE" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "取消上传失败");
    state.attachments.splice(index, 1);
    renderAttachments();
    setAttachmentNotice(`已取消上传 ${attachment.name}`);
  } catch (error) { setAttachmentNotice(`${attachment.name}: ${error.message}`, true); }
}
function formatBytes(size) { if (size < 1024) return `${size} B`; if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`; return `${(size / (1024 * 1024)).toFixed(1)} MB`; }
function setAttachmentNotice(message, isError = false) { const notice = $("attachmentNotice"); notice.textContent = message; notice.className = `attachment-notice${isError ? " error" : ""}`; }
async function uploadAttachment(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) binary += String.fromCharCode(bytes[index]);
  const response = await fetch("/api/uploads", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: file.name, content_base64: btoa(binary) }) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "附件上传失败");
  return data;
}
async function handleAttachments(event) {
  const files = [...event.target.files]; event.target.value = "";
  await uploadFiles(files);
}
async function uploadFiles(files) {
  if (state.sending) { setAttachmentNotice("Agent 正在执行，完成后再添加附件", true); return; }
  if (!files.length) return;
  const remaining = MAX_ATTACHMENTS_PER_TURN - state.attachments.length;
  const selected = files.slice(0, Math.max(remaining, 0));
  if (!selected.length) { setAttachmentNotice(`每轮最多添加 ${MAX_ATTACHMENTS_PER_TURN} 个附件`, true); return; }
  state.uploading = true; $("send").disabled = true;
  setAttachmentNotice(`正在上传 ${selected.length} 个附件...`);
  for (const file of selected) {
    if (file.size > MAX_ATTACHMENT_BYTES) { setAttachmentNotice(`${file.name}: 附件不能超过 2 MB`, true); continue; }
    try {
      const uploaded = await uploadAttachment(file);
      if (!state.attachments.some((item) => item.path === uploaded.path)) state.attachments.push(uploaded);
    } catch (error) { setAttachmentNotice(`${file.name}: ${error.message}`, true); }
  }
  state.uploading = false; $("send").disabled = false;
  renderAttachments();
  if (files.length > selected.length) setAttachmentNotice(`最多 ${MAX_ATTACHMENTS_PER_TURN} 个附件，已忽略 ${files.length - selected.length} 个`, true);
  else if (state.attachments.length && !$("attachmentNotice").classList.contains("error")) setAttachmentNotice(`已添加 ${state.attachments.length} 个附件`);
}
function appendTool(data, running) { const rail = $("toolRail"); const id = `${data.name}-${rail.children.length}`; const node = document.createElement("div"); node.className = `tool-event ${running ? "running" : data.status}`; node.dataset.toolId = id; node.textContent = `${running ? "◌" : data.status === "done" ? "✓" : "×"}  ${data.label}`; rail.appendChild(node); messages.scrollTop = messages.scrollHeight; return id; }
async function sendTask(event) {
  event.preventDefault(); if (state.sending || state.uploading || !prompt.value.trim()) return;
  const task = prompt.value.trim(); prompt.value = ""; state.sending = true; $("send").disabled = true; $("attachments").disabled = true;
  const previousMessages = state.messages.slice();
  state.messages = [...previousMessages, { role: "user", content: task, attachments: state.attachments.map((item) => ({ name: item.name, size: item.size })) }];
  renderMessages(state.messages);
  try {
    const response = await fetch("/api/chat/stream", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: state.sessionId, task, attachments: state.attachments.map((item) => item.path) }) });
    if (!response.ok) throw new Error((await response.json()).error || "请求失败");
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
    while (true) { const { value, done } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true }); const chunks = buffer.split("\n\n"); buffer = chunks.pop(); for (const chunk of chunks) { const eventName = chunk.match(/^event: (.+)$/m)?.[1]; const dataLine = chunk.match(/^data: (.+)$/m)?.[1]; if (!dataLine) continue; const data = JSON.parse(dataLine); if (eventName === "model_response") setThinking(true); if (eventName === "tool_start") appendTool(data, true); if (eventName === "tool_end") { const nodes = [...$("toolRail").children]; const node = nodes.reverse().find((item) => item.classList.contains("running")); if (node) { node.className = `tool-event ${data.status}`; node.innerHTML = `<span>${data.status === "done" ? "✓" : "×"}  ${escapeHtml(data.label)}</span>${renderDiff(data.diff) || ""}`; } } if (eventName === "answer") startAnswerTyping(data.answer); if (eventName === "complete") { if (state.answerTyping && state.answerTyping.index < Array.from(state.answerTyping.text).length) state.pendingComplete = data; else { finishComplete(data); await loadSessions(); } } } }
  } catch (error) { stopAnswerTypingTimer(); state.answerTyping = null; state.pendingComplete = null; setThinking(false); state.sending = false; renderMessages([...state.messages, { role: "assistant", content: `请求失败：${error.message}` }]); } finally { if (!state.answerTyping && !state.pendingComplete) { state.sending = false; $("send").disabled = false; $("attachments").disabled = false; prompt.focus(); } }
}
const composer = $("composer");
composer.addEventListener("submit", sendTask); $("newChat").addEventListener("click", newChat); $("refresh").addEventListener("click", loadSessions); $("attachments").addEventListener("change", handleAttachments); composer.addEventListener("dragover", (event) => { if (Array.from(event.dataTransfer?.types || []).includes("Files")) { event.preventDefault(); composer.classList.add("dragging-files"); } }); composer.addEventListener("dragleave", (event) => { if (!composer.contains(event.relatedTarget)) composer.classList.remove("dragging-files"); }); composer.addEventListener("drop", (event) => { event.preventDefault(); composer.classList.remove("dragging-files"); if (event.dataTransfer?.files) uploadFiles([...event.dataTransfer.files]); }); prompt.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); composer.requestSubmit(); } }); prompt.addEventListener("input", () => { prompt.style.height = "auto"; prompt.style.height = `${Math.min(prompt.scrollHeight, 180)}px`; });
loadSessions();
