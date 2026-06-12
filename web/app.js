"use strict";

/* ------------------------------------------------------------------ *
 * KKTC Resmî Gazete — karar arama uygulaması (vanilla JS, no deps)
 * ------------------------------------------------------------------ */

const CATS = [
  { key: "atama",                 label: "Atamalar",              short: "Atama" },
  { key: "gorevden_alma",         label: "Görevden Almalar",      short: "Görevden Alma" },
  { key: "yurttasliga_alinma",    label: "Yurttaşlığa Alınma",    short: "Yurttaşlığa Alınma" },
  { key: "yurttasliktan_cikarma", label: "Yurttaşlıktan Çıkarılma", short: "Yurttaşlıktan Çıkarılma" },
];
const CAT_LABEL = Object.fromEntries(CATS.map(c => [c.key, c]));
const PAGE = 200; // rows rendered per page

const state = {
  summary: null,
  data: null,            // full decisions array (lazy-loaded)
  selectedCats: new Set(),
  hiddenSeries: new Set(),
  yearFrom: null,
  yearTo: null,
  q: "",
  sortDesc: true,
  shown: PAGE,
  filtered: [],
};

const $ = sel => document.querySelector(sel);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};
const fmt = n => n.toLocaleString("tr-TR");
const esc = s => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ------------------------------- boot ---------------------------- */
init();

async function init() {
  initTheme();
  try {
    state.summary = await (await fetch("data/summary.json")).json();
  } catch (e) {
    $("#loadState").textContent = "summary.json yüklenemedi. Önce scraper.py çalıştırın ve web/ klasörünü bir sunucu ile açın.";
    $("#loadState").classList.add("err");
    return;
  }
  buildDashboard();
  buildFilters();
  bindEvents();
  // Prefetch the full dataset so search is instant.
  loadData();
}

/* ----------------------------- dashboard ------------------------- */
function totalFor(catKey) {
  return Object.values(state.summary.years)
    .reduce((s, y) => s + (y.counts[catKey] || 0), 0);
}

function buildDashboard() {
  const grid = $("#statGrid");
  const totalDecisions = Object.values(state.summary.years).reduce((s, y) => s + y.decisions, 0);
  const totalIssues = Object.values(state.summary.years).reduce((s, y) => s + y.issues, 0);
  const years = Object.keys(state.summary.years).sort();
  const yearSpan = `${years[0]}–${years[years.length - 1]}`;

  CATS.forEach(c => {
    const card = el("div", "stat-card");
    card.style.setProperty("--c", `var(--c-${c.key})`);
    card.dataset.cat = c.key;
    card.innerHTML = `
      <div class="label"><span class="dot"></span>${c.label}</div>
      <div class="value">${fmt(totalFor(c.key))}</div>
      <div class="sub">${yearSpan} toplam karar</div>`;
    card.addEventListener("click", () => {
      toggleCat(c.key);
      $("#q").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    grid.appendChild(card);
  });

  $("#metaLine").innerHTML =
    `${fmt(totalIssues)} gazete sayısı · ${fmt(totalDecisions)} karar kaydı · ${years.length} yıl ` +
    `(${years[0]}–${years[years.length - 1]}) · güncellenme: ${state.summary.generated.slice(0, 10)}`;

  buildLegend();
  drawChart();
}

function buildLegend() {
  const leg = $("#chartLegend");
  leg.innerHTML = "";
  CATS.forEach(c => {
    const item = el("span", "legend-item");
    item.dataset.cat = c.key;
    item.innerHTML = `<span class="swatch" style="background:var(--c-${c.key})"></span>${c.short}`;
    item.addEventListener("click", () => {
      if (state.hiddenSeries.has(c.key)) state.hiddenSeries.delete(c.key);
      else state.hiddenSeries.add(c.key);
      item.classList.toggle("off");
      drawChart();
    });
    leg.appendChild(item);
  });
}

function drawChart() {
  const years = Object.keys(state.summary.years).sort();
  const active = CATS.filter(c => !state.hiddenSeries.has(c.key));
  const W = Math.max(640, years.length * 56);
  const H = 300, padL = 44, padB = 28, padT = 12, padR = 8;
  const plotW = W - padL - padR, plotH = H - padT - padB;

  let max = 1;
  years.forEach(y => active.forEach(c =>
    max = Math.max(max, state.summary.years[y].counts[c.key] || 0)));
  const niceMax = niceCeil(max);

  const x = i => padL + (i + 0.5) * (plotW / years.length);
  const yScale = v => padT + plotH - (v / niceMax) * plotH;
  const groupW = (plotW / years.length) * 0.72;
  const barW = Math.max(3, groupW / Math.max(active.length, 1));

  let svg = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img">`;
  // gridlines + y labels
  const ticks = 4;
  for (let t = 0; t <= ticks; t++) {
    const val = (niceMax / ticks) * t;
    const yy = yScale(val);
    svg += `<line class="grid-line" x1="${padL}" y1="${yy}" x2="${W - padR}" y2="${yy}"/>`;
    svg += `<text class="axis-label" x="${padL - 6}" y="${yy + 3}" text-anchor="end">${fmt(val)}</text>`;
  }
  // bars
  years.forEach((y, i) => {
    const cx = x(i);
    const start = cx - groupW / 2;
    svg += `<g class="bar-group">`;
    active.forEach((c, j) => {
      const v = state.summary.years[y].counts[c.key] || 0;
      const bx = start + j * barW;
      const by = yScale(v);
      const bh = padT + plotH - by;
      svg += `<rect class="bar hl" x="${bx.toFixed(1)}" y="${by.toFixed(1)}" `
           + `width="${(barW - 1).toFixed(1)}" height="${Math.max(0, bh).toFixed(1)}" `
           + `rx="2" fill="var(--c-${c.key})" `
           + `data-tip="${y} · ${c.short}: ${fmt(v)}"></rect>`;
    });
    svg += `</g>`;
    svg += `<text class="year-label" x="${cx}" y="${H - 8}" text-anchor="middle">${y.slice(2)}</text>`;
  });
  svg += `</svg>`;
  $("#chart").innerHTML = svg;
  attachChartTips();
}

function niceCeil(v) {
  if (v <= 5) return 5;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / mag;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * mag;
}

let tipEl;
function attachChartTips() {
  if (!tipEl) { tipEl = el("div", "chart-tip"); document.body.appendChild(tipEl); }
  $("#chart").querySelectorAll("rect.bar").forEach(r => {
    r.addEventListener("mousemove", e => {
      tipEl.textContent = r.dataset.tip;
      tipEl.style.opacity = "1";
      tipEl.style.left = (e.clientX + 12) + "px";
      tipEl.style.top = (e.clientY - 8) + "px";
    });
    r.addEventListener("mouseleave", () => { tipEl.style.opacity = "0"; });
  });
}

/* ----------------------------- filters --------------------------- */
function buildFilters() {
  const chips = $("#catChips");
  CATS.forEach(c => {
    const chip = el("span", "chip");
    chip.style.setProperty("--c", `var(--c-${c.key})`);
    chip.dataset.cat = c.key;
    chip.innerHTML = `<span class="dot"></span>${c.short}`;
    chip.addEventListener("click", () => toggleCat(c.key));
    chips.appendChild(chip);
  });

  const years = Object.keys(state.summary.years).sort();
  const from = $("#yearFrom"), to = $("#yearTo");
  years.forEach(y => {
    from.appendChild(new Option(y, y));
    to.appendChild(new Option(y, y));
  });
  state.yearFrom = +years[0];
  state.yearTo = +years[years.length - 1];
  from.value = state.yearFrom;
  to.value = state.yearTo;
}

function toggleCat(key) {
  if (state.selectedCats.has(key)) state.selectedCats.delete(key);
  else state.selectedCats.add(key);
  syncCatUI();
  applyFilters();
}

function syncCatUI() {
  document.querySelectorAll(".chip").forEach(ch =>
    ch.classList.toggle("on", state.selectedCats.has(ch.dataset.cat)));
  document.querySelectorAll(".stat-card").forEach(c =>
    c.classList.toggle("active", state.selectedCats.has(c.dataset.cat)));
}

/* ----------------------------- events ---------------------------- */
function bindEvents() {
  const q = $("#q"), clearQ = $("#clearQ");
  q.addEventListener("input", debounce(() => {
    state.q = q.value.trim();
    clearQ.hidden = !state.q;
    applyFilters();
  }, 180));
  clearQ.addEventListener("click", () => {
    q.value = ""; state.q = ""; clearQ.hidden = true; q.focus(); applyFilters();
  });

  $("#yearFrom").addEventListener("change", e => { state.yearFrom = +e.target.value; applyFilters(); });
  $("#yearTo").addEventListener("change", e => { state.yearTo = +e.target.value; applyFilters(); });

  $("#moreBtn").addEventListener("click", () => { state.shown += PAGE; renderRows(); });
  $("#exportBtn").addEventListener("click", exportCsv);

  document.querySelector("th[data-sort]").addEventListener("click", () => {
    state.sortDesc = !state.sortDesc;
    applyFilters();
  });
}

/* --------------------------- data load --------------------------- */
async function loadData() {
  try {
    const res = await fetch("data/decisions.json");
    if (!res.ok) throw new Error(res.status);
    state.data = await res.json();
    $("#loadState").hidden = true;
    $("#tableWrap").hidden = false;
    $("#exportBtn").disabled = false;
    applyFilters();
  } catch (e) {
    $("#loadState").textContent =
      "decisions.json yüklenemedi (" + e.message + "). web/ klasörünü bir HTTP sunucusu üzerinden açın.";
    $("#loadState").classList.add("err");
  }
}

/* --------------------------- filtering --------------------------- */
function tokenize(q) { return q.toLowerCase().split(/\s+/).filter(Boolean); }

function applyFilters() {
  if (!state.data) return;
  const cats = state.selectedCats;
  const yF = state.yearFrom, yT = state.yearTo;
  const tokens = tokenize(state.q);

  const out = [];
  for (const r of state.data) {
    if (r.y < yF || r.y > yT) continue;
    if (cats.size && !r.cats.some(c => cats.has(c))) continue;
    if (tokens.length) {
      const hay = (r.desc + " " + r.kno + " " + r.ek + " " + r.no).toLowerCase();
      let ok = true;
      for (const t of tokens) { if (!hay.includes(t)) { ok = false; break; } }
      if (!ok) continue;
    }
    out.push(r);
  }
  // Dateless records (a handful of issues lack a printed date at the source)
  // sort by their year so they stay grouped with it instead of sinking to the end.
  const key = r => r.iso || String(r.y);
  out.sort((a, b) => state.sortDesc
    ? key(b).localeCompare(key(a))
    : key(a).localeCompare(key(b)));

  state.filtered = out;
  state.shown = PAGE;
  renderCount();
  renderRows();
}

function renderCount() {
  const n = state.filtered.length;
  let extra = "";
  if (state.selectedCats.size) {
    extra = " · " + [...state.selectedCats].map(k => CAT_LABEL[k].short).join(", ");
  }
  $("#resultCount").innerHTML = `<b>${fmt(n)}</b> karar bulundu (${state.yearFrom}–${state.yearTo})${extra}`;
}

function highlight(text) {
  const tokens = tokenize(state.q);
  let safe = esc(text);
  if (!tokens.length) return safe;
  // escape tokens for regex
  const re = new RegExp("(" + tokens.map(t =>
    t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "gi");
  return safe.replace(re, "<mark>$1</mark>");
}

function catBadges(r) {
  return r.cats.map(k => {
    const c = CAT_LABEL[k];
    if (!c) return "";
    return `<span class="badge" style="background:var(--c-${k})">${c.short}</span>`;
  }).join(" ");
}

function renderRows() {
  const tbody = $("#rows");
  const slice = state.filtered.slice(0, state.shown);
  const frag = document.createDocumentFragment();
  for (const r of slice) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td class="c-date">${r.date || "—"}</td>` +
      `<td class="c-issue"><a class="issue-link" href="${esc(r.pdf)}" target="_blank" rel="noopener">${esc(r.no)} ↗</a></td>` +
      `<td class="c-kno"><span class="kno-cell">${highlight(r.kno || "—")}</span></td>` +
      `<td class="c-ek">${esc(r.ek || "—")}</td>` +
      `<td class="c-cat">${catBadges(r) || '<span class="muted small">—</span>'}</td>` +
      `<td class="c-desc">${highlight(r.desc)}</td>`;
    frag.appendChild(tr);
  }
  tbody.replaceChildren(frag);
  $("#moreBtn").hidden = state.shown >= state.filtered.length;
  $("#moreBtn").textContent =
    `Daha fazla göster (${fmt(state.shown)} / ${fmt(state.filtered.length)})`;
}

/* ----------------------------- export ---------------------------- */
function exportCsv() {
  const rows = state.filtered;
  const head = ["Yil", "Sayi", "Tarih", "KararNo", "Ek", "Kategoriler", "KararMetni", "PDF"];
  const q = s => '"' + String(s || "").replace(/"/g, '""') + '"';
  const lines = [head.join(",")];
  for (const r of rows) {
    lines.push([r.y, r.no, r.date, r.kno, r.ek,
      r.cats.map(k => CAT_LABEL[k] ? CAT_LABEL[k].short : k).join(" | "),
      r.desc, r.pdf].map(q).join(","));
  }
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = el("a");
  a.href = URL.createObjectURL(blob);
  a.download = `resmi-gazete-kararlar-${state.yearFrom}-${state.yearTo}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ------------------------------ misc ----------------------------- */
function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
function store(key, val) {
  try {
    if (val === undefined) return window.localStorage.getItem(key);
    window.localStorage.setItem(key, val);
  } catch (e) { return null; }
}
function prefersDark() {
  try { return window.matchMedia("(prefers-color-scheme: dark)").matches; }
  catch (e) { return false; }
}
function initTheme() {
  const saved = store("rg-theme");
  const dark = saved ? saved === "dark" : prefersDark();
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  $("#themeToggle").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    store("rg-theme", next);
  });
}
