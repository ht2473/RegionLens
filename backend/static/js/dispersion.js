/* RegionLens — неравенство регионов (Ф13, модуль 3).
   Разброс показателя по регионам за годы: /api/dispersion/?metric_id=
   (n, медиана, P10/P90, P90/P10, CV, IQR); каталог метрик — /api/metrics/.
   Бар в столбце P90/P10 нормирован по максимуму ряда — видно, растёт ли разрыв по годам. */

(function () {
  "use strict";

  var root = document.getElementById("dispersion-root");
  var select = document.getElementById("metric-select");
  if (!root || !select) return;

  function num(x, d) {
    return x == null ? "—" : Number(x).toFixed(d == null ? 2 : d);
  }

  function shell(msg) {
    root.innerHTML = '<div class="shell"><p>' + msg + "</p></div>";
  }

  function loadMetrics() {
    return fetch("/api/metrics/")
      .then(function (r) {
        if (!r.ok) throw new Error(gettext("Ошибка каталога метрик") + " (" + r.status + ")");
        return r.json();
      })
      .then(function (rows) {
        if (!rows.length) {
          select.innerHTML = "<option>" + gettext("Нет метрик") + "</option>";
          throw new Error(gettext("Каталог метрик пуст."));
        }
        select.innerHTML = rows
          .map(function (m) {
            return '<option value="' + m.metric_id + '">' + m.metric_name + "</option>";
          })
          .join("");
        if (window.RL && RL.enhanceSelect) RL.enhanceSelect(select, gettext("Поиск показателя…"));
        return rows[0].metric_id;
      });
  }

  function load(metricId) {
    shell(gettext("Загрузка…"));
    fetch("/api/dispersion/?metric_id=" + metricId)
      .then(function (r) {
        if (!r.ok) throw new Error(gettext("Ошибка загрузки") + " (" + r.status + ")");
        return r.json();
      })
      .then(function (rows) {
        render(rows);
      })
      .catch(function (e) {
        shell(RL.errText(e));
      });
  }

  function render(rows) {
    if (!rows.length) {
      shell(gettext("Нет данных разброса по этому показателю."));
      return;
    }
    rows.sort(function (a, b) {
      return a.year - b.year;
    });

    // нормировка бара по максимуму P90/P10 в ряду (видно рост/спад разрыва)
    var ratios = rows
      .map(function (r) {
        return r.p90_p10_ratio;
      })
      .filter(function (v) {
        return v != null;
      });
    var maxRatio = ratios.length ? Math.max.apply(null, ratios) : 0;
    var hasRatio = ratios.length > 0;

    var head =
      "<tr><th>" + gettext("Год") + "</th><th class='num'>n</th><th class='num'>" + gettext("Медиана") + "</th>" +
      "<th class='num'>P10</th><th class='num'>P90</th>" +
      "<th class='num'>P90/P10</th><th class='num'>CV</th><th class='num'>IQR</th></tr>";

    var body = rows
      .map(function (r) {
        var bar = "";
        if (r.p90_p10_ratio != null && maxRatio > 0) {
          var w = Math.max(2, Math.min(100, (r.p90_p10_ratio / maxRatio) * 100));
          bar = "<div class='score-bar'><span style='width:" + w + "%'></span></div>";
        }
        return (
          "<tr><td>" + r.year + "</td>" +
          "<td class='num'>" + (r.n_regions == null ? "—" : r.n_regions) + "</td>" +
          "<td class='num'>" + num(r.median) + "</td>" +
          "<td class='num'>" + num(r.p10) + "</td>" +
          "<td class='num'>" + num(r.p90) + "</td>" +
          "<td class='num'><strong>" + num(r.p90_p10_ratio) + "</strong>" + bar + "</td>" +
          "<td class='num'>" + num(r.cv) + "</td>" +
          "<td class='num'>" + num(r.iqr) + "</td></tr>"
        );
      })
      .join("");

    var note = hasRatio
      ? "<p class='chart-note'>" +
        gettext(
          "Столбец и бар P90/P10 — отношение значения региона 90-го перцентиля к 10-му: 1 — равенство, рост по годам — расширение разрыва. Считается для величин со шкалой отношений."
        ) +
        "</p>"
      : "<p class='chart-note'>" +
        gettext(
          "Для этого типа показателя отношение P90/P10 и коэффициент вариации не определены (нет содержательного нуля) — смотрите разброс по IQR и значениям P10/P90."
        ) +
        "</p>";

    root.innerHTML =
      note +
      "<div class='table-wrap'><table class='table'><thead>" +
      head +
      "</thead><tbody>" +
      body +
      "</tbody></table></div>";
  }

  select.addEventListener("change", function () {
    load(select.value);
  });

  loadMetrics()
    .then(function (firstId) {
      load(firstId);
    })
    .catch(function (e) {
      shell(RL.errText(e));
    });
})();
