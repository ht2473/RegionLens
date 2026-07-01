/* RegionLens — лаборатория индекса (поток B, научное ядро).
   Прозрачность зависимости индекса от схемы весов:
   1) тренд согласованности схем по годам (/api/index/scheme-agreement/, Спирмен);
   2) scatter «место по схеме X vs по схеме Y» за год — какие регионы расходятся (рейтинги из
      /api/index/?year=&scheme=). Имена регионов — /api/regions/. */

(function () {
  "use strict";

  if (!document.getElementById("lab-agreement")) return;
  if (typeof Plotly === "undefined") return;

  var SCHEME_RU = { equal: gettext("равные"), pca: "PCA", expert: gettext("экспертные") };
  var COLORS = ["#1f6f63", "#b4532a", "#3b6ea5"];
  var GOOD = "#1f6f63";
  var WIDE = "#b4532a";
  var WIDE_GAP = 10; // |разница мест| ≥ — считаем регион «расходящимся»
  var FONT = { family: "Golos Text, sans-serif", color: RL.cssVar("--ink-soft", "#51606e") };
  var GRID = RL.cssVar("--line-soft", "#e9e3d6");

  var state = { year: RL.prefYear(2024) };
  var names = null; // okato -> region_name

  function shell(id, msg) {
    var el = document.getElementById(id);
    if (el) el.innerHTML = '<div class="shell"><p>' + msg + "</p></div>";
  }
  function asJson(r) {
    if (!r.ok) throw new Error(gettext("Ошибка загрузки") + " (" + r.status + ")");
    return r.json();
  }
  function ensureNames() {
    if (names) return Promise.resolve(names);
    return fetch("/api/regions/")
      .then(asJson)
      .then(function (rows) {
        names = {};
        rows.forEach(function (r) { names[r.okato] = r.region_name; });
        return names;
      });
  }
  function baseLayout(extra) {
    var l = {
      margin: { l: 56, r: 16, t: 8, b: 44 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: FONT,
    };
    Object.keys(extra || {}).forEach(function (k) { l[k] = extra[k]; });
    return l;
  }
  // Plotly не удаляет прежнее содержимое контейнера (заглушку «Загрузка…»/старый график) —
  // очищаем сами перед отрисовкой, иначе заглушка остаётся рядом с графиком.
  function plot(id, traces, layout, config) {
    var el = document.getElementById(id);
    if (el) el.innerHTML = "";
    Plotly.newPlot(id, traces, layout, config);
  }

  // ── Тренд согласованности схем ───────────────────────────────────────────
  function renderTrend(rows) {
    if (!rows.length) {
      shell("lab-agreement", gettext("Нет данных о согласованности схем."));
      return;
    }
    var byPair = {};
    rows.forEach(function (r) {
      var key = r.scheme_a + "|" + r.scheme_b;
      (byPair[key] = byPair[key] || []).push(r);
    });
    var traces = Object.keys(byPair).map(function (key, i) {
      var pts = byPair[key].slice().sort(function (a, b) { return a.year - b.year; });
      var parts = key.split("|");
      return {
        x: pts.map(function (p) { return p.year; }),
        y: pts.map(function (p) { return p.spearman; }),
        mode: "lines+markers",
        type: "scatter",
        name: SCHEME_RU[parts[0]] + "–" + SCHEME_RU[parts[1]],
        line: { color: COLORS[i % COLORS.length], width: 2 },
        marker: { size: 5 },
      };
    });
    plot(
      "lab-agreement",
      traces,
      baseLayout({
        height: 300,
        margin: { l: 56, r: 16, t: 8, b: 36 },
        yaxis: { title: gettext("Спирмен ρ"), gridcolor: GRID },
        xaxis: { dtick: 2, gridcolor: GRID },
        legend: { orientation: "h" },
      }),
      { responsive: true, displayModeBar: false }
    );
  }

  // ── Scatter: место по схеме X vs по схеме Y ───────────────────────────────
  function renderScatter(a, b, rankA, rankB) {
    var okatos = Object.keys(rankA).filter(function (o) { return rankB[o] != null; });
    if (!okatos.length) {
      shell("lab-scatter", gettext("Нет данных за выбранный год."));
      return;
    }
    var xs = [], ys = [], text = [], colors = [], n = okatos.length;
    okatos.forEach(function (o) {
      var ra = rankA[o], rb = rankB[o];
      xs.push(ra);
      ys.push(rb);
      var nm = (names && names[o]) || o;
      text.push(
        nm + "<br>" + SCHEME_RU[a] + ": " + ra + " · " + SCHEME_RU[b] + ": " + rb +
        " (" + gettext("разница") + " " + Math.abs(ra - rb) + ")"
      );
      colors.push(Math.abs(ra - rb) >= WIDE_GAP ? WIDE : GOOD);
    });
    plot(
      "lab-scatter",
      [
        {
          x: xs, y: ys, mode: "markers", type: "scatter",
          marker: { size: 7, color: colors, opacity: 0.82 },
          text: text, hovertemplate: "%{text}<extra></extra>",
        },
      ],
      baseLayout({
        height: 460,
        xaxis: { title: gettext("Место") + " — " + SCHEME_RU[a], gridcolor: GRID },
        yaxis: { title: gettext("Место") + " — " + SCHEME_RU[b], gridcolor: GRID, scaleanchor: "x", scaleratio: 1 },
        shapes: [
          { type: "line", x0: 1, y0: 1, x1: n, y1: n, line: { color: "#8a96a1", width: 1, dash: "dot" } },
        ],
      }),
      { responsive: true, displayModeBar: false }
    );
  }

  function loadScatter() {
    var a = $a.value, b = $b.value, year = state.year;
    if (a === b) {
      shell("lab-scatter", gettext("Выберите две разные схемы."));
      return;
    }
    shell("lab-scatter", gettext("Загрузка…"));
    Promise.all([
      ensureNames(),
      fetch("/api/index/?year=" + year + "&scheme=" + a).then(asJson),
      fetch("/api/index/?year=" + year + "&scheme=" + b).then(asJson),
    ])
      .then(function (out) {
        var ra = {}, rb = {};
        out[1].forEach(function (r) { ra[r.okato] = r.rank; });
        out[2].forEach(function (r) { rb[r.okato] = r.rank; });
        renderScatter(a, b, ra, rb);
      })
      .catch(function (e) { shell("lab-scatter", RL.errText(e)); });
  }

  // ── Контролы ──────────────────────────────────────────────────────────────
  var $year = document.getElementById("lab-year");
  var $yearLabel = document.getElementById("lab-year-label");
  var $a = document.getElementById("lab-a");
  var $b = document.getElementById("lab-b");
  if ($year) $year.value = state.year;
  if ($yearLabel) $yearLabel.textContent = state.year;
  if ($a) $a.value = RL.prefScheme("equal");

  $year.addEventListener("input", function () {
    state.year = parseInt($year.value, 10);
    $yearLabel.textContent = state.year;
  });
  $year.addEventListener("change", loadScatter);
  $a.addEventListener("change", loadScatter);
  $b.addEventListener("change", loadScatter);

  // ── Старт ──────────────────────────────────────────────────────────────────
  fetch("/api/index/scheme-agreement/")
    .then(asJson)
    .then(renderTrend)
    .catch(function (e) { shell("lab-agreement", RL.errText(e)); });
  loadScatter();
})();
