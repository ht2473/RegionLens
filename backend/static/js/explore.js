/* RegionLens — обзор показателей (explore, поток B).
   Каталог метрик (/api/metric-catalog/) слева → выбор показателя → значения по регионам за год
   (/api/metric-values/) в виде ранжированной таблицы с инлайн-баром. Состояние (метрика, год,
   фильтры) кодируется в URL — вид восстановим и шарится. Работает для любой из сотен метрик. */

(function () {
  "use strict";

  var root = document.getElementById("explore-root");
  if (!root) return;

  var DOMAIN_RU = {
    economy: gettext("Экономика"),
    income: gettext("Доходы"),
    labor: gettext("Труд"),
    demography: gettext("Демография"),
    infrastructure: gettext("Инфраструктура"),
    health_edu: gettext("Здоровье и образование"),
  };
  var CATALOG_LIMIT = 400;

  var $search = document.getElementById("ex-search");
  var $domain = document.getElementById("ex-domain");
  var $tier = document.getElementById("ex-tier");
  var $list = document.getElementById("ex-list");
  var $meta = document.getElementById("ex-meta");
  var $yearWrap = document.getElementById("ex-year-control");
  var $year = document.getElementById("ex-year");
  var $yearLabel = document.getElementById("ex-year-label");
  var $copy = document.getElementById("ex-copy-link");

  // Избранные показатели пользователя (для состояния звезды в мета-заголовке).
  var favAuth = !!(root && root.dataset.auth === "1");
  var favSet = new Set();
  (function () {
    var el = document.getElementById("ex-favorites");
    if (!el) return;
    try {
      (JSON.parse(el.textContent) || []).forEach(function (id) { favSet.add(String(id)); });
    } catch (e) { /* пустой/битый список — оставляем набор пустым */ }
  })();

  function favLabel(on) { return on ? gettext("В избранном") : gettext("В избранное"); }
  var $values = document.getElementById("ex-values");
  var $series = document.getElementById("ex-series");
  var $viewToggle = document.getElementById("ex-view-toggle");
  var $mapWrap = document.getElementById("ex-map-wrap");

  var state = { metric: null, year: null, view: "table", lastValues: null };

  // ── Утилиты ──────────────────────────────────────────────────────────────
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function fmt(v) {
    if (v == null) return "—";
    var n = Number(v);
    return n.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
  }
  function domainRu(d) {
    return DOMAIN_RU[d] || d || "—";
  }
  function shell(el, msg) {
    el.innerHTML = '<div class="shell"><p>' + esc(msg) + "</p></div>";
  }

  // ── URL-состояние (deep-link) ────────────────────────────────────────────
  function writeUrl() {
    var p = new URLSearchParams();
    if ($tier.value) p.set("tier", $tier.value);
    if ($domain.value) p.set("domain", $domain.value);
    if ($search.value.trim()) p.set("q", $search.value.trim());
    if (state.metric) p.set("metric", state.metric.metric_id);
    if (state.year != null) p.set("year", state.year);
    if (state.view === "map") p.set("view", "map");
    window.history.replaceState(null, "", window.location.pathname + "?" + p.toString());
  }

  // ── Каталог метрик (левая панель) ────────────────────────────────────────
  function catalogUrl(extra) {
    var p = new URLSearchParams();
    if ($tier.value) p.set("tier", $tier.value);
    if ($domain.value) p.set("domain", $domain.value);
    if ($search.value.trim()) p.set("search", $search.value.trim());
    p.set("limit", CATALOG_LIMIT);
    if (extra) Object.keys(extra).forEach(function (k) { p.set(k, extra[k]); });
    return "/api/metric-catalog/?" + p.toString();
  }

  function renderList(rows) {
    if (!rows.length) {
      $list.innerHTML = '<li class="explore-muted">' + gettext("Ничего не найдено.") + "</li>";
      return;
    }
    var html = rows
      .map(function (m) {
        var active = state.metric && state.metric.metric_id === m.metric_id ? " is-active" : "";
        var cov = m.coverage == null ? "" : Math.round(m.coverage * 100) + "%";
        return (
          '<li class="explore-item' + active + '" data-id="' + m.metric_id + '" tabindex="0">' +
          '<span class="explore-item-name">' + esc(m.metric_name) + "</span>" +
          '<span class="explore-item-meta">' + esc(domainRu(m.domain)) +
          (cov ? " · " + gettext("покрытие") + " " + cov : "") + "</span></li>"
        );
      })
      .join("");
    if (rows.length >= CATALOG_LIMIT) {
      html +=
        '<li class="explore-muted">' +
        interpolate(gettext("Показаны первые %(n)s. Уточните поиск."), { n: CATALOG_LIMIT }, true) +
        "</li>";
    }
    $list.innerHTML = html;
    // карта metric_id → строка каталога для быстрого выбора
    $list._rows = {};
    rows.forEach(function (m) { $list._rows[m.metric_id] = m; });
  }

  function loadCatalog() {
    fetch(catalogUrl())
      .then(function (r) {
        if (!r.ok) throw new Error(gettext("Ошибка каталога") + " (" + r.status + ")");
        return r.json();
      })
      .then(renderList)
      .catch(function (e) { shell($list, RL.errText(e)); });
  }

  // ── Выбор показателя ─────────────────────────────────────────────────────
  function selectMetric(m) {
    state.metric = m;
    clearSeries();
    // подсветка в списке
    Array.prototype.forEach.call($list.querySelectorAll(".explore-item"), function (li) {
      li.classList.toggle("is-active", Number(li.dataset.id) === m.metric_id);
    });
    renderMeta(m);
    // год: границы по охвату метрики, значение — из URL (если в границах) или последний год
    var lo = m.year_min,
      hi = m.year_max;
    if (lo == null || hi == null) {
      $yearWrap.hidden = true;
      shell($values, gettext("У показателя нет данных по годам."));
      return;
    }
    $year.min = lo;
    $year.max = hi;
    var y = state.year != null && state.year >= lo && state.year <= hi ? state.year : hi;
    state.year = y;
    $year.value = y;
    $yearLabel.textContent = y;
    $yearWrap.hidden = false;
    applyViewVisibility();
    writeUrl();
    loadValues();
  }

  function renderMeta(m) {
    var tierLabel = m.is_core
      ? gettext("ядро индекса")
      : m.tier === "extended"
        ? gettext("основной")
        : gettext("разрежен");
    $meta.innerHTML =
      "<h2>" + esc(m.metric_name) + "</h2>" +
      '<p class="explore-meta-line">' +
      esc(domainRu(m.domain)) +
      (m.unit ? " · " + esc(m.unit) : "") +
      (m.value_type ? " · " + gettext("тип") + ": " + esc(m.value_type) : "") +
      " · " + tierLabel +
      (m.year_min != null ? " · " + m.year_min + "–" + m.year_max : "") +
      "</p>";
    if (favAuth && window.RL && RL.toggleFavorite) {
      var favd = favSet.has(String(m.metric_id));
      var favBtn = document.createElement("button");
      favBtn.type = "button";
      favBtn.className = "fav-toggle" + (favd ? " is-active" : "");
      favBtn.style.marginTop = "8px";
      favBtn.innerHTML = '<span class="fav-star">\u2605</span><span class="fav-label"></span>';
      favBtn.querySelector(".fav-label").textContent = favLabel(favd);
      favBtn.addEventListener("click", function () {
        RL.toggleFavorite("metric", m.metric_id, m.metric_name).then(function (res) {
          if (res.favorited) favSet.add(String(m.metric_id));
          else favSet.delete(String(m.metric_id));
          favBtn.classList.toggle("is-active", res.favorited);
          favBtn.querySelector(".fav-label").textContent = favLabel(res.favorited);
        });
      });
      $meta.appendChild(favBtn);
    }
  }

  // ── Значения по регионам за год (правая панель) ──────────────────────────
  function renderValues(rows) {
    if (!rows.length) {
      shell($values, interpolate(gettext("Нет данных за %(year)s год."), { year: state.year }, true));
      return;
    }
    var maxAbs = rows.reduce(function (mx, r) {
      return Math.max(mx, Math.abs(Number(r.value) || 0));
    }, 0) || 1;
    var body = rows
      .map(function (r, i) {
        var w = Math.round((Math.abs(Number(r.value) || 0) / maxAbs) * 100);
        return (
          "<tr class='explore-row' data-okato='" + esc(r.okato) +
          "' data-name='" + esc(r.region_name) + "'>" +
          "<td class='num'>" + (i + 1) + "</td>" +
          "<td>" + esc(r.region_name) + "</td>" +
          "<td class='num'><strong>" + fmt(r.value) + "</strong>" +
          "<div class='score-bar'><span style='width:" + w + "%'></span></div></td></tr>"
        );
      })
      .join("");
    $values.innerHTML =
      "<div class='table-wrap'><table class='table'><thead>" +
      "<tr><th class='num'>#</th><th>" + gettext("Регион") + "</th><th class='num'>" + gettext("Значение") + "</th></tr>" +
      "</thead><tbody>" + body + "</tbody></table></div>" +
      "<p class='chart-note'>" +
      interpolate(
        gettext(
          "%(n)s регионов · %(year)s год · бар нормирован по максимуму ряда · кликните регион — его динамика по годам."
        ),
        { n: rows.length, year: state.year },
        true
      ) +
      "</p>";
  }

  function loadValues() {
    if (!state.metric) return;
    if (state.view !== "map") shell($values, gettext("Загрузка…"));
    fetch("/api/metric-values/?metric_id=" + state.metric.metric_id + "&year=" + state.year)
      .then(function (r) {
        if (!r.ok) throw new Error(gettext("Ошибка значений") + " (" + r.status + ")");
        return r.json();
      })
      .then(function (rows) {
        state.lastValues = rows;
        renderActiveView(rows);
      })
      .catch(function (e) {
        if (state.view === "map") {
          var el = document.getElementById("ex-map-legend");
          if (el) el.innerHTML = "<div class='legend-note'>" + RL.errText(e) + "</div>";
        } else {
          shell($values, RL.errText(e));
        }
      });
  }

  function renderActiveView(rows) {
    if (state.view === "map") exmap.render(rows);
    else renderValues(rows);
  }

  // ── Drill-down: ряд региона по выбранной метрике (клик по строке) ─────────
  function clearSeries() {
    $series.hidden = true;
    $series.innerHTML = "";
  }

  function selectRegion(okato, name) {
    if (!state.metric) return;
    $series.hidden = false;
    $series.innerHTML = '<div class="shell"><p>' + gettext("Загрузка ряда…") + "</p></div>";
    fetch("/api/metrics/" + state.metric.metric_id + "/series/?okato=" + encodeURIComponent(okato))
      .then(function (r) {
        if (!r.ok) throw new Error(gettext("Ошибка ряда") + " (" + r.status + ")");
        return r.json();
      })
      .then(function (rows) { renderSeries(rows, name); })
      .catch(function (e) { shell($series, RL.errText(e)); });
  }

  function renderSeries(rows, name) {
    var pts = rows.filter(function (r) { return r.value != null; });
    if (!pts.length) {
      shell($series, gettext("У региона нет ряда по этому показателю."));
      return;
    }
    $series.innerHTML =
      '<div class="explore-series-head"><strong>' + esc(name) + "</strong> · " +
      esc(state.metric.metric_name) +
      '<button type="button" class="explore-series-close" aria-label="' + gettext("Закрыть") + '">×</button></div>' +
      '<div id="ex-series-chart"></div>';
    Plotly.newPlot(
      "ex-series-chart",
      [
        {
          x: pts.map(function (r) { return r.year; }),
          y: pts.map(function (r) { return r.value; }),
          type: "scatter",
          mode: "lines+markers",
          line: { color: "#1f6f63", width: 2 },
          marker: { size: 5, color: "#1f6f63" },
          hovertemplate: "%{x}: %{y}<extra></extra>",
        },
      ],
      {
        margin: { l: 54, r: 16, t: 6, b: 34 },
        height: 260,
        xaxis: { dtick: 2, gridcolor: RL.cssVar("--line-soft", "#e9e3d6") },
        yaxis: { title: state.metric.unit || "", gridcolor: RL.cssVar("--line-soft", "#e9e3d6") },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        font: { family: "Golos Text, sans-serif", color: RL.cssVar("--ink-soft", "#51606e") },
      },
      { responsive: true, displayModeBar: false }
    );
    var close = $series.querySelector(".explore-series-close");
    if (close) close.addEventListener("click", clearSeries);
  }

  // ── Карта-хороплет (вид «Карта») ─────────────────────────────────────────
  // Те же значения, что в таблице, на карте субъектов. Последовательная шкала min→max
  // (для произвольной метрики «выше=лучше» неизвестно). Клик по региону — тот же drill-down ряда.
  var exmap = (function () {
    var GEOJSON_URL = "/static/geo/regions.geojson";
    var NODATA = RL.cssVar("--map-nodata", "#dcdcdc");
    var map = null;
    var geo = null;
    var ready = false;
    var pending = null;
    var popup = null;

    function ensureInit() {
      if (map || typeof maplibregl === "undefined") return;
      map = new maplibregl.Map({
        container: "ex-map",
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
      popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
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
            wire();
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
            ready = true;
            if (pending) {
              render(pending);
              pending = null;
            }
          })
          .catch(function () {
            var el = document.getElementById("ex-map");
            if (el) {
              el.innerHTML = '<div class="shell"><p>' + gettext("Не удалось загрузить границы регионов.") + "</p></div>";
            }
          });
      });
    }

    function wire() {
      RL.attachMapHover(map, {
        popup: popup,
        html: function (p) {
          var v = p.exdisp != null && p.exdisp !== "" ? p.exdisp : gettext("нет данных");
          return "<strong>" + (p.name || p.okato) + "</strong><br>" + v;
        },
      });
      map.on("click", "fill", function (e) {
        var p = e.features[0].properties;
        if (p.okato) selectRegion(p.okato, p.name || p.okato);
      });
    }

    function applyPaint(lo, hi) {
      var color;
      if (hi <= lo) {
        color = "#5fa896"; // все значения равны — один цвет
      } else {
        color = [
          "interpolate", ["linear"], ["get", "exval"],
          lo, "#e7f0ee", (lo + hi) / 2, "#5fa896", hi, "#0c5c4f",
        ];
      }
      map.setPaintProperty("fill", "fill-color", [
        "case", ["==", ["get", "exval"], null], NODATA, color,
      ]);
      map.setPaintProperty("fill", "fill-opacity", 0.88);
    }

    function renderLegend(lo, hi) {
      var el = document.getElementById("ex-map-legend");
      if (!el) return;
      var unit = state.metric && state.metric.unit ? " · " + esc(state.metric.unit) : "";
      el.innerHTML =
        "<div class='legend-title'>" + gettext("Значение") + unit + "</div>" +
        "<div class='legend-gradient'></div>" +
        "<div class='legend-scale'><span>" + fmt(lo) + "</span><span>" + fmt(hi) + "</span></div>" +
        "<div class='legend-note'>" + gettext("Светлее — меньше, темнее — больше. Серый — нет данных.") + "</div>";
    }

    function render(rows) {
      if (typeof maplibregl === "undefined") return;
      ensureInit();
      if (!ready) {
        pending = rows;
        return;
      }
      var byOkato = {};
      rows.forEach(function (d) { byOkato[d.okato] = d; });
      var vals = rows
        .map(function (d) { return Number(d.value); })
        .filter(function (v) { return !isNaN(v); });
      var lo = vals.length ? Math.min.apply(null, vals) : 0;
      var hi = vals.length ? Math.max.apply(null, vals) : 1;
      geo.features.forEach(function (f) {
        var d = byOkato[f.properties.okato];
        f.properties.exval = d && d.value != null ? Number(d.value) : null;
        f.properties.exdisp = d && d.value != null ? fmt(d.value) : null;
      });
      map.getSource("regions").setData(geo);
      applyPaint(lo, hi);
      renderLegend(lo, hi);
      map.resize();
    }

    return { render: render };
  })();

  // ── Переключение вида (Таблица / Карта) ──────────────────────────────────
  function applyViewVisibility() {
    Array.prototype.forEach.call($viewToggle.querySelectorAll("[data-view]"), function (b) {
      b.classList.toggle("is-active", b.dataset.view === state.view);
    });
    $values.hidden = state.view === "map";
    $mapWrap.hidden = state.view !== "map";
  }

  function setView(view) {
    state.view = view === "map" ? "map" : "table";
    applyViewVisibility();
    writeUrl();
    if (state.lastValues) renderActiveView(state.lastValues);
  }

  // ── События ──────────────────────────────────────────────────────────────
  var searchTimer = null;
  $search.addEventListener("input", function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      writeUrl();
      loadCatalog();
    }, 250);
  });
  $domain.addEventListener("change", function () {
    writeUrl();
    loadCatalog();
  });
  $tier.addEventListener("change", function () {
    writeUrl();
    loadCatalog();
  });
  $list.addEventListener("click", function (e) {
    var li = e.target.closest(".explore-item");
    if (li && $list._rows) selectMetric($list._rows[Number(li.dataset.id)]);
  });
  $list.addEventListener("keydown", function (e) {
    if (e.key !== "Enter") return;
    var li = e.target.closest(".explore-item");
    if (li && $list._rows) selectMetric($list._rows[Number(li.dataset.id)]);
  });
  $values.addEventListener("click", function (e) {
    var tr = e.target.closest(".explore-row");
    if (tr) selectRegion(tr.dataset.okato, tr.dataset.name);
  });
  $year.addEventListener("input", function () {
    state.year = parseInt($year.value, 10);
    $yearLabel.textContent = state.year;
  });
  $year.addEventListener("change", function () {
    writeUrl();
    loadValues();
  });
  if ($viewToggle) {
    $viewToggle.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-view]");
      if (btn) setView(btn.dataset.view);
    });
  }
  if ($copy) {
    $copy.addEventListener("click", function () {
      var flash = function () {
        var prev = $copy.textContent;
        $copy.textContent = gettext("Ссылка скопирована");
        setTimeout(function () { $copy.textContent = prev; }, 1500);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(window.location.href).then(flash, flash);
      } else {
        flash();
      }
    });
  }

  // ── Домены в селекте ─────────────────────────────────────────────────────
  Object.keys(DOMAIN_RU).forEach(function (d) {
    var opt = document.createElement("option");
    opt.value = d;
    opt.textContent = DOMAIN_RU[d];
    $domain.appendChild(opt);
  });

  // ── Инициализация из URL ─────────────────────────────────────────────────
  var p = new URLSearchParams(window.location.search);
  if (p.has("tier")) $tier.value = p.get("tier");
  if (p.get("domain")) $domain.value = p.get("domain");
  if (p.get("q")) $search.value = p.get("q");
  var urlYear = parseInt(p.get("year"), 10);
  if (!isNaN(urlYear)) state.year = urlYear;
  if (p.get("view") === "map") state.view = "map";
  var urlMetric = parseInt(p.get("metric"), 10);

  loadCatalog();
  if (!isNaN(urlMetric)) {
    // восстановить выбранную метрику по ссылке (одну строку каталога)
    fetch("/api/metric-catalog/?metric_id=" + urlMetric)
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (rows) {
        if (rows.length) selectMetric(rows[0]);
      })
      .catch(function () {});
  }
})();
