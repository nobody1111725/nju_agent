const state = { sessionId: null, sending: false, messages: [] };
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
  messages.innerHTML = items.length ? items.map((item) => `<article class="message ${item.role}"><div class="avatar ${item.role}">${item.role === "user" ? "你" : "N"}</div><div class="message-body">${item.role === "assistant" ? markdownToHtml(item.content) : escapeHtml(item.content)}</div></article>`).join("") : `<div class="empty-state"><div class="empty-mark">N</div><h1>开始编程工作</h1><p>描述要修改、检查或运行的代码任务。</p></div>`;
  messages.scrollTop = messages.scrollHeight;
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
async function loadSessions() {
  const response = await fetch("/api/sessions");
  const data = await response.json();
  const list = $("sessions");
  list.innerHTML = (data.sessions || []).map((item) => `<button class="session-item ${item.id === state.sessionId ? "active" : ""}" data-id="${item.id}">${escapeHtml(item.messages.find((m) => m.role === "user")?.content || "新会话")}<small>${escapeHtml(item.short_id)}</small></button>`).join("");
  list.querySelectorAll(".session-item").forEach((button) => button.addEventListener("click", () => openSession(button.dataset.id)));
}
async function openSession(id) {
  const response = await fetch(`/api/sessions/${encodeURIComponent(id)}`);
  if (!response.ok) return;
  const data = await response.json(); state.sessionId = data.id; state.messages = Array.isArray(data.messages) ? data.messages : []; $("sessionTitle").textContent = state.messages.find((m) => m.role === "user")?.content || "已恢复会话"; renderMessages(state.messages); await loadSessions();
}
function newChat() { state.sessionId = null; state.messages = []; $("sessionTitle").textContent = "新对话"; renderMessages(state.messages); $("toolRail").innerHTML = ""; loadSessions(); prompt.focus(); }
function appendTool(data, running) { const rail = $("toolRail"); const id = `${data.name}-${rail.children.length}`; const node = document.createElement("div"); node.className = `tool-event ${running ? "running" : data.status}`; node.dataset.toolId = id; node.textContent = `${running ? "◌" : data.status === "done" ? "✓" : "×"}  ${data.label}`; rail.appendChild(node); messages.scrollTop = messages.scrollHeight; return id; }
async function sendTask(event) {
  event.preventDefault(); if (state.sending || !prompt.value.trim()) return;
  const task = prompt.value.trim(); prompt.value = ""; state.sending = true; $("send").disabled = true; $("toolRail").innerHTML = "";
  const previousMessages = state.messages.slice();
  state.messages = [...previousMessages, { role: "user", content: task }];
  renderMessages(state.messages);
  try {
    const response = await fetch("/api/chat/stream", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: state.sessionId, task }) });
    if (!response.ok) throw new Error((await response.json()).error || "请求失败");
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
    while (true) { const { value, done } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true }); const chunks = buffer.split("\n\n"); buffer = chunks.pop(); for (const chunk of chunks) { const eventName = chunk.match(/^event: (.+)$/m)?.[1]; const dataLine = chunk.match(/^data: (.+)$/m)?.[1]; if (!dataLine) continue; const data = JSON.parse(dataLine); if (eventName === "model_response") setThinking(true); if (eventName === "tool_start") appendTool(data, true); if (eventName === "tool_end") { const nodes = [...$("toolRail").children]; const node = nodes.reverse().find((item) => item.textContent.includes(data.label)); if (node) { node.className = `tool-event ${data.status}`; node.textContent = `${data.status === "done" ? "✓" : "×"}  ${data.label}`; } } if (eventName === "complete") { setThinking(false); if (data.id) { state.sessionId = data.id; } if (Array.isArray(data.messages)) { state.messages = data.messages; $("sessionTitle").textContent = state.messages.find((m) => m.role === "user")?.content || "已保存会话"; } if (data.error) { renderMessages(state.messages); await loadSessions(); throw new Error(data.error); } renderMessages(state.messages); await loadSessions(); } } }
  } catch (error) { setThinking(false); renderMessages([...state.messages, { role: "assistant", content: `请求失败：${error.message}` }]); } finally { state.sending = false; $("send").disabled = false; prompt.focus(); }
}
$("composer").addEventListener("submit", sendTask); $("newChat").addEventListener("click", newChat); $("refresh").addEventListener("click", loadSessions); prompt.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); $("composer").requestSubmit(); } }); prompt.addEventListener("input", () => { prompt.style.height = "auto"; prompt.style.height = `${Math.min(prompt.scrollHeight, 180)}px`; });
loadSessions();
