/* ======================================
   thesis-backtester showcase app
   ====================================== */

(function () {
  "use strict";

  // ---- State ----
  let operatorsData = null;
  let strategiesData = null;
  let activeCategory = "all";
  let searchQuery = "";

  // ---- Category display names ----
  const CATEGORY_NAMES = {
    screening: "筛选",
    fundamental: "基本面",
    valuation: "估值",
    decision: "决策",
    forward_risk: "前瞻风险",
    special: "特殊模型",
    bank: "银行",
    consumer: "消费",
    manufacturing: "制造",
    tech: "科技",
  };

  // ---- Init ----
  document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    loadData();
  });

  // ---- Tab switching ----
  function initTabs() {
    const btns = document.querySelectorAll(".tab-btn");
    btns.forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.tab;
        btns.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        document.querySelectorAll(".tab-panel").forEach((p) => {
          p.classList.toggle("active", p.id === target);
        });
      });
    });
  }

  // ---- Load JSON data ----
  function loadData() {
    const base = getBasePath();
    Promise.all([
      fetch(base + "data/operators.json").then((r) => r.json()),
      fetch(base + "data/strategies.json").then((r) => r.json()),
    ])
      .then(([ops, strats]) => {
        operatorsData = ops;
        strategiesData = strats;
        renderOperators();
        renderStrategies();
      })
      .catch((err) => {
        console.error("Failed to load data:", err);
        document.getElementById("tab-operators").innerHTML =
          '<p style="padding:2rem;color:#ef4444;">Failed to load data. Make sure to run <code>python docs/site/build.py</code> first.</p>';
      });
  }

  function getBasePath() {
    // Support both local file:// and deployed contexts
    const path = window.location.pathname;
    if (path.endsWith("index.html")) {
      return path.replace("index.html", "");
    }
    return path.endsWith("/") ? path : path + "/";
  }

  // ---- Render Operators Tab ----
  function renderOperators() {
    const container = document.getElementById("tab-operators");
    if (!operatorsData) return;

    const categories = Object.keys(operatorsData.categories).sort();

    // Build toolbar
    let html = '<div class="toolbar">';
    html += '<input type="text" class="search-box" id="op-search" placeholder="搜索算子名称或ID...">';
    html += '<div class="filter-btns">';
    html += '<button class="filter-btn active" data-cat="all">全部</button>';
    categories.forEach((cat) => {
      const count = operatorsData.categories[cat].length;
      const label = CATEGORY_NAMES[cat] || cat;
      html += `<button class="filter-btn" data-cat="${cat}">${label} (${count})</button>`;
    });
    html += "</div>";
    html += `<span class="count-badge" id="op-count">共 ${operatorsData.total} 个算子</span>`;
    html += "</div>";

    // Card grid placeholder
    html += '<div class="card-grid" id="op-grid"></div>';
    container.innerHTML = html;

    // Bind events
    document.getElementById("op-search").addEventListener("input", (e) => {
      searchQuery = e.target.value.toLowerCase();
      renderCards();
    });

    container.querySelectorAll(".filter-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        container.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        activeCategory = btn.dataset.cat;
        renderCards();
      });
    });

    renderCards();
  }

  function renderCards() {
    const grid = document.getElementById("op-grid");
    if (!grid || !operatorsData) return;

    let ops = [];
    Object.entries(operatorsData.categories).forEach(([cat, items]) => {
      if (activeCategory !== "all" && cat !== activeCategory) return;
      items.forEach((op) => {
        if (searchQuery) {
          const hay = (op.id + " " + op.name + " " + (op.tags || []).join(" ")).toLowerCase();
          if (!hay.includes(searchQuery)) return;
        }
        ops.push(op);
      });
    });

    // Update count
    const countEl = document.getElementById("op-count");
    if (countEl) countEl.textContent = `显示 ${ops.length} / ${operatorsData.total} 个算子`;

    grid.innerHTML = ops.map((op) => buildCardHTML(op)).join("");

    // Bind card expand/collapse
    grid.querySelectorAll(".op-card").forEach((card) => {
      card.addEventListener("click", () => card.classList.toggle("expanded"));
    });
  }

  function buildCardHTML(op) {
    const catClass = "cat-" + (op.dir_category || op.category);
    const catLabel = CATEGORY_NAMES[op.dir_category] || op.dir_category || op.category;

    let html = `<div class="op-card" data-id="${op.id}">`;
    html += '<div class="card-head">';
    html += `<div><div class="op-name">${esc(op.name)}</div><div class="op-id">${esc(op.id)}</div></div>`;
    html += `<span class="category-badge ${catClass}">${esc(catLabel)}</span>`;
    html += '<span class="expand-hint">点击展开 ▼</span>';
    html += "</div>";

    // Tags
    if (op.tags && op.tags.length) {
      html += '<div class="tag-list">';
      op.tags.forEach((t) => (html += `<span class="tag">${esc(t)}</span>`));
      html += "</div>";
    }

    // Gate
    if (op.gate) {
      const gateText = op.gate.only_industry
        ? "仅限: " + op.gate.only_industry.join(", ")
        : JSON.stringify(op.gate);
      html += `<div class="gate-badge">${esc(gateText)}</div>`;
    }

    // Expandable details
    html += '<div class="card-details">';

    if (op.outputs && op.outputs.length) {
      html += '<div class="detail-section"><h4>输出字段</h4>';
      op.outputs.forEach((o) => {
        html += `<div class="output-item"><span class="output-field">${esc(o.field)}</span> <span class="output-type">${esc(o.type)}</span> <span>${esc(o.desc || "")}</span></div>`;
      });
      html += "</div>";
    }

    if (op.data_needed && op.data_needed.length) {
      html += '<div class="detail-section"><h4>所需数据</h4><div class="data-list">';
      op.data_needed.forEach((d) => (html += `<span class="data-item">${esc(d)}</span>`));
      html += "</div></div>";
    }

    html += "</div></div>";
    return html;
  }

  // ---- Render Strategies Tab ----
  function renderStrategies() {
    const container = document.getElementById("tab-strategies");
    if (!strategiesData || !strategiesData.length) {
      container.innerHTML = '<p style="padding:2rem;color:var(--text-muted);">No strategies found.</p>';
      return;
    }

    let html = "";
    strategiesData.forEach((s) => {
      html += '<div class="strategy-section">';

      // Header
      html += '<div class="strategy-header">';
      html += `<span class="strategy-name">${esc(s.display_name)}</span>`;
      html += '<div class="strategy-meta">';
      if (s.version) html += `<span class="meta-tag version">v${esc(s.version)}</span>`;

      const totalOps = s.chapters.reduce((n, ch) => n + ch.operators.length, 0);
      html += `<span class="meta-tag">${s.chapters.length} 章 / ${totalOps} 算子</span>`;

      if (s.buy_threshold != null)
        html += `<span class="meta-tag buy">买入 &ge; ${s.buy_threshold}</span>`;
      if (s.avoid_threshold != null)
        html += `<span class="meta-tag avoid">回避 &le; ${s.avoid_threshold}</span>`;
      if (s.backtest)
        html += `<span class="meta-tag">${esc(s.backtest.start_date)} ~ ${esc(s.backtest.end_date)}</span>`;
      html += "</div></div>";

      // Chapter timeline
      html += '<div class="chapter-timeline">';
      s.chapters.forEach((ch) => {
        html += '<div class="ch-item">';
        html += '<div class="ch-line">';
        html += `<div class="ch-dot">${ch.chapter}</div>`;
        html += '<div class="ch-connector"></div>';
        html += "</div>";
        html += '<div class="ch-content">';
        html += `<div class="ch-title">${esc(ch.title)} <span class="ch-op-count">(${ch.operators.length} 算子)</span></div>`;
        if (ch.dependencies.length) {
          html += `<div class="ch-deps">依赖: ${ch.dependencies.map(esc).join(", ")}</div>`;
        }
        html += '<div class="ch-ops">';
        ch.operators.forEach((op) => {
          html += `<span class="ch-op-tag">${esc(op)}</span>`;
        });
        html += "</div></div></div>";
      });
      html += "</div></div>";
    });

    container.innerHTML = html;

    // Bind chapter expand
    container.querySelectorAll(".ch-title").forEach((title) => {
      title.addEventListener("click", () => {
        title.closest(".ch-item").classList.toggle("expanded");
      });
    });
  }

  // ---- Utility ----
  function esc(str) {
    if (str == null) return "";
    const d = document.createElement("div");
    d.textContent = String(str);
    return d.innerHTML;
  }
})();
