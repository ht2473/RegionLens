/* RegionLens — конструктор индекса.
   Пользователь задаёт веса шести доменов; рейтинг пересобирается через
   /api/index/custom/?year=&w_<domain>=. Стрелки — сдвиг ранга относительно равных весов. */

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
  var POS = RL.cssVar("--good", "#1f6f63");
  var NEG = RL.cssVar("--bad", "#b4532a");

  var state = { year: RL.prefYear(2024) };
  RL.syncYearControl(state.year);

  var slidersEl = document.getElementById("weight-sliders");
  var weights = {};
  DOMAINS.forEach(function (d) { weights[d[0]] = 1; }); // равные веса по умолчанию

  function num(x) { return x == null ? "—" : Number(x).toFixed(1); }

  function arrow(delta) {
    if (delta > 0) return '<span style="color:' + POS + '">▲ ' + delta + "</span>";
    if (delta < 0) return '<span style="color:' + NEG + '">▼ ' + (-delta) + "</span>";
    return '<span class="muted">—</span>';
  }

  function buildSliders() {
    slidersEl.innerHTML = DOMAINS.map(function (d) {
      var key = d[0];
      return (
        '<div class="kpi"><div class="kpi-label">' + d[1] +
        ' — <strong id="wv-' + key + '">' + weights[key] + "</strong></div>" +
        '<input type="range" class="w-slider" data-domain="' + key +
        '" min="0" max="10" step="1" value="' + weights[key] + '"></div>'
      );
    }).join("");
    slidersEl.querySelectorAll(".w-slider").forEach(function (el) {
      el.addEventListener("input", function () {
        var key = el.getAttribute("data-domain");
        weights[key] = Number(el.value);
        document.getElementById("wv-" + key).textContent = el.value;
        scheduleLoad();
      });
    });
  }

  var timer = null;
  function scheduleLoad() { clearTimeout(timer); timer = setTimeout(load, 250); }

  function queryString() {
    var parts = ["year=" + state.year];
    DOMAINS.forEach(function (d) { parts.push("w_" + d[0] + "=" + weights[d[0]]); });
    return parts.join("&");
  }

  function render(rows) {
    if (!rows.length) {
      root.innerHTML = '<div class="shell"><p>' + gettext("Нет данных за выбранный год.") + "</p></div>";
      return;
    }
    var html =
      '<table class="table"><thead><tr><th>#</th><th>' + gettext("Регион") +
      "</th><th>" + gettext("Балл") + "</th><th>" + gettext("Сдвиг к равным") +
      "</th></tr></thead><tbody>";
    rows.forEach(function (r) {
      html +=
        "<tr><td>" + r.rank + "</td><td>" + (r.region_name || r.okato) +
        "</td><td>" + num(r.score) + "</td><td>" + arrow(r.delta) + "</td></tr>";
    });
    html += "</tbody></table>";
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
    load();
  });

  buildSliders();
  load();
})();
