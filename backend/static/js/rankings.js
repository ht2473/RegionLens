/* RegionLens — рейтинг (Ф7, модуль 4).
   Таблица регионов по индексу: /api/index/?year=&scheme= (ранг, индекс, доменные баллы);
   имена берём из /api/regions/. Строка кликабельна → дашборд региона. */

(function () {
  "use strict";

  var root = document.getElementById("rankings-root");
  if (!root) return;

  var DOMAINS = [
    ["economy", "Эк."],
    ["income", "Дох."],
    ["demography", "Дем."],
    ["labor", "Труд"],
    ["infrastructure", "Инфр."],
    ["health_edu", "Здр./обр."],
  ];
  var state = { year: 2024, scheme: "equal" };
  var names = null; // okato -> region_name

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
    root.innerHTML = '<div class="shell"><p>Загрузка рейтинга…</p></div>';
    Promise.all([
      ensureNames(),
      fetch("/api/index/?year=" + state.year + "&scheme=" + state.scheme).then(function (r) {
        if (!r.ok) throw new Error("Ошибка загрузки рейтинга (" + r.status + ")");
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
      root.innerHTML = '<div class="shell"><p>Нет данных за выбранный год.</p></div>';
      return;
    }
    var hasCorr = Array.isArray(robustness);
    var corrMap = {};
    if (hasCorr) robustness.forEach(function (c) { corrMap[c.okato] = c; });

    var head =
      "<tr><th>#</th><th>Регион</th><th class='num'>Индекс</th>" +
      DOMAINS.map(function (d) { return "<th class='num' title='" + d[0] + "'>" + d[1] + "</th>"; }).join("") +
      (hasCorr ? "<th class='num' title='Разброс места по всем схемам весов'>Коридор</th>" : "") +
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
              "<td class='" + cls + "' title='По схемам весов: с " + c.rank_best + " по " +
              c.rank_worst + " место (коридор " + c.rank_range + ")'>" + txt + "</td>";
          } else {
            corrCell = "<td class='num'>—</td>";
          }
        }
        return (
          "<tr data-okato='" + r.okato + "'><td class='num'>" + r.rank + "</td>" +
          "<td>" + nm + "</td>" +
          "<td class='num'><strong>" + num(r.total_score, 1) + "</strong>" + bar + "</td>" +
          domains + corrCell + "</tr>"
        );
      })
      .join("");
    var note = hasCorr
      ? "<p class='chart-note'>«Коридор» — место региона по разным схемам весов " +
        "(равные / PCA / экспертные): чем шире, тем сильнее ранг зависит от выбора весов, " +
        "а не от самих данных.</p>"
      : "";
    root.innerHTML =
      "<div class='table-wrap'><table class='table rankings'><thead>" +
      head + "</thead><tbody>" + body + "</tbody></table></div>" + note;
    root.querySelectorAll("tr[data-okato]").forEach(function (tr) {
      tr.addEventListener("click", function () {
        window.location.href = "/regions/" + tr.dataset.okato + "/?year=" + state.year;
      });
    });
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
