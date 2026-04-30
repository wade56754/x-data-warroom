const state = {
  status: null,
  tweets: [],
  details: {},
  expanded: new Set(),
  topicMedianEr: {},  // topic -> median_er from /api/insights
};

const $ = (selector) => document.querySelector(selector);

const COPY = {
  overview: {
    tracked_tweets: "追踪推文",
    total_samples: "采样次数",
    total_views: "总浏览",
    total_engagement: "总互动",
    views_24h: "24h 浏览增长",
    avg_er: "平均互动率",
  },
  top: {
    score: "综合分最高",
    replies: "回复最多",
    bookmarks: "收藏最多",
  },
  status: {
    rising: "增长中",
    stable: "稳定",
    needs_reply: "有回复",
    high_bookmark: "收藏高",
    cold: "偏冷",
  },
};

document.addEventListener("DOMContentLoaded", () => {
  $("#sort").addEventListener("change", loadDashboard);
  $("#order").addEventListener("change", loadDashboard);
  $("#limit").addEventListener("change", loadDashboard);
  $("#status-filter").addEventListener("change", renderTweets);
  $("#search").addEventListener("input", renderTweets);
  $("#refresh").addEventListener("click", loadDashboard);

  // hash routing
  applyRoute();
  window.addEventListener("hashchange", applyRoute);

  loadDashboard();
});

async function loadDashboard() {
  setError("");
  $("#refresh").disabled = true;
  $("#refresh").textContent = "刷新中";
  try {
    const sort = encodeURIComponent($("#sort").value);
    const order = encodeURIComponent($("#order").value);
    const limit = encodeURIComponent($("#limit").value);
    const [status, tweetResponse, insightsResponse] = await Promise.all([
      fetchJson("/api/status"),
      fetchJson(`/api/tweets?limit=${limit}&sort=${sort}&order=${order}`),
      fetchJson("/api/insights").catch(() => null),
    ]);
    state.status = status;
    state.tweets = tweetResponse.tweets || [];

    // build topic -> median_er lookup from insights
    const breakdown = (insightsResponse && insightsResponse.weekly_summary && insightsResponse.weekly_summary.topic_breakdown) || [];
    state.topicMedianEr = {};
    breakdown.forEach((t) => {
      if (t.topic && t.median_er != null) state.topicMedianEr[t.topic] = t.median_er;
    });

    renderStatus();
    renderTweets();
  } catch (error) {
    setError(error.message || String(error));
  } finally {
    $("#refresh").disabled = false;
    $("#refresh").textContent = "刷新";
  }
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `请求失败：${response.status}`);
  }
  return data;
}

function renderStatus() {
  const status = state.status;
  if (!status) return;

  $("#subtitle").textContent = `最近采样 ${formatDateTime(status.latest_sample_ts)} · 共 ${formatNumber(status.total_samples)} 次采样`;
  const stale = (status.warnings || []).length > 0;
  $("#freshness").className = stale ? "badge badge-warn" : "badge badge-ok";
  $("#freshness").textContent = stale ? "需要关注" : "数据新鲜";

  const totals = status.totals || {};
  const growth = status.growth || {};
  const totalEngagement =
    status.total_engagement ??
    ["likes", "replies", "bookmarks", "retweets"].reduce((sum, key) => sum + Number(totals[key] || 0), 0);

  // delta helper: returns {text, cls} for a 24h delta value
  function deltaTag(raw) {
    const n = Number(raw || 0);
    if (n > 0) return { text: `↑ +${formatNumber(n)} (24h)`, cls: "up" };
    if (n < 0) return { text: `↓ ${formatNumber(n)} (24h)`, cls: "down" };
    return { text: `— (24h)`, cls: "" };
  }

  const hs = status.hourly_series || {};
  const viewsSpark = (hs.views && hs.views.length >= 2) ? sparkline_mini(hs.views, 100, 28) : "";
  const engSpark = (hs.engagement && hs.engagement.length >= 2) ? sparkline_mini(hs.engagement, 100, 28) : "";

  const cards = [
    { label: COPY.overview.tracked_tweets, value: formatNumber(status.tracked_tweets), hint: "当前被采集的推文数", delta: null, spark: "" },
    { label: COPY.overview.total_samples, value: formatNumber(status.total_samples), hint: "历史采样点总数", delta: null, spark: "" },
    { label: COPY.overview.total_views, value: formatNumber(totals.views), hint: "当前累计浏览", delta: deltaTag(growth.views_24h), spark: viewsSpark },
    { label: COPY.overview.total_engagement, value: formatNumber(totalEngagement), hint: "赞 / 回复 / 收藏 / 转发", delta: deltaTag((growth.likes_24h || 0) + (growth.replies_24h || 0) + (growth.bookmarks_24h || 0) + (growth.retweets_24h || 0)), spark: engSpark },
    { label: COPY.overview.views_24h, value: signedNumber(growth.views_24h), hint: "最近 24 小时曝光变化", delta: null, spark: "" },
    { label: COPY.overview.avg_er, value: formatPercent(status.avg_er), hint: "平均互动率", delta: null, spark: "" },
  ];
  $("#overview").innerHTML = cards
    .map(({ label, value, hint, delta, spark }) => {
      const deltaHtml = delta
        ? `<span class="stat-card-delta ${delta.cls}">${delta.text}</span>`
        : "";
      const sparkHtml = spark ? `<span class="stat-card-spark">${spark}</span>` : "";
      return `
        <article class="stat-card">
          <span>${label}</span>
          <strong>${value}</strong>
          ${deltaHtml}
          <em>${hint}</em>
          ${sparkHtml}
        </article>
      `;
    })
    .join("");

  renderHealth(status);
  renderTopPerformers(status.top || {});
}

function renderHealth(status) {
  const collector = status.collector || {};
  const ok = collector.ok === true;
  $("#collector-state").className = ok ? "badge badge-ok" : "badge badge-warn";
  $("#collector-state").textContent = ok ? "正常" : "检查";
  const warnings = status.warnings || [];
  $("#health").innerHTML = `
    <dl class="health-list">
      <div><dt>最近运行</dt><dd>${escapeHtml(formatDateTime(collector.last_run_at))}</dd></div>
      <div><dt>最新采样</dt><dd>${escapeHtml(formatDateTime(status.latest_sample_ts))}</dd></div>
      <div><dt>日志路径</dt><dd class="path">${escapeHtml(collector.log_file || "-")}</dd></div>
    </dl>
    ${warnings.length ? `<ul class="warnings">${warnings.map((item) => `<li>${escapeHtml(translateWarning(item))}</li>`).join("")}</ul>` : `<p class="quiet-note">采集器状态正常，当前只读取本地数据文件。</p>`}
  `;
}

function renderTopPerformers(top) {
  const groups = [
    [COPY.top.score, top.by_score || []],
    [COPY.top.replies, top.by_replies || []],
    [COPY.top.bookmarks, top.by_bookmarks || []],
  ];
  $("#top-performers").innerHTML = groups
    .map(
      ([title, items]) => `
        <section class="top-list">
          <h3>${title}</h3>
          ${items.length ? items.map(renderTopItem).join("") : `<p class="empty">暂无数据</p>`}
        </section>
      `,
    )
    .join("");
}

function renderTopItem(item) {
  return `
    <a class="top-item" href="${escapeAttr(item.url)}" target="_blank" rel="noreferrer" title="${escapeAttr(item.text || "")}">
      <span>${escapeHtml(truncate(item.text, 52))}</span>
      <strong>${formatNumber(item.value)}</strong>
    </a>
  `;
}

function velocityClass(v) {
  if (v == null) return 'velocity-na';
  if (v >= 5000) return 'velocity-hot';   // 在飞 / 算法在推
  if (v >= 500)  return 'velocity-warm';  // 稳定爬升
  if (v >= 50)   return 'velocity-normal'; // 慢热中
  return 'velocity-cold';                  // 已沉淀 / 没起来
}

function viralClass(s) {
  if (s == null) return 'viral-na';
  if (s >= 80) return 'viral-hot';
  if (s >= 60) return 'viral-warm';
  if (s >= 30) return 'viral-normal';
  if (s >= 10) return 'viral-cold';
  return 'viral-na';
}

// Compute needs_reply priority: 2=hot(red), 1=warm(amber), 0=cold(grey)
function needsReplyPriority(tweet) {
  if (tweet.status_label !== "needs_reply") return null;
  const replies = (tweet.metrics || {}).replies || 0;
  const deltaReplies = (tweet.deltas || {}).replies || 0;
  if (replies >= 5 || deltaReplies > 0) return 2;
  const topic = tweet.topic || "";
  const medianEr = state.topicMedianEr[topic] ?? 0;
  if (replies >= 1 && tweet.er > medianEr) return 1;
  return 0;
}

function renderTweets() {
  const body = $("#tweets-body");
  const query = ($("#search").value || "").trim().toLowerCase();
  const statusFilter = $("#status-filter").value;
  let tweets = state.tweets.filter((tweet) => {
    const matchesText = !query || (tweet.text || "").toLowerCase().includes(query) || tweet.tweet_id.includes(query);
    const matchesStatus = statusFilter === "all" || tweet.status_label === statusFilter;
    return matchesText && matchesStatus;
  });

  // 仅注 priority（用于行视觉竖条颜色），不做 sort 干预 —— 完全跟随 API 顺序（用户的 sort 选择）
  tweets = tweets.map((tweet) => ({ ...tweet, _priority: needsReplyPriority(tweet) }));

  if (!tweets.length) {
    body.innerHTML = `<tr><td colspan="15" class="empty-row">没有匹配推文</td></tr>`;
    return;
  }

  body.innerHTML = tweets.map(renderTweetRows).join("");
  body.querySelectorAll("[data-toggle]").forEach((button) => {
    button.addEventListener("click", () => toggleDetails(button.dataset.toggle));
  });
}

function renderTweetRows(tweet) {
  const metrics = tweet.metrics || {};
  const deltas = tweet.deltas || {};
  const deltaEngagement = ["likes", "replies", "bookmarks", "retweets"].reduce((sum, key) => sum + Number(deltas[key] || 0), 0);
  const expanded = state.expanded.has(tweet.tweet_id);
  const priority = tweet._priority;

  // build status badge: needs_reply gets data-priority attr + label override
  let statusHtml;
  if (tweet.status_label === "needs_reply" && priority != null) {
    const label = priority === 0 ? "已沉淀" : statusLabel(tweet.status_label);
    statusHtml = `<span class="status status-needs_reply" data-priority="${priority}">${label}</span>`;
  } else {
    statusHtml = `<span class="status status-${escapeAttr(tweet.status_label)}">${statusLabel(tweet.status_label)}</span>`;
  }

  const historyViews = (tweet.history || []).map((h) => Number((h.metrics || {}).views) || 0);
  const miniSpark = historyViews.length >= 2
    ? sparkline_mini(historyViews, 40, 16)
    : (expanded ? "−" : "+");
  return `
    <tr class="${expanded ? "is-expanded" : ""}">
      <td class="row-spark"><button class="spark-toggle" type="button" data-toggle="${escapeAttr(tweet.tweet_id)}" title="${expanded ? "收起趋势" : "展开趋势"}" aria-label="展开/收起">${miniSpark}</button></td>
      <td class="tweet-text" title="${escapeAttr(tweet.text || "")}">${escapeHtml(truncate(tweet.text || "", 96))}</td>
      <td>${escapeHtml(formatDateTime(tweet.created_at))}<small>${formatAge(tweet.age_hours)}</small></td>
      <td>${formatNumber(metrics.views)}</td>
      <td>${formatNumber(metrics.likes)}</td>
      <td>${formatNumber(metrics.replies)}</td>
      <td>${formatNumber(metrics.bookmarks)}</td>
      <td>${formatNumber(metrics.retweets)}</td>
      <td><span class="delta">${signedNumber(deltas.views)}</span><small>${signedNumber(deltaEngagement)} 互动</small></td>
      <td class="velocity ${velocityClass(tweet.velocity)}">${tweet.velocity != null ? (tweet.velocity >= 1000 ? `${(tweet.velocity / 1000).toFixed(1)}k/h` : `${Math.round(tweet.velocity)}/h`) : '—'}</td>
      <td class="viral-score ${viralClass(tweet.viral_score)}">${tweet.viral_score != null ? tweet.viral_score : '—'}</td>
      <td>${formatPercent(tweet.er)}</td>
      <td>${formatNumber(tweet.weighted_score)}</td>
      <td>${statusHtml}</td>
      <td><a class="open-link" href="${escapeAttr(tweet.url)}" target="_blank" rel="noreferrer">打开</a></td>
    </tr>
    <tr class="detail-row ${expanded ? "" : "is-hidden"}">
      <td colspan="15">${renderDetail(tweet.tweet_id)}</td>
    </tr>
  `;
}

function renderDetail(tweetId) {
  const detail = state.details[tweetId];
  if (!detail) {
    return `<div class="detail-panel">加载趋势中...</div>`;
  }
  if (detail.error) {
    return `<div class="detail-panel error-inline">${escapeHtml(detail.error)}</div>`;
  }
  const history = detail.history || [];
  return `
    <div class="detail-panel">
      <div class="spark-grid">
        <div>
          <span>浏览趋势</span>
          ${sparkline(history, "views")}
        </div>
        <div>
          <span>互动趋势</span>
          ${sparkline(history, "engagement")}
        </div>
      </div>
      <div class="history-meta">
        <span>${history.length} 次采样</span>
        <span>最近采样 ${escapeHtml(formatDateTime(detail.sampled_at))}</span>
        <span>浏览增量 ${signedNumber((detail.deltas || {}).views)}</span>
      </div>
    </div>
  `;
}

async function toggleDetails(tweetId) {
  if (state.expanded.has(tweetId)) {
    state.expanded.delete(tweetId);
    renderTweets();
    return;
  }
  state.expanded.add(tweetId);
  renderTweets();
  if (!state.details[tweetId]) {
    try {
      const response = await fetchJson(`/api/tweet/${encodeURIComponent(tweetId)}`);
      state.details[tweetId] = response.tweet;
    } catch (error) {
      state.details[tweetId] = { error: error.message || String(error) };
    }
    renderTweets();
  }
}

function sparkline(history, metric) {
  const values = (history || []).map((sample) => {
    const metrics = sample.metrics || {};
    return Number(metric === "engagement" ? metrics.engagement : metrics[metric]) || 0;
  });
  if (!values.length) return `<div class="sparkline empty">暂无采样</div>`;
  const width = 240;
  const height = 56;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(1, max - min);
  const points = values
    .map((value, index) => {
      const x = values.length === 1 ? width / 2 : (index / (values.length - 1)) * width;
      const y = height - 4 - ((value - min) / range) * (height - 8);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const last = values[values.length - 1];
  const lastPoint = points.split(" ").pop().split(",");
  const aria = metric === "engagement" ? "互动趋势" : "浏览趋势";
  return `
    <svg class="sparkline" viewBox="0 0 ${width} ${height}" role="img" aria-label="${aria}">
      <polyline points="${points}" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
      <circle cx="${lastPoint[0]}" cy="${lastPoint[1]}" r="3.5" fill="currentColor"></circle>
    </svg>
    <strong>${formatNumber(last)}</strong>
  `;
}

function sparkline_mini(values, width, height) {
  const w = width || 40;
  const h = height || 16;
  const vals = (values || []).map((v) => Number(v) || 0);
  if (vals.length < 2) return "";
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const range = Math.max(1, max - min);
  const points = vals
    .map((v, i) => {
      const x = (i / (vals.length - 1)) * w;
      const y = h - 2 - ((v - min) / range) * (h - 4);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const last = points.split(" ").pop().split(",");
  return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><polyline points="${points}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></polyline><circle cx="${last[0]}" cy="${last[1]}" r="2" fill="currentColor"></circle></svg>`;
}

function setError(message) {
  const element = $("#error");
  if (!message) {
    element.classList.add("is-hidden");
    element.textContent = "";
    return;
  }
  element.classList.remove("is-hidden");
  element.textContent = message;
}

function statusLabel(value) {
  return COPY.status[value] || value || "-";
}

function translateWarning(value) {
  const text = String(value || "");
  const staleMatch = text.match(/^latest sample is (\d+) minutes old$/i);
  if (staleMatch) return `最新采样已过去 ${formatNumber(staleMatch[1])} 分钟`;
  return text;
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return new Intl.NumberFormat("zh-CN").format(Number(value));
}

function signedNumber(value) {
  const number = Number(value || 0);
  if (number > 0) return `+${formatNumber(number)}`;
  return formatNumber(number);
}

function formatPercent(value) {
  if (value === null || value === undefined) return "-";
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatAge(value) {
  if (value === null || value === undefined) return "";
  if (value < 24) return `${Number(value).toFixed(1)} 小时前`;
  return `${(Number(value) / 24).toFixed(1)} 天前`;
}

function truncate(value, length) {
  const text = String(value || "");
  if (text.length <= length) return text;
  return `${text.slice(0, length - 1)}…`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

// === hash 路由 ===
function applyRoute() {
  const hash = window.location.hash.replace("#", "") || "overview";
  const route = hash === "table" ? "table" : "overview";
  document.body.dataset.route = route;

  // update subnav active state
  document.querySelectorAll(".subnav-item").forEach((el) => {
    const target = el.getAttribute("href").replace("#", "");
    el.classList.toggle("active", target === route);
  });
}
