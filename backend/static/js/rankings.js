/* RegionLens — рейтинг (Ф7, модуль 4).
   Таблица регионов по индексу: /api/index/?year=&scheme= (ранг, индекс, доменные баллы);
   имена берём из /api/regions/. Строка кликабельна → дашборд региона. */

(function () {
  "use strict";

  var root = document.getElementById("rankings-root");
  if (!root) return;

  var DOMAINS = [
    ["economy", gettext("Эк.")],
    ["income", gettext("Дох.")],
    ["demography", gettext("Дем.")],
    ["labor", gettext("Труд")],
    ["infrastructure", gettext("Инфр.")],
    ["health_edu", gettext("Здр./обр.")],
  ];
  var state = { year: RL.prefYear(2024), scheme: RL.prefScheme("equal") };
  RL.syncYearControl(state.year);
  (function () {
    var ss = document.getElementById("scheme-select");
    if (ss) ss.value = state.scheme;
  })();
  var names = null; // okato -> region_name

  // ── Связанная карта: хороплет по индексу + двусторонняя подсветка со строками таблицы ──
  // Инициализируется один раз; guard'ы делают её необязательной (нет MapLibre/geojson —
  // рейтинг работает как прежде). onRow(okato, kind) вызывается при наведении/клике по карте.
  var lmap = (function () {
    var el = document.getElementById("rankings-map");
    if (!el || typeof maplibregl === "undefined") return null;

    var geo = null, ready = false, pending = null, onRow = null;
    var map = new maplibregl.Map({
      container: "rankings-map",
      style: {
        version: 8, sources: {},
        layers: [{ id: "bg", type: "background", paint: { "background-color": RL.cssVar("--map-bg", "#eaf0f1") } }],
      },
      center: [99, 66], zoom: 1.6, renderWorldCopies: false, attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    var popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });

    map.on("load", function () {
      fetch("/static/geo/regions.geojson")
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (fc) {
          if (!fc) {
            var w = el.closest(".rankings-map-wrap");
            if (w) w.style.display = "none";
            return;
          }
          geo = fc;
          map.addSource("regions", { type: "geojson", data: geo });
          map.addLayer({ id: "fill", type: "fill", source: "regions",
            paint: { "fill-color": RL.cssVar("--map-nodata", "#dcdcdc"), "fill-opacity": 0.9 } });
          map.addLayer({ id: "line", type: "line", source: "regions",
            paint: { "line-color": RL.cssVar("--map-line", "#ffffff"), "line-width": 0.5 } });
          map.addLayer({ id: "hl", type: "line", source: "regions",
            paint: { "line-color": RL.cssVar("--accent", "#1f6f63"), "line-width": 2.5 },
            filter: ["==", ["get", "okato"], "__none__"] });
          wire();
          ready = true;
          if (pending) { paint(pending); pending = null; }
        })
        .catch(function () {
          // geojson недоступен — убираем блок карты, таблица работает как прежде
          var wrap = el.closest(".rankings-map-wrap");
          if (wrap) wrap.style.display = "none";
        });
    });

    function paint(rows) {
      if (!ready) { pending = rows; return; }
      var by = {};
      rows.forEach(function (r) { by[r.okato] = r; });
      geo.features.forEach(function (f) {
        var d = by[f.properties.okato];
        f.properties.value = d && typeof d.total_score === "number" ? d.total_score : null;
        f.properties.rank = d ? d.rank : null;
      });
      map.getSource("regions").setData(geo);
      map.setPaintProperty("fill", "fill-color", [
        "case", ["==", ["get", "value"], null], RL.cssVar("--map-nodata", "#dcdcdc"),
        ["interpolate", ["linear"], ["get", "value"],
          0, "#e7f0ee", 25, "#9cc8bd", 50, "#5fa896", 75, "#2e8170", 100, "#0c5c4f"],
      ]);
    }

    function highlight(okato) {
      if (ready) map.setFilter("hl", ["==", ["get", "okato"], okato || "__none__"]);
    }

    function wire() {
      map.on("mousemove", "fill", function (e) {
        map.getCanvas().style.cursor = "pointer";
        var p = e.features[0].properties;
        popup.setLngLat(e.lngLat).setHTML(
          "<strong>" + (p.name || p.okato) + "</strong>" +
          (p.rank != null ? "<br>" + gettext("Место") + ": " + p.rank : "")
        ).addTo(map);
        highlight(p.okato);
        if (onRow) onRow(p.okato, "hover");
      });
      map.on("mouseleave", "fill", function () {
        map.getCanvas().style.cursor = ""; popup.remove(); highlight(null);
        if (onRow) onRow(null, "hover");
      });
      map.on("click", "fill", function (e) {
        if (onRow) onRow(e.features[0].properties.okato, "click");
      });
    }

    return {
      paint: paint,
      highlight: highlight,
      setOnRow: function (fn) { onRow = fn; },
    };
  })();

  function num(x, d) { return x == null ? "—" : Number(x).toFixed(d == null ? 2 : d); }

  function ensureNames() {
    if (names) return Promise.resolve(names);
    return fetch("/api/regions/")
      .then(function (r) { return r.json(); })
      .then(function (rows) {
        names = {};
        rows.forEach(function (r) { names[r.okato] = r.region_name; });
        return names;
      });
  }

  function load() {
    root.innerHTML = '<div class="shell"><p>' + gettext("Загрузка рейтинга…") + "</p></div>";
    Promise.all([
      ensureNames(),
      fetch("/api/index/?year=" + state.year + "&scheme=" + state.scheme).then(function (r) {
        if (!r.ok) throw new Error(gettext("Ошибка загрузки рейтинга") + " (" + r.status + ")");
        return r.json();
      }),
      // коридор ранга по схемам — необязателен: если недоступен, рейтинг работает как прежде
      fetch("/api/index/robustness/?year=" + state.year)
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; }),
    ])
      .then(function (out) { render(out[1], out[2]); })
      .catch(function (e) { root.innerHTML = '<div class="shell"><p>' + RL.errText(e) + "</p></div>"; });
  }

  function render(rows, robustness) {
    if (!rows.length) {
      root.innerHTML = '<div class="shell"><p>' + gettext("Нет данных за выбранный год.") + "</p></div>";
      return;
    }
    var hasCorr = Array.isArray(robustness);
    var corrMap = {};
    if (hasCorr) robustness.forEach(function (c) { corrMap[c.okato] = c; });

    var head =
      "<tr><th>#</th><th>" + gettext("Регион") + "</th><th class='num'>" + gettext("Индекс") + "</th>" +
      DOMAINS.map(function (d) { return "<th class='num' title='" + d[0] + "'>" + d[1] + "</th>"; }).join("") +
      (hasCorr
        ? "<th class='num' title='" + gettext("Разброс места по всем схемам весов") + "'>" + gettext("Коридор") + "</th>"
        : "") +
      "</tr>";
    var body = rows
      .map(function (r) {
        var nm = (names && names[r.okato]) || r.okato;
        var bar =
          "<div class='score-bar'><span style='width:" +
          Math.max(0, Math.min(100, r.total_score || 0)) + "%'></span></div>";
        var domains = DOMAINS.map(function (d) {
          return "<td class='num'>" + num(r[d[0]]) + "</td>";
        }).join("");
        var corrCell = "";
        if (hasCorr) {
          var c = corrMap[r.okato];
          if (c) {
            var txt =
              c.rank_best === c.rank_worst ? String(c.rank_best) : c.rank_best + "–" + c.rank_worst;
            var cls = c.rank_range >= 10 ? "num rank-wide" : "num";
            corrCell =
              "<td class='" + cls + "' title='" +
              interpolate(
                gettext("По схемам весов: с %(best)s по %(worst)s место (коридор %(range)s)"),
                { best: c.rank_best, worst: c.rank_worst, range: c.rank_range },
                true
              ) +
              "'>" + txt + "</td>";
          } else {
            corrCell = "<td class='num'>—</td>";
          }
        }
        return (
          "<tr data-okato='" + r.okato + "'><td class='num'>" + r.rank + "</td>" +
          "<td><a class='row-link' href='/regions/" + r.okato + "/?year=" + state.year + "'>" + nm + "</a></td>" +
          "<td class='num'><strong>" + num(r.total_score, 1) + "</strong>" + bar + "</td>" +
          domains + corrCell + "</tr>"
        );
      })
      .join("");
    var note = hasCorr
      ? "<p class='chart-note'>" +
        gettext(
          "«Коридор» — место региона по разным схемам весов (равные / PCA / экспертные): чем шире, тем сильнее ранг зависит от выбора весов, а не от самих данных."
        ) +
        "</p>"
      : "";
    root.innerHTML =
      "<div class='table-wrap'><table class='table rankings'><thead>" +
      head + "</thead><tbody>" + body + "</tbody></table></div>" + note;
    var rowByOkato = {};
    root.querySelectorAll("tr[data-okato]").forEach(function (tr) {
      var okato = tr.dataset.okato;
      rowByOkato[okato] = tr;
      tr.addEventListener("click", function () {
        window.location.href = "/regions/" + okato + "/?year=" + state.year;
      });
      if (lmap) {
        tr.addEventListener("mouseenter", function () { lmap.highlight(okato); });
        tr.addEventListener("mouseleave", function () { lmap.highlight(null); });
      }
    });

    if (lmap) {
      lmap.paint(rows);
      lmap.setOnRow(function (okato, kind) {
        var prev = root.querySelector("tr.is-hover");
        if (prev) prev.classList.remove("is-hover");
        if (!okato) return;
        var tr = rowByOkato[okato];
        if (!tr) return;
        tr.classList.add("is-hover");
        if (kind === "click") {
          tr.scrollIntoView({ block: "center", behavior: "smooth" });
          tr.classList.add("is-flash");
          setTimeout(function () { tr.classList.remove("is-flash"); }, 1200);
        }
      });
    }
  }

  var slider = document.getElementById("year-slider");
  var label = document.getElementById("year-label");
  if (slider) {
    slider.addEventListener("input", function () {
      state.year = parseInt(slider.value, 10);
      if (label) label.textContent = state.year;
    });
    slider.addEventListener("change", load);
  }
  var scheme = document.getElementById("scheme-select");
  if (scheme) {
    scheme.addEventListener("change", function () {
      state.scheme = scheme.value;
      load();
    });
  }

  load();
})();
