/* RegionLens — корреляции метрик (Ф15, модуль 3).
   /api/correlations/ (analyst-only): пары метрик за год (по умолчанию последний), сильнейшие
   первыми. «Все пары» → топ-50; выбранный показатель → пары с ним (он выводится первым).
   Бар = |корреляция|, знак — в числе. Без обёртки .card у таблицы. Корреляция ≠ причинность. */

(function () {
  "use strict";

  var root = document.getElementById("correlations-root");
  var select = document.getElementById("metric-select");
  var slider = document.getElementById("year-slider");
  var label = document.getElementById("year-label");
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
        var opts = ['<option value="">' + gettext("Все пары") + "</option>"];
        rows.forEach(function (m) {
          opts.push('<option value="' + m.metric_id + '">' + m.metric_name + "</option>");
        });
        select.innerHTML = opts.join("");
        if (window.RL && RL.enhanceSelect) RL.enhanceSelect(select, gettext("Поиск показателя…"));
      });
  }

  function load() {
    shell(gettext("Загрузка…"));
    var metricId = select.value;
    var year = slider ? slider.value : "";
    var url = "/api/correlations/?year=" + encodeURIComponent(year);
    if (metricId) url += "&metric_id=" + encodeURIComponent(metricId);
    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error(gettext("Ошибка загрузки") + " (" + r.status + ")");
        return r.json();
      })
      .then(function (rows) {
        render(rows, metricId);
      })
      .catch(function (e) {
        shell(RL.errText(e));
      });
  }

  function render(rows, metricId) {
    if (!rows.length) {
      shell(gettext("Нет пар корреляций за выбранный год."));
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
      "<tr><th>" + gettext("Показатель A") + "</th><th>" + gettext("Показатель B") + "</th>" +
      "<th class='num'>" + gettext("Корреляция") + "</th><th class='num'>" + gettext("Регионов") + "</th></tr>";
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
      "<p class='chart-note'>" +
      interpolate(
        gettext(
          "Год: %(year)s · метод: %(method)s · пар: %(n)s · бар — |корреляция| (0…1), знак указан в числе. Сильнейшие связи — сверху. Связь не означает причинности."
        ),
        { year: year, method: method, n: rows.length },
        true
      ) +
      "</p>" +
      "<div class='table-wrap'><table class='table'><thead>" +
      head +
      "</thead><tbody>" +
      body +
      "</tbody></table></div>";
  }

  function readUrlState() {
    var p = new URLSearchParams(window.location.search);
    return { year: p.get("year"), metric: p.get("metric") || "" };
  }

  function writeUrlState() {
    var p = new URLSearchParams(window.location.search);
    if (slider) p.set("year", slider.value);
    if (select.value) p.set("metric", select.value);
    else p.delete("metric");
    window.history.replaceState(null, "", window.location.pathname + "?" + p.toString());
  }

  select.addEventListener("change", function () {
    writeUrlState();
    load();
  });
  if (slider) {
    slider.addEventListener("input", function () {
      if (label) label.textContent = slider.value;
    });
    slider.addEventListener("change", function () {
      writeUrlState();
      load();
    });
  }

  var copyBtn = document.getElementById("corr-copy-link");
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

  var initial = readUrlState();
  loadMetrics()
    .then(function () {
      if (slider && /^\d{4}$/.test(initial.year || "")) {
        var lo = parseInt(slider.min, 10),
          hi = parseInt(slider.max, 10);
        slider.value = Math.min(hi, Math.max(lo, parseInt(initial.year, 10)));
      }
      if (label && slider) label.textContent = slider.value;
      if (initial.metric) select.value = initial.metric; // приживётся, только если опция есть
      writeUrlState();
      load();
    })
    .catch(function (e) {
      shell(RL.errText(e));
    });
})();
