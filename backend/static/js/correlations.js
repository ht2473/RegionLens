/* RegionLens — корреляции метрик (Ф15, модуль 3).
   /api/correlations/ (analyst-only): пары метрик за год (по умолчанию последний), сильнейшие
   первыми. «Все пары» → топ-50; выбранный показатель → пары с ним (он выводится первым).
   Бар = |корреляция|, знак — в числе. Без обёртки .card у таблицы. Корреляция ≠ причинность. */

(function () {
  "use strict";

  var root = document.getElementById("correlations-root");
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
        if (!r.ok) throw new Error("Ошибка каталога метрик (" + r.status + ")");
        return r.json();
      })
      .then(function (rows) {
        var opts = ['<option value="">Все пары</option>'];
        rows.forEach(function (m) {
          opts.push('<option value="' + m.metric_id + '">' + m.metric_name + "</option>");
        });
        select.innerHTML = opts.join("");
      });
  }

  function load() {
    shell("Загрузка…");
    var metricId = select.value;
    var url = metricId
      ? "/api/correlations/?metric_id=" + encodeURIComponent(metricId)
      : "/api/correlations/?limit=50";
    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error("Ошибка загрузки (" + r.status + ")");
        return r.json();
      })
      .then(function (rows) {
        render(rows, metricId);
      })
      .catch(function (e) {
        shell(e.message);
      });
  }

  function render(rows, metricId) {
    if (!rows.length) {
      shell("Нет данных корреляций. Пересоберите конвейер (стадия correlations).");
      return;
    }
    // в режиме фильтра показываем выбранную метрику первой
    if (metricId) {
      rows.forEach(function (r) {
        if (String(r.metric_b) === String(metricId)) {
          var ta = r.metric_a;
          var tan = r.metric_a_name;
          r.metric_a = r.metric_b;
          r.metric_a_name = r.metric_b_name;
          r.metric_b = ta;
          r.metric_b_name = tan;
        }
      });
    }

    var year = rows[0].year;
    var method = rows[0].method;
    var maxAbs = 1; // корреляция по модулю ≤ 1 — нормируем бар по 1

    var head =
      "<tr><th>Показатель A</th><th>Показатель B</th>" +
      "<th class='num'>Корреляция</th><th class='num'>Регионов</th></tr>";
    var body = rows
      .map(function (r) {
        var w = Math.max(2, Math.min(100, (Math.abs(r.correlation) / maxAbs) * 100));
        var bar = "<div class='score-bar'><span style='width:" + w + "%'></span></div>";
        return (
          "<tr><td>" + (r.metric_a_name || r.metric_a) + "</td>" +
          "<td>" + (r.metric_b_name || r.metric_b) + "</td>" +
          "<td class='num'><strong>" + num(r.correlation) + "</strong>" + bar + "</td>" +
          "<td class='num'>" + (r.n_regions == null ? "—" : r.n_regions) + "</td></tr>"
        );
      })
      .join("");

    root.innerHTML =
      "<p class='chart-note'>Год: " + year + " · метод: " + method +
      " · бар — |корреляция| (0…1), знак указан в числе. Сильнейшие связи — сверху. " +
      "Связь не означает причинности.</p>" +
      "<div class='table-wrap'><table class='table'><thead>" +
      head +
      "</thead><tbody>" +
      body +
      "</tbody></table></div>";
  }

  select.addEventListener("change", load);

  loadMetrics()
    .then(function () {
      load();
    })
    .catch(function (e) {
      shell(e.message);
    });
})();
