/* RegionLens — пространственная автокорреляция индекса: глобальный Moran's I и карта LISA.
   Карту строит общая фабрика RL.createRegionMap; кластеры LISA (HH/LL/HL/LH) красим по
   квадранту из /api/spatial/lisa/, глобальный индекс со значимостью — из /api/spatial/moran/. */
(function () {
  "use strict";
  var root = document.getElementById("map");
  if (!root || typeof maplibregl === "undefined") return;

  var GEOJSON_URL = "/static/geo/regions.geojson";
  // Палитра квадрантов LISA: кластеры HH/LL (регион и соседи заодно), выбросы HL/LH, ns — серый.
  var COLORS = { HH: "#c0392b", LL: "#2c6fbb", HL: "#e08e45", LH: "#8fb8de", ns: "#dcdcdc" };
  var LABELS = {
    HH: gettext("Высокий среди высоких"),
    LL: gettext("Низкий среди низких"),
    HL: gettext("Высокий среди низких"),
    LH: gettext("Низкий среди высоких"),
    ns: gettext("Незначимо"),
  };

  var state = { year: RL.prefYear(2024), scheme: RL.prefScheme("equal") };
  RL.syncYearControl(state.year);

  var geo = null;
  var handle = RL.createRegionMap({
    container: "map",
    legend: "#map-legend",
    geojsonUrl: GEOJSON_URL,
    onReady: function (ctx) {
      geo = ctx.geo;
      wire();
      update();
    },
    onError: function () {
      root.innerHTML =
        '<div class="shell"><p>' + gettext("Не удалось загрузить границы регионов.") + "</p></div>";
    },
  });
  if (!handle) return;
  var map = handle.map;
  var popup = handle.popup;

  function renderGlobal(g) {
    var box = document.getElementById("moran-global");
    if (!box) return;
    if (!g) {
      box.innerHTML =
        '<p class="chart-note">' +
        gettext("Пространственная статистика не посчитана. Запустите конвейер: python -m pipeline.run_all --only spatial.") +
        "</p>";
      return;
    }
    var i = Number(g.morans_i);
    var p = Number(g.p_value);
    var significant = p < 0.05;
    var verdict;
    if (!significant) {
      verdict = gettext("автокорреляция незначима — пространственной структуры не видно");
    } else if (i > 0) {
      verdict = gettext("значимая положительная автокорреляция — соседние регионы похожи по индексу");
    } else {
      verdict = gettext("значимая отрицательная автокорреляция — соседи контрастны (шахматный узор)");
    }
    box.innerHTML =
      '<div class="kpi-row">' +
      '<div class="kpi"><span class="kpi-label">Moran\u2019s I</span><span class="kpi-value">' +
      i.toFixed(3) + "</span></div>" +
      '<div class="kpi"><span class="kpi-label">' + gettext("Ожидание E[I]") + '</span><span class="kpi-value">' +
      Number(g.expected_i).toFixed(3) + "</span></div>" +
      '<div class="kpi"><span class="kpi-label">' + gettext("p-значение") + '</span><span class="kpi-value">' +
      p.toFixed(3) + "</span></div>" +
      '<div class="kpi"><span class="kpi-label">' + gettext("Регионов") + '</span><span class="kpi-value">' +
      g.n_regions + "</span></div>" +
      "</div><p class=\"chart-note\">" + verdict + " (" + gettext("перестановочный тест, 999") + ").</p>";
  }

  function renderLegend() {
    var el = document.getElementById("map-legend");
    if (el && el.querySelector(".map-legend-body")) el = el.querySelector(".map-legend-body");
    if (!el) return;
    var order = ["HH", "LL", "HL", "LH", "ns"];
    var rows = order
      .map(function (q) {
        return (
          "<div class='legend-row'><span class='swatch' style='background:" +
          COLORS[q] + "'></span>" + LABELS[q] + "</div>"
        );
      })
      .join("");
    el.innerHTML =
      "<div class='legend-title'>" + gettext("Кластеры LISA") + "</div>" + rows +
      "<div class='legend-note'>" +
      gettext("Локальный индекс Морана: значимые (p<0.05) пространственные кластеры и выбросы.") +
      "</div>";
  }

  function update() {
    document.getElementById("sp-year").textContent = state.year;
    var qs = "?year=" + encodeURIComponent(state.year) + "&scheme=" + encodeURIComponent(state.scheme);
    Promise.all([
      fetch("/api/spatial/moran/" + qs),
      fetch("/api/spatial/lisa/" + qs),
    ])
      .then(function (rs) {
        return Promise.all([rs[0].ok ? rs[0].json() : null, rs[1].ok ? rs[1].json() : []]);
      })
      .then(function (out) {
        renderGlobal(out[0]);
        var by = {};
        out[1].forEach(function (d) {
          by[d.okato] = d;
        });
        geo.features.forEach(function (f) {
          var d = by[f.properties.okato];
          f.properties.quadrant = d ? d.quadrant : "ns";
          f.properties.local_i = d && d.local_i != null ? Number(d.local_i).toFixed(3) : "—";
        });
        map.getSource("regions").setData(geo);
        map.setPaintProperty("fill", "fill-color", [
          "match",
          ["get", "quadrant"],
          "HH", COLORS.HH,
          "LL", COLORS.LL,
          "HL", COLORS.HL,
          "LH", COLORS.LH,
          COLORS.ns,
        ]);
        renderLegend();
      });
  }

  function wire() {
    RL.attachMapHover(map, {
      popup: popup,
      html: function (p) {
        var q = p.quadrant || "ns";
        return (
          "<strong>" + (p.name || p.okato) + "</strong><br>" +
          (LABELS[q] || q) + "<br>" +
          gettext("Локальный I") + ": " + (p.local_i != null ? p.local_i : "—")
        );
      },
    });
    map.on("click", "fill", function (e) {
      var okato = e.features[0].properties.okato;
      if (okato) window.location.href = "/regions/" + encodeURIComponent(okato) + "/";
    });
  }

  var yearSlider = document.getElementById("year-slider");
  if (yearSlider) {
    yearSlider.addEventListener("input", function (e) {
      state.year = Number(e.target.value);
      document.getElementById("year-label").textContent = e.target.value;
      if (geo) update();
    });
  }
  var schemeSel = document.getElementById("scheme-select");
  if (schemeSel) {
    schemeSel.value = state.scheme;
    schemeSel.addEventListener("change", function (e) {
      state.scheme = e.target.value;
      if (geo) update();
    });
  }
})();
