/* RegionLens — обзор типологии (Ф7, модуль 5).
   /api/typology/?year= → принадлежность регионов к типам; группируем по типу и для каждого
   тянем /api/typology/profile/?year=&cluster_id= (профиль: средний z метрик). Карточка типа:
   метка, число регионов, мини-бары характерных метрик, чипы регионов (типичные → пограничные).
   Имена регионов — из /api/regions/. distance_to_centroid — типичность, не прогноз. */

(function () {
  "use strict";

  var root = document.getElementById("typology-root");
  if (!root) return;

  var PALETTE = ["#c46a3f", "#1f6f63", "#3b6ea5", "#8a6fab", "#b0a44e"];
  var POS = "#1f6f63", NEG = "#b4532a", INK = "#1b2430", GRID = "#e9e3d6";
  var state = { year: 2024 };
  var names = null;

  // Подпись метрики: схлопнуть дубликат «X: X» (артефакт metric_name). 
  function cleanLabel(name) {
    if (!name) return "";
    var p = name.split(": ");
    return p.length === 2 && p[0].trim() === p[1].trim() ? p[0].trim() : name;
  }
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

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
    root.innerHTML = '<div class="shell"><p>' + gettext("Загрузка типологии…") + "</p></div>";
    Promise.all([
      ensureNames(),
      fetch("/api/typology/?year=" + state.year).then(function (r) {
        if (!r.ok) throw new Error(gettext("Ошибка загрузки типологии") + " (" + r.status + ")");
        return r.json();
      }),
    ])
      .then(function (out) { render(out[1]); })
      .catch(function (e) { root.innerHTML = '<div class="shell"><p>' + RL.errText(e) + "</p></div>"; });
  }

  function render(rows) {
    if (!rows.length) {
      root.innerHTML = '<div class="shell"><p>' + gettext("Нет данных за выбранный год.") + "</p></div>";
      return;
    }
    var groups = {};
    rows.forEach(function (r) {
      var cid = r.cluster_id;
      if (!groups[cid]) groups[cid] = { cid: cid, label: r.cluster_label || gettext("тип") + " " + cid, items: [] };
      groups[cid].items.push(r);
    });
    var cids = Object.keys(groups).sort(function (a, b) { return a - b; });

    // Сводка: число регионов по типам
    var summary =
      "<div class='type-summary'>" +
      cids
        .map(function (cid) {
          return (
            "<span class='type-pill'><span class='swatch' style='background:" +
            (PALETTE[cid] || "#ccc") + "'></span>" + groups[cid].label +
            " · <strong>" + groups[cid].items.length + "</strong></span>"
          );
        })
        .join("") +
      "</div>";

    var cards = cids
      .map(function (cid) {
        var g = groups[cid];
        g.items.sort(function (a, b) {
          return (a.distance_to_centroid || 0) - (b.distance_to_centroid || 0);
        });
        var chips = g.items
          .map(function (r) {
            return "<a class='region-chip sm' href='/regions/" + r.okato + "/?year=" + state.year + "'>" +
              ((names && names[r.okato]) || r.okato) + "</a>";
          })
          .join("");
        return (
          "<div class='card type-card'>" +
          "<h3><span class='swatch' style='background:" + (PALETTE[cid] || "#ccc") + "'></span>" +
          g.label + " <span class='type-count'>" + g.items.length + " " + gettext("регионов") + "</span></h3>" +
          "<div id='profile-" + cid + "' class='chart profile-chart'></div>" +
          "<p class='chart-note'>" + gettext("Регионы (от типичных к пограничным):") + "</p>" +
          "<div class='region-grid sm'>" + chips + "</div>" +
          "</div>"
        );
      })
      .join("");

    root.innerHTML = summary + "<div class='grid cols-2 type-grid'>" + cards + "</div>";
    cids.forEach(function (cid) { drawProfile(cid); });
  }

  function drawProfile(cid) {
    fetch("/api/typology/profile/?year=" + state.year + "&cluster_id=" + cid)
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (rows) {
        var el = document.getElementById("profile-" + cid);
        if (!el) return;
        if (!rows.length) { el.innerHTML = '<p class="chart-note">' + gettext("Нет профиля.") + "</p>"; return; }
        var top = rows.slice(0, 6); // крупнейший |mean_z| первым (API сортирует по убыванию)
        var maxAbs = Math.max.apply(null, top.map(function (m) { return Math.abs(m.mean_z); })) || 1;
        var html = top
          .map(function (m) {
            var z = m.mean_z;
            var pos = z >= 0;
            var pct = (Math.abs(z) / maxAbs) * 48; // доля полуширины (до края с запасом)
            var fill = pos
              ? '<span class="pbar-fill pos" style="left:50%;width:' + pct.toFixed(1) + '%"></span>'
              : '<span class="pbar-fill neg" style="right:50%;width:' + pct.toFixed(1) + '%"></span>';
            return (
              '<div class="pbar-row">' +
              '<div class="pbar-name">' + esc(cleanLabel(m.metric_name || "metric " + m.metric_id)) + "</div>" +
              '<div class="pbar-line"><div class="pbar-track">' + fill + "</div>" +
              '<span class="pbar-val">' + (pos ? "+" : "") + z.toFixed(2) + "</span></div>" +
              "</div>"
            );
          })
          .join("");
        el.innerHTML = '<div class="pbars">' + html + "</div>";
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

  load();
})();
