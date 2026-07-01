/* RegionLens — карта (Ф7, модуль 2).
   Хороплет субъектов РФ без внешних тайлов: рисуем только полигоны из
   /static/geo/regions.geojson (ключ okato), раскраска — по /api/geo/layer/.
   measure=cluster: цвет по типу + прозрачность по типичности (A1, distance_to_centroid —
   чем типичнее регион, тем плотнее заливка; это НЕ вероятность смены типа).
   measure=index: последовательная шкала 0–100. */

(function () {
  "use strict";

  var GEOJSON_URL = "/static/geo/regions.geojson";
  var API = "/api/geo/layer/";
  var CLUSTER_COLORS = ["#c46a3f", "#1f6f63", "#3b6ea5", "#8a6fab", "#b0a44e"]; // по cluster_id
  var NODATA = RL.cssVar("--map-nodata", "#dcdcdc");

  var root = document.getElementById("map");
  if (!root || typeof maplibregl === "undefined") return;

  // ── Deep-link: состояние карты (мера + год) кодируется в URL — вид восстановим и шарится ──
  var MEASURES = ["cluster", "index"];
  var slider = document.getElementById("year-slider");
  var yearLabel = document.getElementById("year-label");
  var yMin = slider ? parseInt(slider.min, 10) || 2010 : 2010;
  var yMax = slider ? parseInt(slider.max, 10) || 2024 : 2024;

  function readUrlState() {
    var p = new URLSearchParams(window.location.search);
    var y = parseInt(p.get("year") || root.dataset.year || "2020", 10);
    if (isNaN(y)) y = parseInt(root.dataset.year || "2020", 10);
    var m = p.get("measure");
    return {
      year: Math.min(yMax, Math.max(yMin, y)),
      measure: MEASURES.indexOf(m) === -1 ? "cluster" : m,
    };
  }

  function writeUrlState() {
    var p = new URLSearchParams(window.location.search);
    p.set("year", state.year);
    p.set("measure", state.measure);
    window.history.replaceState(null, "", window.location.pathname + "?" + p.toString());
  }

  var state = readUrlState();
  var geo = null; // загруженный FeatureCollection (мутируем properties при обновлении)

  var map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      sources: {},
      layers: [{ id: "bg", type: "background", paint: { "background-color": RL.cssVar("--map-bg", "#eaf0f1") } }],
    },
    center: [99, 66],
    zoom: 2,
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
        geo = fc;
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
        wireInteraction();
        update();
        if (window.RL && RL.onTheme) {
          RL.onTheme(function () {
            try {
              if (!map.getLayer || !map.getLayer("bg")) return;
              map.setPaintProperty("bg", "background-color", RL.cssVar("--map-bg", "#eaf0f1"));
              if (map.getLayer("line"))
                map.setPaintProperty("line", "line-color", RL.cssVar("--map-line", "#ffffff"));
              NODATA = RL.cssVar("--map-nodata", "#dcdcdc");
              if (map.getLayer("fill")) applyPaint();
            } catch (e) {}
          });
        }
      })
      .catch(function () {
        root.innerHTML =
          '<div class="shell"><p>' +
          gettext(
            "Не удалось загрузить границы регионов. Сформируйте <code>static/geo/regions.geojson</code> командой <code>build_region_geojson</code> (см. README)."
          ) +
          "</p></div>";
      });
  });

  function update() {
    var url = API + "?year=" + encodeURIComponent(state.year) + "&measure=" + state.measure;
    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error(gettext("Ошибка загрузки слоя") + " (" + r.status + ").");
        return r.json();
      })
      .then(function (rows) {
        var byOkato = {};
        rows.forEach(function (d) {
          byOkato[d.okato] = d;
        });
        var dists = rows
          .map(function (d) {
            return d.distance_to_centroid;
          })
          .filter(function (v) {
            return typeof v === "number";
          });
        var dMin = Math.min.apply(null, dists),
          dMax = Math.max.apply(null, dists);

        geo.features.forEach(function (f) {
          var d = byOkato[f.properties.okato];
          f.properties.cluster = d ? d.cluster_id : null;
          f.properties.label = d ? d.cluster_label || null : null;
          f.properties.value = d && typeof d.total_score === "number" ? d.total_score : null;
          // A1: типичность → плотность заливки (типичный=плотнее, пограничный=прозрачнее)
          var op = 0.85;
          if (d && typeof d.distance_to_centroid === "number" && dMax > dMin) {
            var t = (d.distance_to_centroid - dMin) / (dMax - dMin); // 0=типичный..1=пограничный
            op = 0.9 - 0.55 * t;
          }
          f.properties.op = d ? op : 0.25;
          f.properties.metric = d
            ? state.measure === "index"
              ? (d.total_score != null ? d.total_score.toFixed(1) : "—")
              : d.cluster_label || gettext("тип") + " " + d.cluster_id
            : gettext("нет данных");
        });
        map.getSource("regions").setData(geo);
        applyPaint();
        renderLegend(rows);
      })
      .catch(function (e) {
        var el = document.getElementById("map-legend");
        if (el) {
          el.innerHTML =
            "<div class='legend-title'>" + gettext("Слой не загрузился") + "</div>" +
            "<div class='legend-note'>" + RL.errText(e) + "</div>";
        }
      });
  }

  function applyPaint() {
    if (state.measure === "cluster") {
      map.setPaintProperty("fill", "fill-color", [
        "match",
        ["get", "cluster"],
        0, CLUSTER_COLORS[0],
        1, CLUSTER_COLORS[1],
        2, CLUSTER_COLORS[2],
        3, CLUSTER_COLORS[3],
        4, CLUSTER_COLORS[4],
        NODATA,
      ]);
      map.setPaintProperty("fill", "fill-opacity", ["coalesce", ["get", "op"], 0.25]);
    } else {
      map.setPaintProperty("fill", "fill-color", [
        "case",
        ["==", ["get", "value"], null],
        NODATA,
        [
          "interpolate", ["linear"], ["get", "value"],
          0, "#e7f0ee", 25, "#9cc8bd", 50, "#5fa896", 75, "#2e8170", 100, "#0c5c4f",
        ],
      ]);
      map.setPaintProperty("fill", "fill-opacity", 0.88);
    }
  }

  function wireInteraction() {
    map.on("mousemove", "fill", function (e) {
      map.getCanvas().style.cursor = "pointer";
      var p = e.features[0].properties;
      popup
        .setLngLat(e.lngLat)
        .setHTML(
          '<strong>' + (p.name || p.okato) + "</strong><br>" +
            (state.measure === "index" ? gettext("Индекс") + ": " : "") + (p.metric || "—")
        )
        .addTo(map);
    });
    map.on("mouseleave", "fill", function () {
      map.getCanvas().style.cursor = "";
      popup.remove();
    });
    map.on("click", "fill", function (e) {
      var okato = e.features[0].properties.okato;
      if (okato) window.location.href = "/regions/" + okato + "/?year=" + state.year;
    });
  }

  function renderLegend(rows) {
    var el = document.getElementById("map-legend");
    if (!el) return;
    if (state.measure === "cluster") {
      var seen = {};
      rows.forEach(function (d) {
        if (seen[d.cluster_id] === undefined)
        seen[d.cluster_id] = d.cluster_label || gettext("тип") + " " + d.cluster_id;
      });
      var html = "<div class='legend-title'>" + gettext("Типы регионов") + "</div>";
      Object.keys(seen).sort().forEach(function (cid) {
        html +=
          "<div class='legend-row'><span class='swatch' style='background:" +
          (CLUSTER_COLORS[cid] || NODATA) + "'></span>" + seen[cid] + "</div>";
      });
      html +=
        "<div class='legend-note'>" +
        gettext("Плотность заливки — типичность региона для своего типа.") +
        "</div>";
      el.innerHTML = html;
    } else {
      el.innerHTML =
        "<div class='legend-title'>" + gettext("Индекс развития (0–100)") + "</div>" +
        "<div class='legend-gradient'></div>" +
        "<div class='legend-scale'><span>0</span><span>50</span><span>100</span></div>";
    }
  }

  // ── Контролы (синхронизированы с URL; изменения пишутся в адресную строку) ──────────────
  if (slider) {
    slider.value = state.year;
    if (yearLabel) yearLabel.textContent = state.year;
    slider.addEventListener("input", function () {
      state.year = parseInt(slider.value, 10);
      if (yearLabel) yearLabel.textContent = state.year;
    });
    slider.addEventListener("change", function () {
      writeUrlState();
      if (geo) update();
    });
  }
  document.querySelectorAll("[data-measure]").forEach(function (btn) {
    btn.classList.toggle("is-active", btn.dataset.measure === state.measure);
    btn.addEventListener("click", function () {
      state.measure = btn.dataset.measure;
      document.querySelectorAll("[data-measure]").forEach(function (b) {
        b.classList.toggle("is-active", b === btn);
      });
      writeUrlState();
      if (geo) update();
    });
  });

  // Кнопка «скопировать ссылку» на текущий вид карты.
  var copyBtn = document.getElementById("map-copy-link");
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

  // Нормализовать URL под стартовое состояние, чтобы ссылку можно было сразу скопировать.
  writeUrlState();
})();
