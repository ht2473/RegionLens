/* RegionLens — конвергенция регионов (поток B, научное ядро).
   σ-сходимость: разброс композитного индекса по регионам во времени (/api/index/dispersion/).
   Переключатели меры разброса и схемы весов; авто-вывод о направлении (сходимость/расхождение). */

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
  var data = null;

  function shell(msg) {
    $chart.innerHTML = '<div class="shell"><p>' + msg + "</p></div>";
  }

  function render() {
    if (!data) return;
    var scheme = $scheme.value;
    var measure = $measure.value;
    var pts = data
      .filter(function (r) { return r.weighting_scheme === scheme && r[measure] != null; })
      .sort(function (a, b) { return a.year - b.year; });
    if (!pts.length) {
      shell("Нет данных для выбранной схемы.");
      $readout.textContent = "";
      return;
    }
    var years = pts.map(function (p) { return p.year; });
    var vals = pts.map(function (p) { return p[measure]; });
    $chart.innerHTML = ""; // убрать «Загрузка…»/старый график, иначе Plotly дорисует поверх
    Plotly.newPlot(
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

  $measure.addEventListener("change", render);
  $scheme.addEventListener("change", render);

  fetch("/api/index/dispersion/")
    .then(function (r) {
      if (!r.ok) throw new Error("Ошибка загрузки (" + r.status + ")");
      return r.json();
    })
    .then(function (rows) {
      data = rows;
      render();
    })
    .catch(function (e) { shell(RL.errText(e)); });
})();
