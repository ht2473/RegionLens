/* RegionLens — дашборд региона (Ф7, модуль 3).
   Тянет /api/regions/<okato>/?year= и /api/transitions/?okato= и рисует:
   KPI (индекс+B4-дельта, ранг, тип+типичность, траектория), радар профиля по доменам,
   диверг-бары изменения по доменам (B4), SHAP-вклад, шаговую траекторию типа по годам.
   Формулировки: B4 — арифметика по доменам; SHAP — объяснение классификатора, не причинность. */

(function () {
  "use strict";

  var root = document.getElementById("region-root");
  if (!root || typeof Plotly === "undefined") return;

  var OKATO = root.dataset.okato;
  var initYear = RL.prefYear(parseInt(root.dataset.year || "2024", 10));
  var state = { year: Math.min(2024, Math.max(2010, initYear)) };
  RL.syncYearControl(state.year);

  function writeUrlState() {
    var p = new URLSearchParams(window.location.search);
    p.set("year", state.year);
    window.history.replaceState(null, "", window.location.pathname + "?" + p.toString());
  }

  var DOMAIN_RU = {
    economy: gettext("Экономика"),
    income: gettext("Доходы"),
    demography: gettext("Демография"),
    labor: gettext("Труд"),
    infrastructure: gettext("Инфраструктура"),
    health_edu: gettext("Здоровье/образование"),
  };
  var DOMAIN_ORDER = ["economy", "income", "demography", "labor", "infrastructure", "health_edu"];
  var TRAJ_RU = {
    stable_high: gettext("устойчиво высокий"),
    stable_mid: gettext("устойчиво средний"),
    stable_low: gettext("устойчиво низкий"),
    converger: gettext("догоняющий"),
    diverger: gettext("отстающий"),
    leapfrogger: gettext("рывок"),
    volatile: gettext("волатильный"),
    drifting: gettext("дрейфующий"),
  };
  var POS = "#1f6f63",
    NEG = "#b4532a",
    INK = RL.cssVar("--ink", "#1b2430"),
    GRID = RL.cssVar("--line-soft", "#e9e3d6"),
    RADARGRID = RL.cssVar("--radar-grid", "#c2b8a0");
  var FONT = { family: "Golos Text, system-ui, sans-serif", color: INK, size: 13 };
  var CFG = { responsive: true, displayModeBar: false };

  function fmt(x, d) { return x == null ? "—" : Number(x).toFixed(d == null ? 1 : d); }

  function show(id, on) { document.getElementById(id).style.display = on ? "" : "none"; }

  function fail(msg) {
    var e = document.getElementById("region-error");
    e.textContent = msg;
    show("region-error", true);
    show("region-body", false);
  }

  function load() {
    var u = "/api/regions/" + encodeURIComponent(OKATO) + "/?year=" + state.year;
    var tw = "/api/regions/" + encodeURIComponent(OKATO) + "/twins/?year=" + state.year;
    var dc = "/api/decomposition/?okato=" + encodeURIComponent(OKATO) + "&year=" + state.year;
    Promise.all([
      fetch(u),
      fetch("/api/transitions/?okato=" + encodeURIComponent(OKATO)),
      fetch(tw),
      fetch(dc),
    ])
      .then(function (rs) {
        if (rs[0].status === 404) throw new Error(gettext("Регион не найден или нет данных за год."));
        if (!rs[0].ok) throw new Error(gettext("Ошибка загрузки") + " (" + rs[0].status + ").");
        return Promise.all([
          rs[0].json(),
          rs[1].ok ? rs[1].json() : [],
          rs[2].ok ? rs[2].json() : [],
          rs[3].ok ? rs[3].json() : [],
        ]);
      })
      .then(function (out) {
        show("region-error", false);
        show("region-body", true);
        render(out[0], out[1], out[2], out[3]);
      })
      .catch(function (err) { fail(RL.errText(err)); });
  }

  function render(d, transitions, twins, decomp) {
    // Заголовок
    document.getElementById("region-title").textContent = d.region_name || OKATO;
    var typeLabel = d.cluster ? d.cluster.cluster_label : "—";
    document.getElementById("region-sub").textContent =
      (d.federal_district ? RL.localizeFederalDistrict(d.federal_district) + " · " : "") + gettext("тип") + ": " + typeLabel;

    // KPI
    document.getElementById("kpi-total").textContent = fmt(d.index.total_score);
    var dl = document.getElementById("kpi-delta");
    if (d.index.total_delta == null) {
      dl.textContent = gettext("нет пред. года");
      dl.style.color = "#8a96a1";
    } else {
      var up = d.index.total_delta >= 0;
      dl.textContent = (up ? "▲ +" : "▼ ") + fmt(d.index.total_delta) + " " + gettext("к пред. году");
      dl.style.color = up ? POS : NEG;
    }
    document.getElementById("kpi-rank").textContent = d.rank ? d.rank.rank : "—";
    document.getElementById("kpi-rank-sub").textContent = d.rank ? gettext("из") + " " + d.rank.of : "";
    document.getElementById("kpi-type").textContent = typeLabel;
    document.getElementById("kpi-typicality").textContent = d.cluster
      ? gettext("удалённость от центра типа") + ": " + fmt(d.cluster.distance_to_centroid, 2)
      : "";
    var traj = (transitions[0] && transitions[0].trajectory_type) || null;
    document.getElementById("kpi-traj").textContent = traj ? TRAJ_RU[traj] || traj : "—";

    drawRadar(d.index.domains);
    drawB4(d.index.domains);
    drawShap(d.shap_top || []);
    drawTrajectory(transitions);
    drawTwins(twins || []);
    drawDecomp(decomp || []);
  }

  function drawRadar(domains) {
    var theta = DOMAIN_ORDER.map(function (k) { return DOMAIN_RU[k]; });
    var byd = {};
    domains.forEach(function (x) { byd[x.domain] = x.score; });
    var r = DOMAIN_ORDER.map(function (k) { return byd[k] == null ? 0 : byd[k]; });
    var vals = r.concat([0]);
    var lo = Math.min.apply(null, vals) - 0.5, hi = Math.max.apply(null, vals) + 0.5;
    Plotly.newPlot(
      "chart-radar",
      [
        { type: "scatterpolar", r: DOMAIN_ORDER.map(function () { return 0; }).concat([0]),
          theta: theta.concat([theta[0]]), mode: "lines",
          line: { color: RADARGRID, dash: "dot", width: 1.6 }, name: gettext("среднее РФ"), hoverinfo: "skip" },
        { type: "scatterpolar", r: r.concat([r[0]]), theta: theta.concat([theta[0]]),
          fill: "toself", fillcolor: "rgba(31,111,99,0.18)",
          line: { color: POS, width: 2 }, name: gettext("регион") },
      ],
      { polar: { bgcolor: "rgba(0,0,0,0)",
          radialaxis: { range: [lo, hi], gridcolor: RADARGRID, gridwidth: 1.2, tickfont: { size: 10 } },
          angularaxis: { gridcolor: RADARGRID, gridwidth: 1.2, tickfont: { size: 11 } } },
        showlegend: false, font: FONT, margin: { t: 20, b: 20, l: 40, r: 40 },
        height: 300, paper_bgcolor: "rgba(0,0,0,0)" },
      CFG
    );
  }

  function divergeBars(id, labels, values, opts) {
    opts = opts || {};
    var colors = values.map(function (v) { return v >= 0 ? POS : NEG; });
    Plotly.newPlot(
      id,
      [{ type: "bar", orientation: "h", x: values, y: labels, marker: { color: colors },
        hovertemplate: "%{y}: %{x:.2f}<extra></extra>" }],
      { font: FONT, margin: { t: 10, b: 30, l: opts.left || 130, r: 20 },
        height: opts.height || 300, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
        xaxis: { zeroline: true, zerolinecolor: RL.cssVar("--line", "#b9c2cb"), gridcolor: GRID },
        yaxis: { automargin: true } },
      CFG
    );
  }

  function drawB4(domains) {
    var withDelta = domains.filter(function (x) { return x.delta != null; });
    if (!withDelta.length) {
      document.getElementById("chart-b4").innerHTML =
        '<p class="chart-note">' + gettext("Нет предыдущего года для сравнения.") + "</p>";
      return;
    }
    var labels = withDelta.map(function (x) { return DOMAIN_RU[x.domain] || x.domain; });
    var values = withDelta.map(function (x) { return x.delta; });
    divergeBars("chart-b4", labels, values);
  }

  function drawDecomp(rows) {
    if (!rows.length) {
      document.getElementById("chart-decomp").innerHTML =
        '<p class="chart-note">' + gettext("Нет предыдущего года для разложения индекса.") + "</p>";
      return;
    }
    var labels = rows.map(function (x) { return DOMAIN_RU[x.domain] || x.domain; });
    var values = rows.map(function (x) { return x.contribution; });
    divergeBars("chart-decomp", labels, values);
  }

  function drawShap(shap) {
    if (!shap.length) {
      document.getElementById("chart-shap").innerHTML =
        '<p class="chart-note">' + gettext("Нет данных SHAP за год.") + "</p>";
      return;
    }
    var ordered = shap.slice().reverse(); // крупнейший |вклад| — сверху
    divergeBars(
      "chart-shap",
      ordered.map(function (s) { return s.metric_name || "metric " + s.metric_id; }),
      ordered.map(function (s) { return s.shap_value; }),
      { left: 240, height: 340 }
    );
  }

  function drawTrajectory(transitions) {
    if (!transitions.length) {
      document.getElementById("chart-traj").innerHTML =
        '<p class="chart-note">' + gettext("Нет данных о переходах.") + "</p>";
      return;
    }
    var sorted = transitions.slice().sort(function (a, b) { return a.year_from - b.year_from; });
    var years = [sorted[0].year_from];
    var clusters = [sorted[0].cluster_from];
    sorted.forEach(function (t) { years.push(t.year_to); clusters.push(t.cluster_to); });
    Plotly.newPlot(
      "chart-traj",
      [{ type: "scatter", mode: "lines+markers", x: years, y: clusters, line: { shape: "hv", color: POS, width: 2 },
        marker: { size: 7, color: POS }, hovertemplate: "%{x}: " + gettext("тип") + " %{y}<extra></extra>" }],
      { font: FONT, margin: { t: 10, b: 30, l: 40, r: 20 }, height: 300,
        paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
        xaxis: { gridcolor: GRID, dtick: 2 },
        yaxis: { title: gettext("тип"), dtick: 1, gridcolor: GRID, zeroline: false } },
      CFG
    );
  }

  function drawTwins(twins) {
    var box = document.getElementById("twins-list");
    if (!box) return;
    box.innerHTML = "";
    if (!twins.length) {
      var empty = document.createElement("li");
      empty.className = "twins-empty";
      empty.textContent = gettext("Нет данных о двойниках за выбранный год.");
      box.appendChild(empty);
      return;
    }
    twins.forEach(function (t) {
      var li = document.createElement("li");
      li.className = "twin-item";

      var rank = document.createElement("span");
      rank.className = "twin-rank";
      rank.textContent = t.rank;

      var a = document.createElement("a");
      a.className = "twin-name";
      a.href = "/regions/" + encodeURIComponent(t.twin_okato) + "/?year=" + state.year;
      a.textContent = t.region_name || t.twin_okato;

      var fo = document.createElement("span");
      fo.className = "twin-fo";
      fo.textContent = RL.localizeFederalDistrict(t.federal_district) || "";

      var sim = document.createElement("span");
      sim.className = "twin-sim";
      sim.title = gettext("косинусная близость профиля z-оценок (1.00 — идентичный профиль)");
      sim.textContent = fmt(t.similarity, 2);

      li.appendChild(rank);
      li.appendChild(a);
      li.appendChild(fo);
      li.appendChild(sim);
      box.appendChild(li);
    });
  }

  // Ползунок года (синхронизирован с URL: вид восстановим и шарится)
  var slider = document.getElementById("year-slider");
  var label = document.getElementById("year-label");
  if (slider) {
    slider.value = state.year;
    if (label) label.textContent = state.year;
    slider.addEventListener("input", function () {
      state.year = parseInt(slider.value, 10);
      if (label) label.textContent = state.year;
    });
    slider.addEventListener("change", function () {
      writeUrlState();
      load();
    });
  }

  var copyBtn = document.getElementById("region-copy-link");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      var flash = function () {
        var prev = copyBtn.textContent;
        copyBtn.textContent = gettext("Ссылка скопирована");
        setTimeout(function () {
          copyBtn.textContent = prev;
        }, 1500);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(window.location.href).then(flash, flash);
      } else {
        flash();
      }
    });
  }

  writeUrlState();
  load();

  // При смене темы перекраска пунктира «среднее РФ» на радаре — это цвет трейса (0),
  // relayout его не трогает, поэтому точечно через restyle. Регистрируется один раз.
  if (window.RL && RL.onTheme) {
    RL.onTheme(function () {
      var el = document.getElementById("chart-radar");
      if (el && el._fullLayout && typeof Plotly !== "undefined") {
        try {
          Plotly.restyle(el, { "line.color": RL.cssVar("--radar-grid", "#c2b8a0") }, [0]);
        } catch (e) {}
      }
    });
  }
})();
