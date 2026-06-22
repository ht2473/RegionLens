/* RegionLens — качество данных (Ф17, модуль 3).
   Полнота/импутации аналитической сетки: /api/data-quality/ (строки на метрику-год).
   Строим три роллапа из плоских строк: по годам (полнота сырья + импутации),
   по доменам и по метрикам (самые импутированные первыми). Различаем доступность
   сырья (completeness_raw / coverage) и долю достроенных ячеек (impute_share):
   для absolute-метрик они расходятся (гармонизация делит на население). */

(function () {
  "use strict";

  var root = document.getElementById("data-quality-root");
  if (!root) return;

  var DOMAIN_RU = {
    economy: "Экономика",
    income: "Доходы",
    demography: "Демография",
    labor: "Рынок труда",
    infrastructure: "Инфраструктура",
    health_edu: "Здоровье и образование",
    excluded: "Вне аналитики",
  };

  function pct(x) {
    return x == null ? "—" : (Number(x) * 100).toFixed(1) + "%";
  }

  function shell(msg) {
    root.innerHTML = '<div class="shell"><p>' + msg + "</p></div>";
  }

  function bar(value, max) {
    if (value == null || !max) return "";
    var w = Math.max(2, Math.min(100, (value / max) * 100));
    return "<div class='score-bar'><span style='width:" + w + "%'></span></div>";
  }

  // Свернуть строки по ключу: суммируем ячейки сетки/сырья/импутаций, доли — из сумм.
  function rollup(rows, keyFn) {
    var acc = {};
    rows.forEach(function (r) {
      var k = keyFn(r);
      if (k == null) return;
      var a = acc[k] || (acc[k] = { regions: 0, present: 0, imputed: 0, sample: r });
      a.regions += r.n_regions || 0;
      a.present += r.n_present_raw || 0;
      a.imputed += r.n_imputed || 0;
    });
    return Object.keys(acc).map(function (k) {
      var a = acc[k];
      return {
        key: k,
        sample: a.sample,
        completeness_raw: a.regions ? a.present / a.regions : null,
        impute_share: a.regions ? a.imputed / a.regions : null,
      };
    });
  }

  function byYearTable(rows) {
    var agg = rollup(rows, function (r) {
      return r.year;
    }).sort(function (a, b) {
      return Number(a.key) - Number(b.key);
    });
    var head =
      "<tr><th>Год</th><th class='num'>Полнота сырья</th>" +
      "<th class='num'>Импутаций</th></tr>";
    var body = agg
      .map(function (a) {
        return (
          "<tr><td>" + a.key + "</td>" +
          "<td class='num'><strong>" + pct(a.completeness_raw) + "</strong>" +
          bar(a.completeness_raw, 1) + "</td>" +
          "<td class='num'>" + pct(a.impute_share) + "</td></tr>"
        );
      })
      .join("");
    return (
      "<h2>Полнота по годам</h2>" +
      "<p class='chart-note'>Полнота сырья — доля ячеек «регион×метрика» с непустым исходным " +
      "значением Росстата за год (бар к 100%). Импутаций — доля достроенных ячеек " +
      "гармонизированной сетки. 2024 — неполный год: часть индикаторов ещё не вышла.</p>" +
      "<div class='table-wrap'><table class='table'><thead>" + head +
      "</thead><tbody>" + body + "</tbody></table></div>"
    );
  }

  function byDomainTable(rows) {
    var agg = rollup(rows, function (r) {
      return r.domain;
    }).sort(function (a, b) {
      return (b.impute_share || 0) - (a.impute_share || 0);
    });
    var head =
      "<tr><th>Домен</th><th class='num'>Полнота сырья</th>" +
      "<th class='num'>Импутаций</th></tr>";
    var body = agg
      .map(function (a) {
        var label = DOMAIN_RU[a.key] || a.key;
        return (
          "<tr><td>" + label + "</td>" +
          "<td class='num'>" + pct(a.completeness_raw) + "</td>" +
          "<td class='num'><strong>" + pct(a.impute_share) + "</strong></td></tr>"
        );
      })
      .join("");
    return (
      "<h2>Импутации по доменам</h2>" +
      "<p class='chart-note'>Свод по доменам индекса (отсортировано по доле импутаций). " +
      "Различие полноты сырья и импутаций возникает у абсолютных показателей: их пересчёт " +
      "на душу требует населения, и его пропуск даёт импутацию.</p>" +
      "<div class='table-wrap'><table class='table'><thead>" + head +
      "</thead><tbody>" + body + "</tbody></table></div>"
    );
  }

  function byMetricTable(rows) {
    var agg = rollup(rows, function (r) {
      return r.metric_id;
    });
    agg.forEach(function (a) {
      // оконное покрытие сырья по метрике хранится в metric_dim (coverage) — стабильно по годам
      a.coverage = a.sample.coverage;
      a.name = a.sample.metric_name || "#" + a.key;
      a.domain = a.sample.domain;
    });
    agg.sort(function (a, b) {
      return (b.impute_share || 0) - (a.impute_share || 0);
    });
    var maxImp = agg.reduce(function (m, a) {
      return Math.max(m, a.impute_share || 0);
    }, 0);
    var head =
      "<tr><th>Показатель</th><th>Домен</th><th class='num'>Покрытие сырья</th>" +
      "<th class='num'>Импутаций</th></tr>";
    var body = agg
      .map(function (a) {
        return (
          "<tr><td>" + a.name + "</td>" +
          "<td>" + (DOMAIN_RU[a.domain] || a.domain || "—") + "</td>" +
          "<td class='num'>" + pct(a.coverage) + "</td>" +
          "<td class='num'><strong>" + pct(a.impute_share) + "</strong>" +
          bar(a.impute_share, maxImp) + "</td></tr>"
        );
      })
      .join("");
    return (
      "<h2>По показателям ядра</h2>" +
      "<p class='chart-note'>Покрытие сырья — оконная доля заполненных «регион×год» по метрике " +
      "(совпадает с порогом отбора ядра). Импутаций — доля достроенных ячеек (бар нормирован " +
      "по максимуму ряда). Самые проблемные показатели — сверху.</p>" +
      "<div class='table-wrap'><table class='table'><thead>" + head +
      "</thead><tbody>" + body + "</tbody></table></div>"
    );
  }

  function render(rows) {
    if (!rows.length) {
      shell("Нет данных о качестве (хранилище ещё не собрано).");
      return;
    }
    root.innerHTML = byYearTable(rows) + byDomainTable(rows) + byMetricTable(rows);
  }

  shell("Загрузка…");
  fetch("/api/data-quality/")
    .then(function (r) {
      if (!r.ok) throw new Error("Ошибка загрузки (" + r.status + ")");
      return r.json();
    })
    .then(render)
    .catch(function (e) {
      shell(e.message);
    });
})();
