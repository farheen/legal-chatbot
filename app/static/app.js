"use strict";

const $ = (id) => document.getElementById(id);
let turns = [];      // [{role, content}] plain-text turns sent back for follow-up questions
let currentSources = [];

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(path, options = {}) {
  const res = await fetch(path, { credentials: "same-origin", headers: { "Content-Type": "application/json" }, ...options });
  if (res.status === 401) { showLogin(); throw new Error("Not signed in"); }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

// --- auth ----------------------------------------------------------------------------------------
function showLogin() { $("app-view").hidden = true; $("login-view").hidden = false; }
async function showApp() {
  $("login-view").hidden = true; $("app-view").hidden = false;
  const f = await api("/api/filters");
  $("f-jurisdictions").innerHTML = f.jurisdictions
    .map((j) => `<option value="${escapeHtml(j.name)}">${escapeHtml(j.name)} (${j.count.toLocaleString()})</option>`).join("");
  $("coverage").textContent = f.date_min ? `Collection covers ${f.date_min.slice(0, 4)}–${f.date_max.slice(0, 4)}.` : "";
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  $("login-error").textContent = "";
  try {
    await api("/api/login", { method: "POST", body: JSON.stringify({ username: form.get("username"), password: form.get("password") }) });
    e.target.reset();
    await showApp();
  } catch (err) { $("login-error").textContent = err.message; }
});
$("logout").addEventListener("click", async () => { await api("/api/logout", { method: "POST" }); newThread(); showLogin(); });

// --- rendering -----------------------------------------------------------------------------------
function renderAnswer(text, sourceCount) {
  // Escape first, then apply a small safe subset of markdown and turn [P#] markers into chips.
  let html = escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\[(P\d+(?:\s*,\s*P?\d+)*)\]/g, (_, group) => group.split(/\s*,\s*/).map((t) => {
      const n = parseInt(t.replace("P", ""), 10);
      const bad = n < 1 || n > sourceCount ? " bad" : "";
      return `<span class="marker${bad}" data-n="${n}">P${n}</span>`;
    }).join(""));
  return html.split(/\n{2,}/).map((block) => {
    const lines = block.split("\n");
    if (lines.every((l) => /^\s*[-*•]\s+/.test(l))) {
      return `<ul>${lines.map((l) => `<li>${l.replace(/^\s*[-*•]\s+/, "")}</li>`).join("")}</ul>`;
    }
    if (/^#{1,4}\s/.test(block)) return `<p><strong>${block.replace(/^#{1,4}\s/, "")}</strong></p>`;
    return `<p>${block.replace(/\n/g, "<br>")}</p>`;
  }).join("");
}

function renderSources(sources, used = null) {
  currentSources = sources;
  $("sources").innerHTML = sources.length ? sources.map((s, i) => `
    <li id="src-${i + 1}" class="${used && !used.includes(i + 1) ? "unused" : ""}">
      <div class="src-head">P${i + 1}. ${escapeHtml(s.case_name)}</div>
      <div class="src-meta">${escapeHtml([s.citation, s.court, s.decision_date].filter(Boolean).join(" · "))}
        ${s.opinion_type && s.opinion_type !== "majority" ? ` · <strong>${escapeHtml(s.opinion_type)}</strong>` : ""}</div>
      <div class="src-text">${escapeHtml(s.text)}</div>
      <div class="src-actions">
        <button class="link" data-expand="${i}">Expand</button>
        <button class="link" data-case="${s.case_id}">Open full opinion</button>
      </div>
    </li>`).join("") : "<li>No matching passages.</li>";
}

function renderVerification(v) {
  const problems = [];
  const unverified = v.citations.filter((c) => c.status === "unverified");
  if (unverified.length) problems.push(`Citations not found in the database or sources (possible errors): ${unverified.map((c) => escapeHtml(c.cite)).join(", ")}`);
  if (v.invalid_markers.length) problems.push(`References to sources that do not exist: ${v.invalid_markers.join(", ")}`);
  if (v.unmatched_quotes.length) problems.push(`Quotations not found verbatim in the sources: ${v.unmatched_quotes.map((q) => `“${escapeHtml(q.slice(0, 80))}${q.length > 80 ? "…" : ""}”`).join("; ")}`);
  if (v.uncited_paragraphs) problems.push(`${v.uncited_paragraphs} longer paragraph(s) cite no source.`);
  const verified = v.citations.filter((c) => c.status === "verified").length;
  if (!problems.length) {
    return `<div class="check ok">Checked: ${verified} case citation(s) found in the database; every quotation appears in the sources.</div>`;
  }
  return `<div class="check warn"><strong>Check before relying on this answer:</strong><ul>${problems.map((p) => `<li>${p}</li>`).join("")}</ul></div>`;
}

// --- asking --------------------------------------------------------------------------------------
function filters() {
  return {
    jurisdictions: [...$("f-jurisdictions").selectedOptions].map((o) => o.value),
    court: $("f-court").value.trim() || null,
    date_from: $("f-from").value.trim() || null,
    date_to: $("f-to").value.trim() || null,
  };
}

function newThread() { turns = []; $("thread").innerHTML = ""; renderSources([]); }
$("new-chat").addEventListener("click", newThread);

$("question").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("ask-form").requestSubmit();
});

$("ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = $("question").value.trim();
  if (!question) return;
  $("question").value = "";
  $("ask-button").disabled = true;

  const userEl = document.createElement("div");
  userEl.className = "msg user"; userEl.textContent = question;
  const botEl = document.createElement("div");
  botEl.className = "msg assistant";
  botEl.innerHTML = `<div class="body"><span class="status">Searching the case law…</span></div><div class="verify"></div>`;
  $("thread").append(userEl, botEl);
  botEl.scrollIntoView({ behavior: "smooth" });

  let text = "";
  let sources = [];
  try {
    const res = await fetch("/api/ask", {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, filters: filters(), history: turns }),
    });
    if (res.status === 401) { showLogin(); return; }
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail?.[0]?.msg || res.statusText);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const raw = buffer.slice(0, idx); buffer = buffer.slice(idx + 2);
        const event = raw.match(/^event: (.*)$/m)?.[1];
        const data = JSON.parse(raw.match(/^data: (.*)$/m)?.[1] ?? "null");
        if (event === "sources") {
          sources = data; renderSources(sources);
          botEl.querySelector(".body").innerHTML = `<span class="status">Reading ${sources.length} passages…</span>`;
        } else if (event === "delta") {
          text += data;
          botEl.querySelector(".body").innerHTML = renderAnswer(text, sources.length);
        } else if (event === "verification") {
          botEl.querySelector(".verify").innerHTML = renderVerification(data);
          renderSources(sources, data.used_passages);
        } else if (event === "error") {
          botEl.querySelector(".verify").innerHTML = `<div class="check warn">${escapeHtml(data)}</div>`;
        }
      }
    }
    if (text) turns.push({ role: "user", content: question }, { role: "assistant", content: text });
  } catch (err) {
    botEl.querySelector(".verify").innerHTML = `<div class="check warn">${escapeHtml(err.message)}</div>`;
  } finally {
    $("ask-button").disabled = false;
  }
});

// --- sources & case viewer ------------------------------------------------------------------------
document.addEventListener("click", async (e) => {
  const marker = e.target.closest(".marker");
  if (marker) {
    const el = $(`src-${marker.dataset.n}`);
    if (!el) return;
    document.querySelectorAll("#sources li").forEach((li) => li.classList.remove("highlight"));
    el.classList.add("highlight");
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  const expand = e.target.closest("[data-expand]");
  if (expand) {
    const t = expand.closest("li").querySelector(".src-text");
    t.classList.toggle("open");
    expand.textContent = t.classList.contains("open") ? "Collapse" : "Expand";
    return;
  }
  const open = e.target.closest("[data-case]");
  if (open) openCase(open.dataset.case);
});

async function openCase(id) {
  $("case-body").innerHTML = "<p>Loading…</p>";
  $("case-dialog").showModal();
  const d = await api(`/api/cases/${encodeURIComponent(id)}`);
  const c = d.case, t = d.treatment;
  const neg = t.negative_signals.map((s) =>
    `<li class="neg"><strong>${escapeHtml(s.name_abbreviation)}</strong> (${escapeHtml(s.citation)}, ${escapeHtml((s.decision_date || "").slice(0, 4))}) — “${escapeHtml(s.term)}”: ${escapeHtml(s.snippet)}</li>`).join("");
  $("case-body").innerHTML = `
    <h1>${escapeHtml(c.name_abbreviation || c.name)}</h1>
    <p class="src-meta">${escapeHtml(d.citations.join("; "))} · ${escapeHtml(c.court)} · ${escapeHtml(c.decision_date)}${c.docket_number ? " · " + escapeHtml(c.docket_number) : ""}</p>
    <div class="treatment">
      Cited by <strong>${t.citing_count}</strong> later case(s) in this database${t.scanned < t.citing_count ? ` (newest ${t.scanned} scanned for negative treatment)` : ""}.
      ${neg ? `<p><strong>Possible negative treatment — check:</strong></p><ul>${neg}</ul>` : ""}
      <p class="hint">${escapeHtml(t.note)}</p>
    </div>
    ${d.opinions.map((o) => `<h2>${escapeHtml(o.type || "opinion")}${o.author ? " — " + escapeHtml(o.author) : ""}</h2><div class="opinion">${escapeHtml(o.text)}</div>`).join("")}`;
}

// --- start -----------------------------------------------------------------------------------------
api("/api/me").then(showApp).catch(() => showLogin());
