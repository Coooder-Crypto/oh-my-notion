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
const overviewMetrics = document.getElementById("overview-metrics");
const insightList = document.getElementById("insight-list");
const pageKindBars = document.getElementById("page-kind-bars");
const sourceTypeBars = document.getElementById("source-type-bars");
const activityBars = document.getElementById("activity-bars");
const keywordCloud = document.getElementById("keyword-cloud");
const domainBars = document.getElementById("domain-bars");
const chunkHeavyPages = document.getElementById("chunk-heavy-pages");
const linkHeavyPages = document.getElementById("link-heavy-pages");

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
  await loadDashboard();
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
          <p class="meta">method=${escapeHtml(result.retrieval_method || "hybrid")} rerank=${formatScore(result.rerank_score)} fts=${formatScore(result.fts_score)} vector=${formatScore(result.vector_score)}</p>
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

async function loadDashboard() {
  const payload = await fetchJson("/api/dashboard");
  if (payload.error) {
    overviewMetrics.innerHTML = metricCard("Error", payload.error);
    return;
  }

  renderOverview(payload.overview || {});
  renderInsights(payload.insights || []);
  renderBarList(pageKindBars, payload.page_kinds || []);
  renderBarList(sourceTypeBars, payload.source_types || []);
  renderBarList(activityBars, payload.recent_activity || []);
  renderKeywordCloud(payload.top_keywords || []);
  renderBarList(domainBars, payload.top_domains || []);
  renderHeavyPages(chunkHeavyPages, payload.top_pages_by_chunks || [], "chunk_count", "chunks");
  renderHeavyPages(linkHeavyPages, payload.top_pages_by_links || [], "link_count", "links");
}

function renderOverview(overview) {
  const metrics = [
    ["Pages", overview.pages],
    ["Chunks", overview.chunks],
    ["Embeddings", overview.embeddings],
    ["Links", overview.links],
    ["Raw Snapshots", overview.raw_snapshots],
    ["Session Turns", overview.session_turns],
  ];
  overviewMetrics.innerHTML = metrics.map(([label, value]) => metricCard(label, value)).join("");
}

function metricCard(label, value) {
  return `
    <article class="metric-card">
      <p class="metric-label">${escapeHtml(label)}</p>
      <p class="metric-value">${escapeHtml(value ?? 0)}</p>
    </article>
  `;
}

function renderInsights(insights) {
  if (!insights.length) {
    insightList.innerHTML = `<p class="snippet">还没有足够数据生成分析结论。</p>`;
    return;
  }
  insightList.innerHTML = insights.map((item) => `<div class="insight-pill">${escapeHtml(item)}</div>`).join("");
}

function renderBarList(container, items) {
  if (!items.length) {
    container.innerHTML = `<p class="snippet">暂无数据。</p>`;
    return;
  }
  const max = Math.max(...items.map((item) => Number(item.value) || 0), 1);
  container.innerHTML = items
    .map(
      (item) => `
        <div class="bar-row">
          <div class="bar-meta">
            <span>${escapeHtml(item.name || "Unknown")}</span>
            <strong>${escapeHtml(item.value || 0)}</strong>
          </div>
          <div class="bar-track">
            <div class="bar-fill" style="width:${Math.max(8, ((Number(item.value) || 0) / max) * 100)}%"></div>
          </div>
        </div>
      `
    )
    .join("");
}

function renderKeywordCloud(items) {
  if (!items.length) {
    keywordCloud.innerHTML = `<p class="snippet">暂无关键词数据。</p>`;
    return;
  }
  const max = Math.max(...items.map((item) => Number(item.value) || 0), 1);
  keywordCloud.innerHTML = items
    .map((item) => {
      const size = 0.9 + ((Number(item.value) || 0) / max) * 1.2;
      return `<span class="token" style="font-size:${size}rem">${escapeHtml(item.name)} <em>${escapeHtml(item.value)}</em></span>`;
    })
    .join("");
}

function renderHeavyPages(container, items, key, unit) {
  if (!items.length) {
    container.innerHTML = `<div class="recent-card"><p class="snippet">暂无数据。</p></div>`;
    return;
  }
  container.innerHTML = items
    .map(
      (item) => `
        <article class="result-card">
          <h3>${escapeHtml(item.title || "Untitled")}</h3>
          <p class="meta">${escapeHtml(item.last_edited_time || "")}</p>
          <p class="snippet">${escapeHtml(String(item[key] || 0))} ${escapeHtml(unit)}${item.child_count !== undefined ? ` · ${escapeHtml(String(item.child_count || 0))} children` : ""}</p>
          <a class="source-link" href="${escapeAttribute(item.url || "#")}" target="_blank" rel="noreferrer">打开页面</a>
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

function formatScore(value) {
  const number = Number(value || 0);
  return number.toFixed(3);
}

loadRecent();
loadDashboard();
