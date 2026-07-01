// Глобальный поиск по сайту (поле-палитра в шапке). Открывается иконкой, Ctrl/⌘+K или «/».
// Запрашивает /api/search/?q= (дебаунс), показывает регионы, показатели и страницы группами;
// клик/Enter ведёт на нужную страницу. Чистый ванильный JS, без зависимостей.
(function () {
  "use strict";

  var overlay, input, results, debounce;
  var items = []; // плоский список текущих результатов для клавиатуры
  var active = -1;

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // metric_name иногда вида «X: X» — схлопываем дубль для читаемости.
  function cleanLabel(s) {
    var p = String(s).split(": ");
    if (p.length === 2 && p[0] === p[1]) return p[0];
    return s;
  }

  function mark(label, q) {
    if (!q) return esc(label);
    var i = label.toLowerCase().indexOf(q.toLowerCase());
    if (i < 0) return esc(label);
    return (
      esc(label.slice(0, i)) +
      "<mark>" +
      esc(label.slice(i, i + q.length)) +
      "</mark>" +
      esc(label.slice(i + q.length))
    );
  }

  function setHint(text) {
    if (results) results.innerHTML = '<div class="search-hint">' + esc(text) + "</div>";
    items = [];
    active = -1;
  }

  window.rlOpenSearch = function () {
    overlay = document.getElementById("site-search");
    if (!overlay) return;
    input = document.getElementById("site-search-input");
    results = document.getElementById("site-search-results");
    overlay.hidden = false;
    document.body.classList.add("search-open");
    input.value = "";
    setHint(gettext("Начните вводить: регион, показатель или страница"));
    input.setAttribute("aria-expanded", "true");
    setTimeout(function () {
      input.focus();
    }, 30);
  };

  window.rlCloseSearch = function () {
    if (!overlay) overlay = document.getElementById("site-search");
    if (overlay) {
      overlay.hidden = true;
      if (input) input.setAttribute("aria-expanded", "false");
    }
    document.body.classList.remove("search-open");
  };

  function optHtml(it, q) {
    var sub = it.sub ? '<span class="search-sub">' + esc(it.sub) + "</span>" : "";
    return (
      '<span class="search-opt-main"><span class="search-opt-label">' +
      mark(it.label, q) +
      "</span>" +
      sub +
      '</span><span class="search-kind">' +
      esc(it.kind) +
      "</span>"
    );
  }

  function render(data, q) {
    items = [];
    active = -1;
    var html = "";

    function group(title, arr) {
      if (!arr.length) return;
      html += '<div class="search-group">' + esc(title) + "</div>";
      arr.forEach(function (it) {
        var i = items.length;
        items.push(it);
        html +=
          '<a class="search-opt" data-i="' + i + '" href="' + esc(it.url) + '" role="option">' +
          optHtml(it, q) +
          "</a>";
      });
    }

    group(
      gettext("Регионы"),
      (data.regions || []).map(function (r) {
        return {
          label: r.region_name,
          sub: RL.localizeFederalDistrict(r.federal_district),
          url: "/regions/" + r.okato + "/",
          kind: gettext("регион"),
        };
      })
    );
    group(
      gettext("Показатели"),
      (data.metrics || []).map(function (m) {
        return {
          label: cleanLabel(m.metric_name),
          sub: m.unit,
          url: "/explore/?metric=" + m.metric_id,
          kind: gettext("показатель"),
        };
      })
    );
    group(
      gettext("Страницы"),
      (data.pages || []).map(function (p) {
        return { label: p.title, sub: null, url: p.url, kind: gettext("страница") };
      })
    );

    if (!items.length) {
      results.innerHTML =
        '<div class="search-empty">' +
        interpolate(gettext("Ничего не найдено по запросу «%(q)s»"), { q: esc(q) }, true) +
        "</div>";
      return;
    }
    results.innerHTML = html;
  }

  function fetchResults(q) {
    fetch("/api/search/?q=" + encodeURIComponent(q), { headers: { Accept: "application/json" } })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (input.value.trim() === q) render(d, q);
      })
      .catch(function () {
        if (results)
          results.innerHTML =
            '<div class="search-empty">' + gettext("Не удалось выполнить поиск") + "</div>";
      });
  }

  function onInput() {
    var q = input.value.trim();
    clearTimeout(debounce);
    if (q.length < 2) {
      setHint(gettext("Введите минимум 2 символа"));
      return;
    }
    debounce = setTimeout(function () {
      fetchResults(q);
    }, 180);
  }

  function move(d) {
    var opts = results.querySelectorAll(".search-opt");
    if (!opts.length) return;
    active = (active + d + opts.length) % opts.length;
    for (var i = 0; i < opts.length; i++) opts[i].classList.toggle("is-active", i === active);
    opts[active].scrollIntoView({ block: "nearest" });
  }

  function go(i) {
    if (items[i]) window.location.href = items[i].url;
  }

  function isTypingTarget(t) {
    if (!t || !t.tagName) return false;
    return /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable;
  }

  document.addEventListener("keydown", function (e) {
    var open = overlay && !overlay.hidden;
    if (!open) {
      var hotK = (e.key === "k" || e.key === "K") && (e.ctrlKey || e.metaKey);
      var hotSlash = e.key === "/" && !isTypingTarget(e.target);
      if (hotK || hotSlash) {
        e.preventDefault();
        window.rlOpenSearch();
      }
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      window.rlCloseSearch();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      move(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      move(-1);
    } else if (e.key === "Enter") {
      if (active >= 0) {
        e.preventDefault();
        go(active);
      } else if (items.length) {
        e.preventDefault();
        go(0);
      }
    }
  });

  document.addEventListener("input", function (e) {
    if (e.target && e.target.id === "site-search-input") onInput();
  });
})();
