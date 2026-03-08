const askForm = document.getElementById("ask-form");
const askInput = document.getElementById("ask-input");
const answerCard = document.getElementById("answer-card");
const searchForm = document.getElementById("search-form");
const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
const recentList = document.getElementById("recent-list");
const syncButton = document.getElementById("sync-button");
const recentButton = document.getElementById("recent-button");
const syncStatus = document.getElementById("sync-status");

askForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = askInput.value.trim();
  if (!question) return;

  setAnswer("正在根据本地 Notion 索引生成回答...");
  const response = await fetchJson(`/api/ask?q=${encodeURIComponent(question)}`);
  if (response.error) {
    setAnswer(response.error);
    return;
  }

  answerCard.classList.remove("empty");
  answerCard.textContent = response.answer;
  renderSearchResults(response.evidence || []);
});

searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = searchInput.value.trim();
  if (!query) return;
  const results = await fetchJson(`/api/search?q=${encodeURIComponent(query)}`);
  renderSearchResults(results);
});

syncButton.addEventListener("click", async () => {
  syncStatus.textContent = "状态：正在同步 Notion...";
  const response = await fetchJson("/api/sync", { method: "POST" });
  syncStatus.textContent = `状态：${response.message || response.error || "同步完成"}`;
  await loadRecent();
});

recentButton.addEventListener("click", async () => {
  await loadRecent();
});

function renderSearchResults(results) {
  if (!results || results.length === 0) {
    searchResults.innerHTML = `<div class="result-card"><p class="snippet">没有命中本地结果。</p></div>`;
    return;
  }

  searchResults.innerHTML = results
    .map(
      (result) => `
        <article class="result-card">
          <h3>${escapeHtml(result.title || "Untitled")}</h3>
          <p class="meta">${escapeHtml(result.heading || "正文")}</p>
          <p class="snippet">${escapeHtml(result.content || "")}</p>
          <a class="source-link" href="${escapeAttribute(result.url || "#")}" target="_blank" rel="noreferrer">打开来源</a>
        </article>
      `
    )
    .join("");
}

async function loadRecent() {
  recentList.innerHTML = `<div class="recent-card"><p class="snippet">正在加载最近页面...</p></div>`;
  const pages = await fetchJson("/api/recent");
  if (!pages || pages.length === 0) {
    recentList.innerHTML = `<div class="recent-card"><p class="snippet">还没有入库页面。</p></div>`;
    return;
  }

  recentList.innerHTML = pages
    .map(
      (page) => `
        <article class="recent-card">
          <h3>${escapeHtml(page.title || "Untitled")}</h3>
          <p class="meta">${escapeHtml(page.last_edited_time || "")}</p>
          <a class="source-link" href="${escapeAttribute(page.url || "#")}" target="_blank" rel="noreferrer">打开页面</a>
        </article>
      `
    )
    .join("");
}

function setAnswer(text) {
  answerCard.classList.remove("empty");
  answerCard.textContent = text;
}

async function fetchJson(url, options = {}) {
  try {
    const response = await fetch(url, options);
    return await response.json();
  } catch (error) {
    return { error: `请求失败: ${error.message}` };
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}

loadRecent();
