/* RegionLens — страница аномалий (Ф9, модуль 4). Доступ — роль analyst.
   Карта пространственных выбросов за год (IsolationForest) + списки резких структурных
   сдвигов рядов и кандидатов смены методологии (A3). Всё это диагностика данных —
   находки для проверки аналитиком, НЕ утверждение о причинах. Данные — /api/anomalies/. */

(function () {
  "use strict";

  var GEOJSON_URL = "/static/geo/regions.geojson";
  var API = "/api/anomalies/";
  var FLAG = "#b4532a"; // помеченный выброс
  var CALM = "#cfe3dc"; // в норме
  var NODATA = RL.cssVar("--map-nodata", "#dcdcdc");

  var root = document.getElementById("map");
  var state = { year: RL.prefYear(parseInt((root && root.dataset.year) || "2020", 10)) };
  RL.syncYearControl(state.year);
  var geo = null;

  // ── Списки (не зависят от года): структурные сдвиги и кандидаты методологии ──
  loadList("structural_break", "breaks-list", renderBreak);
  loadList("methodology_change", "methodology-list", renderMethodology);

  function loadList(kind, elId, renderRow) {
    var box = document.getElementById(elId);
    if (!box) return;
    fetch(API + "?kind=" + kind)
      .then(function (r) {
        return r.ok ? r.json() : [];
      })
      .then(function (rows) {
        box.innerHTML = "";
        if (!rows.length) {
          box.appendChild(note(gettext("Ничего не найдено.")));
          return;
        }
        rows.slice(0, 50).forEach(function (d) {
          box.appendChild(renderRow(d));
        });
        if (rows.length > 50) {
          box.appendChild(note(interpolate(gettext("…и ещё %(n)s (показаны первые 50)."), { n: rows.length - 50 }, true)));
        }
      })
      .catch(function () {
        box.innerHTML = "";
        box.appendChild(note(gettext("Не удалось загрузить данные.")));
      });
  }

  function span(cls, text) {
    var s = document.createElement("span");
    s.className = cls;
    s.textContent = text;
    return s;
  }

  function note(text) {
    var li = document.createElement("li");
    li.className = "anom-empty";
    li.textContent = text;
    return li;
  }

  function renderBreak(d) {
    var li = document.createElement("li");
    li.className = "anom-item";
    var a = document.createElement("a");
    a.className = "anom-name";
    a.href = "/regions/" + encodeURIComponent(d.okato) + "/?year=" + d.year;
    a.textContent = d.region_name || d.okato;
    var mag = span("anom-val", "Δ " + Number(d.score).toFixed(1));
    mag.title = gettext("величина сдвига уровня (в единицах показателя)");
    li.appendChild(span("anom-year", d.year));
    li.appendChild(a);
    li.appendChild(span("anom-metric", d.metric_name || gettext("метрика") + " " + d.metric_id));
    li.appendChild(mag);
    return li;
  }

  function renderMethodology(d) {
    var li = document.createElement("li");
    li.className = "anom-item";
    var frac = span("anom-val", Math.round(Number(d.score) * 100) + "%");
    frac.title = gettext("доля регионов с синхронным сдвигом (кандидат, не вывод)");
    li.appendChild(span("anom-year", d.year));
    li.appendChild(span("anom-name", d.metric_name || gettext("метрика") + " " + d.metric_id));
    li.appendChild(frac);
    return li;
  }

  // ── Карта пространственных выбросов (зависит от года) ──
  if (!root || typeof maplibregl === "undefined") return;

  var map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      sources: {},
      layers: [{ id: "bg", type: "background", paint: { "background-color": RL.cssVar("--map-bg", "#eaf0f1") } }],
    },
    center: [99, 66],
    zoom: 2,
    minZoom: 1.6,
    maxBounds: [[5, 25], [205, 86]],
    renderWorldCopies: false,
    attributionControl: false,
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  var popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });

  map.on("load", function () {
    fetch(GEOJSON_URL)
      .then(function (r) {
        if (!r.ok) throw new Error("geojson " + r.status);
        return r.json();
      })
      .then(function (fc) {
        geo = window.RL && RL.unwrapGeojson ? RL.unwrapGeojson(fc) : fc;
        map.addSource("regions", { type: "geojson", data: geo });
        map.addLayer({
          id: "fill",
          type: "fill",
          source: "regions",
          paint: { "fill-color": NODATA, "fill-opacity": 0.85 },
        });
        map.addLayer({
          id: "line",
          type: "line",
          source: "regions",
          paint: { "line-color": RL.cssVar("--map-line", "#ffffff"), "line-width": 0.6 },
        });
        wire();
        updateMap();
        if (window.RL && RL.fitToData) RL.fitToData(map, geo, 18);
        if (window.RL && RL.softenZoomControls) RL.softenZoomControls(map, 0.5);
        if (window.RL && RL.makeLegendCollapsible) {
          RL.makeLegendCollapsible(document.getElementById("map-legend"));
        }
        if (window.RL && RL.onTheme) {
          RL.onTheme(function () {
            try {
              if (!map.getLayer || !map.getLayer("bg")) return;
              map.setPaintProperty("bg", "background-color", RL.cssVar("--map-bg", "#eaf0f1"));
              if (map.getLayer("line"))
                map.setPaintProperty("line", "line-color", RL.cssVar("--map-line", "#ffffff"));
              NODATA = RL.cssVar("--map-nodata", "#dcdcdc");
            } catch (e) {}
          });
        }
      })
      .catch(function () {
        root.innerHTML =
          '<div class="shell"><p>' +
          gettext(
            "Не удалось загрузить границы регионов. Сформируйте <code>static/geo/regions.geojson</code> (см. README)."
          ) +
          "</p></div>";
      });
  });

  function updateMap() {
    fetch(API + "?kind=spatial&year=" + encodeURIComponent(state.year))
      .then(function (r) {
        return r.ok ? r.json() : [];
      })
      .then(function (rows) {
        var by = {};
        rows.forEach(function (d) {
          by[d.okato] = d;
        });
        geo.features.forEach(function (f) {
          var d = by[f.properties.okato];
          f.properties.has = d ? 1 : 0;
          f.properties.flagged = d && d.is_anomaly ? 1 : 0;
          f.properties.score = d ? Number(d.score).toFixed(3) : "—";
        });
        map.getSource("regions").setData(geo);
        map.setPaintProperty("fill", "fill-color", [
          "case",
          ["==", ["get", "flagged"], 1], FLAG,
          ["==", ["get", "has"], 1], CALM,
          NODATA,
        ]);
        renderLegend();
      });
  }

  function renderLegend() {
    var el = document.getElementById("map-legend");
    if (el && el.querySelector(".map-legend-body")) el = el.querySelector(".map-legend-body");
    if (!el) return;
    el.innerHTML =
      "<div class='legend-title'>" + gettext("Пространственные выбросы") + "</div>" +
      "<div class='legend-row'><span class='swatch' style='background:" +
      FLAG +
      "'></span>" + gettext("помеченный выброс") + "</div>" +
      "<div class='legend-row'><span class='swatch' style='background:" +
      CALM +
      "'></span>" + gettext("в норме") + "</div>" +
      "<div class='legend-note'>" + gettext("Нетипичность профиля региона в этот год (IsolationForest).") + "</div>";
  }

  function wire() {
    RL.attachMapHover(map, {
      popup: popup,
      html: function (p) {
        return (
          "<strong>" + (p.name || p.okato) + "</strong><br>" +
          (p.flagged == 1 ? gettext("выброс") + " · " : gettext("в норме") + " · ") +
          gettext("оценка") + ": " + (p.score || "—")
        );
      },
    });
    map.on("click", "fill", function (e) {
      var okato = e.features[0].properties.okato;
      if (okato) window.location.href = "/regions/" + okato + "/?year=" + state.year;
    });
  }

  var slider = document.getElementById("year-slider");
  var yearLabel = document.getElementById("year-label");
  var spYear = document.getElementById("sp-year");
  if (slider) {
    slider.value = state.year;
    if (yearLabel) yearLabel.textContent = state.year;
    if (spYear) spYear.textContent = state.year;
    slider.addEventListener("input", function () {
      state.year = parseInt(slider.value, 10);
      if (yearLabel) yearLabel.textContent = state.year;
      if (spYear) spYear.textContent = state.year;
    });
    slider.addEventListener("change", function () {
      if (geo) updateMap();
    });
  }
})();
