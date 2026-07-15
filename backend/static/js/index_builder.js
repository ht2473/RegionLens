/* RegionLens — конструктор индекса.
   Пользователь задаёт веса шести доменов; рейтинг пересобирается через
   /api/index/custom/?year=&w_<domain>=. Стрелки — сдвиг ранга относительно равных весов.
   Веса на ползунках — условные единицы 0–10; рядом всегда показан их нормированный вклад
   в проценты (сумма весов = 100%), чтобы цифры на ползунках были понятны без пересчёта. */

(function () {
  "use strict";

  var root = document.getElementById("builder-root");
  if (!root) return;

  var DOMAINS = [
    ["economy", gettext("Экономика")],
    ["income", gettext("Доходы")],
    ["demography", gettext("Демография")],
    ["labor", gettext("Труд")],
    ["infrastructure", gettext("Инфраструктура")],
    ["health_edu", gettext("Здоровье и образование")],
  ];
  var PALETTE = ["#1f6f63", "#3b6ea5", "#b4532a", "#8a6fab", "#c9973a", "#4f8a8b"];
  var POS = RL.cssVar("--good", "#1f6f63");
  var NEG = RL.cssVar("--bad", "#b4532a");
  var FONT = { family: "Golos Text, system-ui, sans-serif", size: 12, color: RL.cssVar("--ink-soft", "#51606e") };

  var state = { year: RL.prefYear(2024) };
  RL.syncYearControl(state.year);

  var slidersEl = document.getElementById("weight-sliders");
  var weightChartEl = document.getElementById("weight-chart");
  var moversEl = document.getElementById("weight-movers");
  var weights = {};
  DOMAINS.forEach(function (d) { weights[d[0]] = 1; }); // равные веса по умолчанию

  function num(x) { return x == null ? "—" : Number(x).toFixed(1); }

  function arrow(delta) {
    if (delta > 0) return '<span style="color:' + POS + '">▲ +' + delta + "</span>";
    if (delta < 0) return '<span style="color:' + NEG + '">▼ ' + (-delta) + "</span>";
    return '<span class="muted">= 0</span>';
  }

  // Нормированные проценты веса по текущим значениям ползунков (сумма = 100%, либо равные
  // доли, если пользователь обнулил все веса разом) — та же нормировка, что и на бэкенде.
  // Общая формула вынесена в RL.normalizeWeights (её же покрывают юнит-тесты).
  function normalizedPct() {
    return RL.normalizeWeights(weights, DOMAINS.map(function (d) { return d[0]; }));
  }

  function buildSliders() {
    var pct = normalizedPct();
    slidersEl.innerHTML = DOMAINS.map(function (d) {
      var key = d[0];
      return (
        '<div class="kpi"><div class="kpi-label">' + d[1] +
        ' — <strong id="wv-' + key + '">' + weights[key] + "</strong> " +
        '<span class="kpi-sub" id="wp-' + key + '">(' + pct[key].toFixed(0) + "%)</span></div>" +
        '<input type="range" class="w-slider" data-domain="' + key +
        '" min="0" max="10" step="1" value="' + weights[key] + '" ' +
        'aria-label="' + d[1] + '"></div>'
      );
    }).join("");
    slidersEl.querySelectorAll(".w-slider").forEach(function (el) {
      el.addEventListener("input", function () {
        var key = el.getAttribute("data-domain");
        weights[key] = Number(el.value);
        document.getElementById("wv-" + key).textContent = el.value;
        var p = normalizedPct();
        DOMAINS.forEach(function (d) {
          var sub = document.getElementById("wp-" + d[0]);
          if (sub) sub.textContent = "(" + p[d[0]].toFixed(0) + "%)";
        });
        drawWeightChart();
        scheduleLoad();
      });
    });
  }

  // Донат-график вклада доменов: наглядно превращает шесть отвлечённых ползунков в одну
  // понятную картинку «на что сейчас сделан упор». Перерисовывается на каждое движение
  // ползунка через Plotly.react — без пересоздания графика.
  function drawWeightChart() {
    if (!weightChartEl || typeof Plotly === "undefined") return;
    var pct = normalizedPct();
    var labels = DOMAINS.map(function (d) { return d[1]; });
    var values = DOMAINS.map(function (d) { return pct[d[0]]; });
    Plotly.react(
      weightChartEl,
      [{
        type: "pie", hole: 0.55, labels: labels, values: values,
        marker: { colors: PALETTE },
        textinfo: "label+percent", textposition: "outside", automargin: true,
        hovertemplate: "%{label}: %{percent}<extra></extra>",
      }],
      {
        font: FONT, height: 300, showlegend: false,
        margin: { t: 34, b: 20, l: 20, r: 20 },
        paper_bgcolor: "rgba(0,0,0,0)",
      },
      { responsive: true }
    );
  }

  var timer = null;
  function scheduleLoad() { clearTimeout(timer); timer = setTimeout(load, 250); }

  function queryString() {
    var parts = ["year=" + state.year];
    DOMAINS.forEach(function (d) { parts.push("w_" + d[0] + "=" + weights[d[0]]); });
    return parts.join("&");
  }

  // «Лидеры смещения»: какие регионы сильнее всего выиграли/проиграли от заданных весов —
  // самая понятная сводка результата, без необходимости листать всю таблицу в поисках экстремумов.
  function renderMovers(rows) {
    if (!moversEl) return;
    var withDelta = rows.filter(function (r) { return r.delta != null; });
    if (!withDelta.length) { moversEl.innerHTML = ""; return; }
    var riser = withDelta.slice().sort(function (a, b) { return b.delta - a.delta; })[0];
    var faller = withDelta.slice().sort(function (a, b) { return a.delta - b.delta; })[0];
    function card(label, r, good) {
      if (!r || r.delta === 0) return "";
      var color = good ? POS : NEG;
      var sign = r.delta > 0 ? "+" : "";
      return (
        '<div class="kpi"><div class="kpi-label">' + label + "</div>" +
        '<div class="kpi-type">' + (r.region_name || r.okato) + "</div>" +
        '<div class="kpi-delta" style="color:' + color + '">' + sign + r.delta + " " + gettext("мест") + "</div></div>"
      );
    }
    var html = card(gettext("Больше всего выигрывает"), riser, true) + card(gettext("Больше всего теряет"), faller, false);
    moversEl.innerHTML = html ? '<div class="kpi-row">' + html + "</div>" : "";
  }

  function render(rows) {
    if (!rows.length) {
      root.innerHTML = '<div class="shell"><p>' + gettext("Нет данных за выбранный год.") + "</p></div>";
      renderMovers([]);
      return;
    }
    renderMovers(rows);
    var maxScore = Math.max.apply(null, rows.map(function (r) { return r.score || 0; })) || 1;
    var html =
      '<div class="table-wrap"><table class="table"><thead><tr><th>#</th><th>' + gettext("Регион") +
      "</th><th>" + gettext("Балл") + "</th><th>" + gettext("Сдвиг к равным весам") +
      "</th></tr></thead><tbody>";
    rows.forEach(function (r) {
      var w = Math.max(2, Math.round((100 * (r.score || 0)) / maxScore));
      html +=
        "<tr><td>" + r.rank + "</td><td>" + (r.region_name || r.okato) +
        "</td><td><strong>" + num(r.score) + "</strong><div class='score-bar'><span style='width:" + w + "%'></span></div></td>" +
        "<td>" + arrow(r.delta) + "</td></tr>";
    });
    html += "</tbody></table></div>";
    root.innerHTML = html;
  }

  function load() {
    root.innerHTML = '<div class="shell"><p>' + gettext("Пересчёт рейтинга…") + "</p></div>";
    fetch("/api/index/custom/?" + queryString())
      .then(function (r) {
        if (!r.ok) throw new Error(gettext("Ошибка расчёта") + " (" + r.status + ")");
        return r.json();
      })
      .then(render)
      .catch(function (e) {
        root.innerHTML = '<div class="shell"><p>' + RL.errText(e) + "</p></div>";
      });
  }

  var yearSlider = document.getElementById("year-slider");
  if (yearSlider) {
    yearSlider.addEventListener("input", function (e) {
      state.year = Number(e.target.value);
      document.getElementById("year-label").textContent = e.target.value;
      scheduleLoad();
    });
  }
  document.getElementById("reset-weights").addEventListener("click", function () {
    DOMAINS.forEach(function (d) { weights[d[0]] = 1; });
    buildSliders();
    drawWeightChart();
    load();
  });

  buildSliders();
  drawWeightChart();
  load();
})();
