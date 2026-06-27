/* RegionLens — конвергенция регионов (поток B, научное ядро).
   σ-сходимость: разброс индекса по годам (/api/index/dispersion/).
   β-сходимость: изменение индекса за период vs стартовый уровень
   (/api/index/beta/ — сводка-регрессия + /api/index/?year= — баллы по регионам). */

(function () {
  "use strict";

  if (!document.getElementById("cv-chart")) return;
  if (typeof Plotly === "undefined") return;

  var MEASURE_RU = {
    cv: "Коэффициент вариации",
    gini: "Индекс Джини",
    p90_p10: "Отношение P90/P10",
    std: "Стандартное отклонение",
  };
  var FONT = { family: "Golos Text, sans-serif", color: "#51606e" };
  var GRID = "#e9e3d6";

  var $measure = document.getElementById("cv-measure");
  var $scheme = document.getElementById("cv-scheme");
  var $chart = document.getElementById("cv-chart");
  var $readout = document.getElementById("cv-readout");
  var $betaChart = document.getElementById("beta-chart");
  var $betaReadout = document.getElementById("beta-readout");

  var dispData = null; // σ: разброс по годам
  var betaData = null; // β: сводка-регрессия по схемам
  var names = null; // okato -> region_name

  function shell(el, msg) {
    if (el) el.innerHTML = '<div class="shell"><p>' + msg + "</p></div>";
  }
  function asJson(r) {
    if (!r.ok) throw new Error("Ошибка загрузки (" + r.status + ")");
    return r.json();
  }
  // Plotly не очищает контейнер сам — убираем заглушку/старый график перед отрисовкой.
  function plot(id, traces, layout, config) {
    var el = document.getElementById(id);
    if (el) el.innerHTML = "";
    Plotly.newPlot(id, traces, layout, config);
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

  // ── σ-сходимость: тренд разброса индекса ──────────────────────────────────
  function renderSigma() {
    if (!dispData) return;
    var scheme = $scheme.value;
    var measure = $measure.value;
    var pts = dispData
      .filter(function (r) { return r.weighting_scheme === scheme && r[measure] != null; })
      .sort(function (a, b) { return a.year - b.year; });
    if (!pts.length) {
      shell($chart, "Нет данных для выбранной схемы.");
      $readout.textContent = "";
      return;
    }
    var years = pts.map(function (p) { return p.year; });
    var vals = pts.map(function (p) { return p[measure]; });
    plot(
      "cv-chart",
      [
        {
          x: years, y: vals, mode: "lines+markers", type: "scatter",
          line: { color: "#1f6f63", width: 2 }, marker: { size: 5 },
          hovertemplate: "%{x}: %{y:.3f}<extra></extra>",
        },
      ],
      {
        margin: { l: 60, r: 16, t: 8, b: 36 }, height: 360,
        yaxis: { title: MEASURE_RU[measure], gridcolor: GRID },
        xaxis: { dtick: 2, gridcolor: GRID },
        paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: FONT,
      },
      { responsive: true, displayModeBar: false }
    );
    var first = vals[0];
    var last = vals[vals.length - 1];
    var chg = first !== 0 ? ((last - first) / Math.abs(first)) * 100 : 0;
    var dir = last < first ? "снизился" : "вырос";
    var verdict = last < first ? "σ-сходимость: регионы сблизились" : "расхождение: разрыв усилился";
    $readout.textContent =
      MEASURE_RU[measure] + " " + years[0] + "→" + years[years.length - 1] + ": " + dir +
      " на " + Math.abs(chg).toFixed(0) + "% (" + first.toFixed(3) + " → " + last.toFixed(3) +
      "). " + verdict + ".";
  }

  // ── β-сходимость: рост за период vs стартовый уровень ─────────────────────
  function renderBeta() {
    if (!betaData) return;
    var scheme = $scheme.value;
    var b = null;
    betaData.forEach(function (r) { if (r.weighting_scheme === scheme) b = r; });
    if (!b) {
      shell($betaChart, "Нет данных для выбранной схемы.");
      $betaReadout.textContent = "";
      return;
    }
    shell($betaChart, "Загрузка…");
    Promise.all([
      ensureNames(),
      fetch("/api/index/?year=" + b.year_start + "&scheme=" + scheme).then(asJson),
      fetch("/api/index/?year=" + b.year_end + "&scheme=" + scheme).then(asJson),
    ])
      .then(function (out) {
        var init = {}, fin = {};
        out[1].forEach(function (r) { init[r.okato] = r.total_score; });
        out[2].forEach(function (r) { fin[r.okato] = r.total_score; });
        var xs = [], ys = [], text = [];
        Object.keys(init).forEach(function (o) {
          if (fin[o] == null) return;
          var g = fin[o] - init[o];
          xs.push(init[o]);
          ys.push(g);
          text.push(
            ((names && names[o]) || o) + "<br>старт " + init[o].toFixed(1) +
            " · изменение " + (g >= 0 ? "+" : "") + g.toFixed(1)
          );
        });
        var xmin = Math.min.apply(null, xs), xmax = Math.max.apply(null, xs);
        var lineX = [xmin, xmax];
        var lineY = [b.intercept + b.beta * xmin, b.intercept + b.beta * xmax];
        plot(
          "beta-chart",
          [
            {
              x: xs, y: ys, mode: "markers", type: "scatter",
              marker: { size: 7, color: "#1f6f63", opacity: 0.8 },
              text: text, hovertemplate: "%{text}<extra></extra>",
            },
            {
              x: lineX, y: lineY, mode: "lines", type: "scatter",
              line: { color: "#b4532a", width: 2 }, hoverinfo: "skip",
            },
          ],
          {
            margin: { l: 60, r: 16, t: 8, b: 44 }, height: 420, showlegend: false,
            xaxis: { title: "Стартовый уровень индекса (" + b.year_start + ")", gridcolor: GRID },
            yaxis: {
              title: "Изменение к " + b.year_end, gridcolor: GRID,
              zeroline: true, zerolinecolor: "#cfc8ba",
            },
            paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: FONT,
          },
          { responsive: true, displayModeBar: false }
        );
        var verdict = b.beta < 0
          ? "β-сходимость: изначально отстающие росли быстрее (догоняние)"
          : "β-дивергенция: лидеры росли быстрее";
        $betaReadout.textContent =
          "β = " + b.beta.toFixed(3) + ", r = " + (b.correlation != null ? b.correlation.toFixed(2) : "—") +
          " (R² = " + (b.r_squared != null ? b.r_squared.toFixed(2) : "—") + "), " +
          b.year_start + "→" + b.year_end + ". " + verdict + ".";
      })
      .catch(function (e) {
        shell($betaChart, RL.errText(e));
        $betaReadout.textContent = "";
      });
  }

  $measure.addEventListener("change", renderSigma);
  $scheme.addEventListener("change", function () {
    renderSigma();
    renderBeta();
  });

  fetch("/api/index/dispersion/")
    .then(asJson)
    .then(function (rows) { dispData = rows; renderSigma(); })
    .catch(function (e) { shell($chart, RL.errText(e)); });
  fetch("/api/index/beta/")
    .then(asJson)
    .then(function (rows) { betaData = rows; renderBeta(); })
    .catch(function (e) { shell($betaChart, RL.errText(e)); });
})();
