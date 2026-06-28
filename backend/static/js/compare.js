/* RegionLens — сравнение регионов (Ф7, модуль 4).
   Выбор 2–3 регионов + год → /api/compare/?year=&okato=..&okato=.. → сгруппированные бары
   по доменам (gap-анализ) + сводная таблица (индекс, тип). Списки регионов — из /api/regions/. */

(function () {
  "use strict";

  if (typeof Plotly === "undefined") return;
  var go = document.getElementById("cmp-go");
  if (!go) return;

  var DOMAINS = [
    ["economy", "Экономика"],
    ["income", "Доходы"],
    ["demography", "Демография"],
    ["labor", "Труд"],
    ["infrastructure", "Инфраструктура"],
    ["health_edu", "Здоровье/обр."],
  ];
  var PALETTE = ["#1f6f63", "#b4532a", "#3b6ea5"];
  var INK = RL.cssVar("--ink", "#1b2430"), GRID = RL.cssVar("--line-soft", "#e9e3d6");
  var state = { year: 2024 };
  var selects = ["cmp-1", "cmp-2", "cmp-3"].map(function (id) { return document.getElementById(id); });
  var msg = document.getElementById("compare-msg");

  function setMsg(t) { if (msg) msg.textContent = t || ""; }

  // Заполнить выпадающие списки регионами
  fetch("/api/regions/")
    .then(function (r) { return r.json(); })
    .then(function (rows) {
      rows.sort(function (a, b) { return (a.region_name || "").localeCompare(b.region_name || "", "ru"); });
      selects.forEach(function (sel, i) {
        var opts = i === 2 ? '<option value="">— нет —</option>' : "";
        opts += rows
          .map(function (r) { return '<option value="' + r.okato + '">' + r.region_name + "</option>"; })
          .join("");
        sel.innerHTML = opts;
      });
      if (rows.length >= 2) {
        selects[0].value = rows[0].okato;
        selects[1].value = rows[1].okato;
      }
      run();
    })
    .catch(function () { setMsg("Не удалось загрузить список регионов."); });

  function selectedOkatos() {
    var seen = {}, out = [];
    selects.forEach(function (s) {
      var v = s.value;
      if (v && !seen[v]) { seen[v] = 1; out.push(v); }
    });
    return out;
  }

  function run() {
    var okatos = selectedOkatos();
    if (okatos.length < 2) { setMsg("Выберите минимум 2 разных региона."); return; }
    setMsg("");
    var qs = new URLSearchParams();
    qs.set("year", state.year);
    okatos.forEach(function (o) { qs.append("okato", o); });
    fetch("/api/compare/?" + qs.toString())
      .then(function (r) {
        if (!r.ok) throw new Error("Ошибка сравнения (" + r.status + ")");
        return r.json();
      })
      .then(render)
      .catch(function (e) { setMsg(RL.errText(e)); });
  }

  function render(rows) {
    if (!rows.length) { setMsg("Нет данных за выбранный год."); return; }
    var traces = rows.map(function (r, i) {
      return {
        type: "bar",
        name: r.region_name || r.okato,
        x: DOMAINS.map(function (d) { return d[1]; }),
        y: DOMAINS.map(function (d) { return r[d[0]]; }),
        marker: { color: PALETTE[i % PALETTE.length] },
        hovertemplate: "%{x}: %{y:.2f}<extra>" + (r.region_name || r.okato) + "</extra>",
      };
    });
    Plotly.newPlot(
      "chart-compare",
      traces,
      {
        barmode: "group",
        font: { family: "Golos Text, system-ui, sans-serif", color: INK, size: 13 },
        margin: { t: 20, b: 60, l: 50, r: 20 },
        height: 380,
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        legend: { orientation: "h", y: -0.18 },
        xaxis: { tickangle: -20 },
        yaxis: { title: "доменный балл (z)", zeroline: true, zerolinecolor: RL.cssVar("--line", "#b9c2cb"), gridcolor: GRID },
      },
      { responsive: true, displayModeBar: false }
    );

    var head = "<tr><th>Регион</th><th class='num'>Индекс</th><th>Тип</th></tr>";
    var body = rows
      .slice()
      .sort(function (a, b) { return (b.total_score || 0) - (a.total_score || 0); })
      .map(function (r) {
        return (
          "<tr data-okato='" + r.okato + "'><td>" + (r.region_name || r.okato) + "</td>" +
          "<td class='num'><strong>" + (r.total_score == null ? "—" : r.total_score.toFixed(1)) + "</strong></td>" +
          "<td>" + (r.cluster_label || "—") + "</td></tr>"
        );
      })
      .join("");
    var el = document.getElementById("compare-summary");
    el.innerHTML =
      "<h3>Сводка</h3><div class='table-wrap'><table class='table'><thead>" +
      head + "</thead><tbody>" + body + "</tbody></table></div>";
    el.querySelectorAll("tr[data-okato]").forEach(function (tr) {
      tr.addEventListener("click", function () {
        window.location.href = "/regions/" + tr.dataset.okato + "/?year=" + state.year;
      });
    });
  }

  go.addEventListener("click", run);
  var slider = document.getElementById("year-slider");
  var label = document.getElementById("year-label");
  if (slider) {
    slider.addEventListener("input", function () {
      state.year = parseInt(slider.value, 10);
      if (label) label.textContent = state.year;
    });
    slider.addEventListener("change", run);
  }
})();
