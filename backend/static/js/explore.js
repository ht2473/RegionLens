/* RegionLens — обзор показателей (explore, поток B).
   Каталог метрик (/api/metric-catalog/) слева → выбор показателя → значения по регионам за год
   (/api/metric-values/) в виде ранжированной таблицы с инлайн-баром. Состояние (метрика, год,
   фильтры) кодируется в URL — вид восстановим и шарится. Работает для любой из сотен метрик. */

(function () {
  "use strict";

  var root = document.getElementById("explore-root");
  if (!root) return;

  var DOMAIN_RU = {
    economy: "Экономика",
    income: "Доходы",
    labor: "Труд",
    demography: "Демография",
    infrastructure: "Инфраструктура",
    health_edu: "Здоровье и образование",
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
  var $values = document.getElementById("ex-values");
  var $series = document.getElementById("ex-series");

  var state = { metric: null, year: null };

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
      $list.innerHTML = '<li class="explore-muted">Ничего не найдено.</li>';
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
          (cov ? " · покрытие " + cov : "") + "</span></li>"
        );
      })
      .join("");
    if (rows.length >= CATALOG_LIMIT) {
      html += '<li class="explore-muted">Показаны первые ' + CATALOG_LIMIT + ". Уточните поиск.</li>";
    }
    $list.innerHTML = html;
    // карта metric_id → строка каталога для быстрого выбора
    $list._rows = {};
    rows.forEach(function (m) { $list._rows[m.metric_id] = m; });
  }

  function loadCatalog() {
    fetch(catalogUrl())
      .then(function (r) {
        if (!r.ok) throw new Error("Ошибка каталога (" + r.status + ")");
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
      shell($values, "У показателя нет данных по годам.");
      return;
    }
    $year.min = lo;
    $year.max = hi;
    var y = state.year != null && state.year >= lo && state.year <= hi ? state.year : hi;
    state.year = y;
    $year.value = y;
    $yearLabel.textContent = y;
    $yearWrap.hidden = false;
    writeUrl();
    loadValues();
  }

  function renderMeta(m) {
    var tierLabel = m.is_core ? "ядро индекса" : m.tier === "extended" ? "основной" : "разрежен";
    $meta.innerHTML =
      "<h2>" + esc(m.metric_name) + "</h2>" +
      '<p class="explore-meta-line">' +
      esc(domainRu(m.domain)) +
      (m.unit ? " · " + esc(m.unit) : "") +
      (m.value_type ? " · тип: " + esc(m.value_type) : "") +
      " · " + tierLabel +
      (m.year_min != null ? " · " + m.year_min + "–" + m.year_max : "") +
      "</p>";
  }

  // ── Значения по регионам за год (правая панель) ──────────────────────────
  function renderValues(rows) {
    if (!rows.length) {
      shell($values, "Нет данных за " + state.year + " год.");
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
      "<tr><th class='num'>#</th><th>Регион</th><th class='num'>Значение</th></tr>" +
      "</thead><tbody>" + body + "</tbody></table></div>" +
      "<p class='chart-note'>" + rows.length + " регионов · " + state.year +
      " год · бар нормирован по максимуму ряда · кликните регион — его динамика по годам.</p>";
  }

  function loadValues() {
    if (!state.metric) return;
    shell($values, "Загрузка…");
    fetch("/api/metric-values/?metric_id=" + state.metric.metric_id + "&year=" + state.year)
      .then(function (r) {
        if (!r.ok) throw new Error("Ошибка значений (" + r.status + ")");
        return r.json();
      })
      .then(renderValues)
      .catch(function (e) { shell($values, RL.errText(e)); });
  }

  // ── Drill-down: ряд региона по выбранной метрике (клик по строке) ─────────
  function clearSeries() {
    $series.hidden = true;
    $series.innerHTML = "";
  }

  function selectRegion(okato, name) {
    if (!state.metric) return;
    $series.hidden = false;
    $series.innerHTML = '<div class="shell"><p>Загрузка ряда…</p></div>';
    fetch("/api/metrics/" + state.metric.metric_id + "/series/?okato=" + encodeURIComponent(okato))
      .then(function (r) {
        if (!r.ok) throw new Error("Ошибка ряда (" + r.status + ")");
        return r.json();
      })
      .then(function (rows) { renderSeries(rows, name); })
      .catch(function (e) { shell($series, RL.errText(e)); });
  }

  function renderSeries(rows, name) {
    var pts = rows.filter(function (r) { return r.value != null; });
    if (!pts.length) {
      shell($series, "У региона нет ряда по этому показателю.");
      return;
    }
    $series.innerHTML =
      '<div class="explore-series-head"><strong>' + esc(name) + "</strong> · " +
      esc(state.metric.metric_name) +
      '<button type="button" class="explore-series-close" aria-label="Закрыть">×</button></div>' +
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
        xaxis: { dtick: 2, gridcolor: "#e9e3d6" },
        yaxis: { title: state.metric.unit || "", gridcolor: "#e9e3d6" },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        font: { family: "Golos Text, sans-serif", color: "#51606e" },
      },
      { responsive: true, displayModeBar: false }
    );
    var close = $series.querySelector(".explore-series-close");
    if (close) close.addEventListener("click", clearSeries);
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
  if ($copy) {
    $copy.addEventListener("click", function () {
      var flash = function () {
        var prev = $copy.textContent;
        $copy.textContent = "Ссылка скопирована";
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
