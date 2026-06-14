/* RegionLens — стабильность рейтинга (Ф14, модуль 3).
   Волатильность ранга регионов: /api/rank-stability/?scheme=
   (rank_mean, rank_std, rank_min/max/range, mean_abs_change). Бар на σ ранга нормирован по
   максимуму выборки — длиннее = «дёрганнее». Стабильные регионы — сверху. Без обёртки .card. */

(function () {
  "use strict";

  var root = document.getElementById("rank-stability-root");
  var scheme = document.getElementById("scheme-select");
  if (!root || !scheme) return;

  function num(x, d) {
    return x == null ? "—" : Number(x).toFixed(d == null ? 2 : d);
  }

  function int(x) {
    return x == null ? "—" : x;
  }

  function shell(msg) {
    root.innerHTML = '<div class="shell"><p>' + msg + "</p></div>";
  }

  function load() {
    shell("Загрузка…");
    fetch("/api/rank-stability/?scheme=" + encodeURIComponent(scheme.value))
      .then(function (r) {
        if (!r.ok) throw new Error("Ошибка загрузки (" + r.status + ")");
        return r.json();
      })
      .then(function (rows) {
        render(rows);
      })
      .catch(function (e) {
        shell(e.message);
      });
  }

  function render(rows) {
    if (!rows.length) {
      shell("Нет данных стабильности рейтинга. Пересоберите конвейер (стадия rank_stability).");
      return;
    }
    var stds = rows
      .map(function (r) {
        return r.rank_std;
      })
      .filter(function (v) {
        return v != null;
      });
    var maxStd = stds.length ? Math.max.apply(null, stds) : 0;

    var head =
      "<tr><th>Регион</th><th class='num'>Лет</th><th class='num'>Ср. ранг</th>" +
      "<th class='num'>σ ранга</th><th class='num'>Мин</th><th class='num'>Макс</th>" +
      "<th class='num'>Размах</th><th class='num'>Ср. |Δ| за год</th></tr>";

    var body = rows
      .map(function (r) {
        var bar = "";
        if (r.rank_std != null && maxStd > 0) {
          var w = Math.max(2, Math.min(100, (r.rank_std / maxStd) * 100));
          bar = "<div class='score-bar'><span style='width:" + w + "%'></span></div>";
        }
        return (
          "<tr><td>" + (r.region_name || r.okato) + "</td>" +
          "<td class='num'>" + int(r.n_years) + "</td>" +
          "<td class='num'>" + num(r.rank_mean, 1) + "</td>" +
          "<td class='num'><strong>" + num(r.rank_std) + "</strong>" + bar + "</td>" +
          "<td class='num'>" + int(r.rank_min) + "</td>" +
          "<td class='num'>" + int(r.rank_max) + "</td>" +
          "<td class='num'>" + int(r.rank_range) + "</td>" +
          "<td class='num'>" + num(r.mean_abs_change) + "</td></tr>"
        );
      })
      .join("");

    root.innerHTML =
      "<p class='chart-note'>σ ранга и средний |Δ| за год — мера «дёрганности» места в рейтинге: " +
      "0 означает, что регион не двигался. Бар нормирован по максимуму в выборке; сортировка — " +
      "от самых стабильных к самым подвижным.</p>" +
      "<div class='table-wrap'><table class='table'><thead>" +
      head +
      "</thead><tbody>" +
      body +
      "</tbody></table></div>";
  }

  scheme.addEventListener("change", load);
  load();
})();
