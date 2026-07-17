/* RegionLens — сценарный анализ (what-if).
   Пользователь выбирает регион и «подтягивает» его домены до целевых перцентилей;
   /api/index/scenario/ возвращает базовое и сценарное место. Учитываются только домены,
   отклонённые от текущего положения региона. */

(function () {
  "use strict";

  var root = document.getElementById("scenario-root");
  var slidersEl = document.getElementById("scenario-sliders");
  var summaryEl = document.getElementById("scenario-summary");
  var regionSelect = document.getElementById("region-select");
  if (!root || !slidersEl || !regionSelect) return;

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

  var state = { year: RL.prefYear(2024), okato: null };
  RL.syncYearControl(state.year);
  var presets = {}; // domain -> текущий перцентиль
  var currentPct = {}; // domain -> текущий перцентиль (для сравнения на графике)
  var FONT = { family: "Inter, system-ui, sans-serif", size: 12, color: RL.cssVar("--ink-soft", "#43505a") };
  var GRID = RL.cssVar("--line-soft", "#e5e9ec");
  var NEUTRAL = RL.cssVar("--ink-faint", "#9aa6ad");

  function arrow(delta) {
    if (delta > 0) return '<span style="color:' + POS + '">▲ ' + delta + "</span>";
    if (delta < 0) return '<span style="color:' + NEG + '">▼ ' + -delta + "</span>";
    return '<span class="muted">= 0</span>';
  }

  function loadRegions() {
    return fetch("/api/regions/")
      .then(function (r) { return r.json(); })
      .then(function (rows) {
        rows.sort(function (a, b) {
          return (a.region_name || "").localeCompare(b.region_name || "");
        });
        regionSelect.innerHTML = rows
          .map(function (r) {
            return '<option value="' + r.okato + '">' + (r.region_name || r.okato) + "</option>";
          })
          .join("");
        if (rows.length) state.okato = rows[0].okato;
      });
  }

  function buildSliders() {
    slidersEl.innerHTML = DOMAINS.map(function (d) {
      var key = d[0];
      var p = presets[key] != null ? Math.round(presets[key]) : 50;
      return (
        '<div class="kpi"><div class="kpi-label">' + d[1] +
        ' — <strong id="sv-' + key + '">' + p + "</strong> " + gettext("перц.") + "</div>" +
        '<input type="range" class="s-slider" data-domain="' + key +
        '" min="0" max="100" step="1" value="' + p + '"></div>'
      );
    }).join("");
    slidersEl.querySelectorAll(".s-slider").forEach(function (el) {
      el.addEventListener("input", function () {
        document.getElementById("sv-" + el.getAttribute("data-domain")).textContent = el.value;
        drawScenario();
        scheduleScenario();
      });
    });
  }

  // Живой график сравнения: текущий перцентиль домена против целевого (положение ползунка).
  // Наглядно показывает, какой разрыв по каждому домену задаёт пользователь; перерисовывается
  // при каждом движении ползунка. Обновление через Plotly.react — без пересоздания графика.
  function drawScenario() {
    var el = document.getElementById("scenario-chart");
    if (!el || typeof Plotly === "undefined") return;
    var labels = [], cur = [], tgt = [];
    DOMAINS.forEach(function (d) {
      var key = d[0];
      var base = currentPct[key] != null ? Math.round(currentPct[key]) : 50;
      var sl = slidersEl.querySelector('.s-slider[data-domain="' + key + '"]');
      labels.push(d[1]);
      cur.push(base);
      tgt.push(sl ? Number(sl.value) : base);
    });
    Plotly.react(
      el,
      [
        { type: "bar", name: gettext("Текущий"), x: labels, y: cur, marker: { color: NEUTRAL },
          hovertemplate: "%{x}<br>" + gettext("текущий") + ": %{y}<extra></extra>" },
        { type: "bar", name: gettext("Целевой"), x: labels, y: tgt, marker: { color: POS },
          hovertemplate: "%{x}<br>" + gettext("целевой") + ": %{y}<extra></extra>" },
      ],
      { barmode: "group", font: FONT, height: 340,
        margin: { t: 34, r: 16, b: 90, l: 44 },
        paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
        legend: { orientation: "h", y: 1.12 },
        xaxis: { tickangle: -20, automargin: true },
        yaxis: { title: gettext("Перцентиль"), range: [0, 100], gridcolor: GRID } },
      { responsive: true }
    );
  }

  function overrides() {
    var out = {};
    slidersEl.querySelectorAll(".s-slider").forEach(function (el) {
      var key = el.getAttribute("data-domain");
      var preset = presets[key] != null ? Math.round(presets[key]) : null;
      if (String(el.value) !== String(preset)) out[key] = el.value; // только изменённые
    });
    return out;
  }

  function scenarioQuery(ov) {
    var parts = ["year=" + state.year, "okato=" + encodeURIComponent(state.okato)];
    Object.keys(ov).forEach(function (k) { parts.push("p_" + k + "=" + ov[k]); });
    return parts.join("&");
  }

  // Одноразовое применение целевых значений из ссылки — после того как слайдеры собраны
  // по пресетам региона (иначе значения перетрутся при перестройке слайдеров).
  var pendingOverrides = null;

  function readUrlState() {
    var p = new URLSearchParams(window.location.search);
    var ov = {};
    DOMAINS.forEach(function (d) {
      var v = p.get("p_" + d[0]);
      if (v !== null && v !== "") ov[d[0]] = v;
    });
    return { year: p.get("year"), okato: p.get("okato") || "", overrides: ov };
  }

  function writeUrlState() {
    if (!state.okato) return;
    var p = new URLSearchParams();
    p.set("year", state.year);
    p.set("okato", state.okato);
    var ov = overrides();
    Object.keys(ov).forEach(function (k) { p.set("p_" + k, ov[k]); });
    window.history.replaceState(null, "", window.location.pathname + "?" + p.toString());
  }

  // Применить целевые значения из ссылки к уже собранным слайдерам (значение + подпись).
  function applyPendingOverrides() {
    if (!pendingOverrides) return false;
    Object.keys(pendingOverrides).forEach(function (k) {
      var sl = slidersEl.querySelector('.s-slider[data-domain="' + k + '"]');
      if (!sl) return;
      sl.value = pendingOverrides[k];
      var lab = document.getElementById("sv-" + k);
      if (lab) lab.textContent = sl.value;
    });
    pendingOverrides = null;
    return true;
  }

  function renderSummary(data) {
    summaryEl.innerHTML =
      '<div class="kpi"><div class="kpi-label">' + gettext("Текущее место") +
      '</div><div class="num">' + data.baseline_rank +
      ' <span class="kpi-sub">' + gettext("из") + " " + data.of + "</span></div></div>" +
      '<div class="kpi"><div class="kpi-label">' + gettext("Сценарное место") +
      '</div><div class="num">' + data.scenario_rank + "</div></div>" +
      '<div class="kpi"><div class="kpi-label">' + gettext("Сдвиг") +
      '</div><div class="num">' + arrow(data.delta) + "</div></div>";
  }

  function domainLabel(key) {
    for (var i = 0; i < DOMAINS.length; i++) {
      if (DOMAINS[i][0] === key) return DOMAINS[i][1];
    }
    return key;
  }

  function renderHint(sensitivity) {
    var hintEl = document.getElementById("scenario-hint");
    if (!hintEl) return;
    if (!sensitivity || !sensitivity.length) { hintEl.innerHTML = ""; return; }
    var top = sensitivity[0];
    var text;
    if (top.gain > 0) {
      text =
        gettext("Наибольший подъём места даёт домен") + ' «' + domainLabel(top.domain) + '» — ' +
        gettext("до") + " +" + top.gain + " " + gettext("мест") + ".";
    } else {
      text = gettext("Регион уже занимает высокое место: подтягивание отдельного домена позицию не меняет.");
    }
    hintEl.innerHTML =
      '<div class="card"><p><strong>' + gettext("Подсказка") + ":</strong> " + text + "</p></div>";
  }

  var timer = null;
  function scheduleScenario() { clearTimeout(timer); timer = setTimeout(runScenario, 250); }

  function runScenario() {
    if (!state.okato) return;
    writeUrlState();
    fetch("/api/index/scenario/?" + scenarioQuery(overrides()))
      .then(function (r) {
        if (!r.ok) throw new Error(gettext("Ошибка расчёта") + " (" + r.status + ")");
        return r.json();
      })
      .then(renderSummary)
      .catch(function (e) {
        root.innerHTML = '<div class="shell"><p>' + RL.errText(e) + "</p></div>";
      });
  }

  function loadRegionState() {
    if (!state.okato) return;
    root.innerHTML = '<div class="shell"><p>' + gettext("Загрузка…") + "</p></div>";
    fetch("/api/index/scenario/?year=" + state.year + "&okato=" + encodeURIComponent(state.okato))
      .then(function (r) {
        if (!r.ok) throw new Error(gettext("Ошибка загрузки") + " (" + r.status + ")");
        return r.json();
      })
      .then(function (data) {
        presets = {};
        currentPct = {};
        DOMAINS.forEach(function (d) {
          var pct = data.current[d[0]] ? data.current[d[0]].percentile : 50;
          presets[d[0]] = pct;
          currentPct[d[0]] = pct;
        });
        buildSliders();
        var applied = applyPendingOverrides();
        renderSummary(data);
        renderHint(data.sensitivity);
        root.innerHTML =
          '<div class="card"><h3>' + gettext("Текущее и целевое положение по доменам") + "</h3>" +
          '<p class="chart-note">' +
          gettext("Столбцы «целевой» отражают положение ползунков, сводка сверху пересчитывает место в рейтинге. Учитываются только изменённые домены.") +
          '</p><div id="scenario-chart" class="chart"></div></div>';
        drawScenario();
        if (applied) runScenario(); // пересчитать сводку под целевые из ссылки
        else writeUrlState(); // свежий регион — зафиксировать year+okato в URL
      })
      .catch(function (e) {
        root.innerHTML = '<div class="shell"><p>' + RL.errText(e) + "</p></div>";
      });
  }

  regionSelect.addEventListener("change", function () {
    state.okato = regionSelect.value;
    loadRegionState();
  });
  var yearSlider = document.getElementById("year-slider");
  if (yearSlider) {
    yearSlider.addEventListener("input", function (e) {
      state.year = Number(e.target.value);
      document.getElementById("year-label").textContent = e.target.value;
      loadRegionState();
    });
  }
  document.getElementById("reset-scenario").addEventListener("click", function () {
    buildSliders();
    drawScenario();
    runScenario();
  });

  var initialState = readUrlState();
  if (initialState.year && /^\d{4}$/.test(initialState.year)) {
    state.year = Math.min(2024, Math.max(2010, parseInt(initialState.year, 10)));
    RL.syncYearControl(state.year);
  }
  if (Object.keys(initialState.overrides).length) pendingOverrides = initialState.overrides;
  RL.wireCopyLink("scenario-copy-link");

  loadRegions()
    .then(function () {
      // Регион из ссылки — если такой есть в списке; иначе остаётся первый по алфавиту.
      if (initialState.okato && regionSelect.querySelector('option[value="' + initialState.okato + '"]')) {
        state.okato = initialState.okato;
      }
      regionSelect.value = state.okato;
      loadRegionState();
    })
    .catch(function (e) {
      root.innerHTML = '<div class="shell"><p>' + RL.errText(e) + "</p></div>";
    });
})();
