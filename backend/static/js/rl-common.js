/* RegionLens — общий клиентский помощник (Фаза 3).
   Подключается из base.html ДО постраничных скриптов, доступен как window.RL.
   Назначение — единый понятный текст ошибки на всех страницах: сетевой сбой (fetch отклонён,
   сервер недоступен, база не собрана) больше не показывает сырое браузерное «Failed to fetch». */

(function () {
  "use strict";
  window.RL = window.RL || {};

  // Сетевой сбой → fetch отклоняется с TypeError: даёт дружелюбное сообщение. Наши HTTP-ошибки
  // (new Error с кодом статуса) сохраняют свой текст. Иначе — общий безопасный текст.
  window.RL.errText = function (err) {
    if (err instanceof TypeError) {
      return (
        "Не удалось связаться с сервером. Проверьте соединение и что хранилище данных собрано, " +
        "затем обновите страницу."
      );
    }
    return (err && err.message) || "Произошла ошибка. Обновите страницу.";
  };

  // Текущее значение CSS-переменной темы (для графиков/карты — чтобы цвета следовали теме).
  // Читается при построении графика; data-theme к этому моменту уже выставлен скриптом в <head>.
  window.RL.cssVar = function (name, fallback) {
    try {
      var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return v || fallback;
    } catch (e) {
      return fallback;
    }
  };

  // Мгновенная перекраска при смене темы. Карты регистрируют хук через RL.onTheme(fn);
  // графики Plotly перекрашиваются обобщённо (без правки каждого файла). Вызывается из rlToggleTheme.
  window.RL._themeHooks = window.RL._themeHooks || [];
  window.RL.onTheme = function (fn) {
    if (typeof fn === "function") window.RL._themeHooks.push(fn);
  };

  function rethemePlotly() {
    if (typeof Plotly === "undefined" || !Plotly.relayout) return;
    var ink = window.RL.cssVar("--ink-soft", "#51606e");
    var grid = window.RL.cssVar("--line-soft", "#e9e3d6");
    var line = window.RL.cssVar("--line", "#b9c2cb");
    var nodes = document.querySelectorAll(".js-plotly-plot");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var fl = el._fullLayout;
      if (!fl) continue;
      var up = { "font.color": ink };
      for (var k in fl) {
        if (k.indexOf("xaxis") === 0 || k.indexOf("yaxis") === 0) {
          up[k + ".gridcolor"] = grid;
          up[k + ".zerolinecolor"] = line;
        }
      }
      if (fl.polar) {
        up["polar.radialaxis.gridcolor"] = grid;
        up["polar.angularaxis.gridcolor"] = grid;
      }
      try {
        Plotly.relayout(el, up);
      } catch (e) {}
    }
  }

  window.RL.applyTheme = function () {
    rethemePlotly();
    for (var i = 0; i < window.RL._themeHooks.length; i++) {
      try {
        window.RL._themeHooks[i]();
      } catch (e) {}
    }
  };

  // Поисковый комбобокс поверх <select>: печатаешь — список фильтруется. Значение и событие
  // change самого <select> сохраняются, поэтому существующая логика страниц не меняется.
  // Идемпотентно; опции читаются из <select> «вживую», так что асинхронное заполнение поддержано.
  window.RL.enhanceSelect = function (select, placeholder) {
    if (!select || select._rlCombo) return;
    select._rlCombo = true;
    select.style.display = "none";

    var wrap = document.createElement("div");
    wrap.className = "combo";
    var field = document.createElement("div");
    field.className = "combo-field";
    var input = document.createElement("input");
    input.type = "text";
    input.className = "combo-input";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.placeholder = placeholder || "Выберите или введите для поиска…";
    var caret = document.createElement("span");
    caret.className = "combo-caret";
    caret.setAttribute("aria-hidden", "true");
    caret.textContent = "▾";
    field.appendChild(input);
    field.appendChild(caret);
    var list = document.createElement("div");
    list.className = "combo-list";
    list.setAttribute("role", "listbox");
    list.hidden = true;
    wrap.appendChild(field);
    wrap.appendChild(list);
    select.parentNode.insertBefore(wrap, select.nextSibling);

    var filtered = [];
    var active = -1;

    function esc(s) {
      return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }
    function options() {
      return Array.prototype.map
        .call(select.options, function (o) {
          return { value: o.value, label: o.textContent };
        })
        .sort(function (a, b) {
          return a.label.localeCompare(b.label, "ru");
        });
    }
    function syncInput() {
      var o = select.options[select.selectedIndex];
      input.value = o ? o.textContent : "";
      input.title = o ? o.textContent : "";
      try {
        input.setSelectionRange(0, 0);
      } catch (e) {}
      input.scrollLeft = 0;
    }
    function mark(label, q) {
      if (!q) return esc(label);
      var i = label.toLowerCase().indexOf(q);
      if (i < 0) return esc(label);
      return (
        esc(label.slice(0, i)) +
        "<mark>" +
        esc(label.slice(i, i + q.length)) +
        "</mark>" +
        esc(label.slice(i + q.length))
      );
    }
    function render(q) {
      q = (q || "").toLowerCase().trim();
      filtered = options()
        .filter(function (o) { return o.label.toLowerCase().indexOf(q) >= 0; })
        .slice(0, 100);
      active = -1;
      if (!filtered.length) {
        list.innerHTML = '<div class="combo-empty">Ничего не найдено</div>';
        return;
      }
      list.innerHTML = filtered
        .map(function (o, i) {
          var cur = o.value === select.value ? " is-current" : "";
          return (
            '<div class="combo-opt' + cur + '" role="option" title="' + esc(o.label) + '" data-i="' + i + '">' +
            mark(o.label, q) +
            "</div>"
          );
        })
        .join("");
    }
    function openAll() {
      input.select();
      render("");
      list.hidden = false;
      wrap.classList.add("open");
      input.setAttribute("aria-expanded", "true");
      var cur = list.querySelector(".combo-opt.is-current");
      if (cur) cur.scrollIntoView({ block: "nearest" });
    }
    function close() {
      list.hidden = true;
      wrap.classList.remove("open");
      input.setAttribute("aria-expanded", "false");
      active = -1;
    }
    function choose(opt) {
      if (!opt) return;
      select.value = opt.value;
      syncInput();
      close();
      select.dispatchEvent(new Event("change", { bubbles: true }));
      input.blur();
    }
    function move(d) {
      var els = list.querySelectorAll(".combo-opt");
      if (!els.length) return;
      active = (active + d + els.length) % els.length;
      for (var i = 0; i < els.length; i++) els[i].classList.toggle("is-active", i === active);
      els[active].scrollIntoView({ block: "nearest" });
    }

    input.addEventListener("focus", openAll);
    caret.addEventListener("mousedown", function (e) {
      e.preventDefault();
      if (list.hidden) {
        input.focus();
        openAll();
      } else {
        close();
        syncInput();
      }
    });
    input.addEventListener("input", function () {
      render(input.value);
      list.hidden = false;
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); if (list.hidden) openAll(); else move(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === "Enter") {
        e.preventDefault();
        if (active >= 0) choose(filtered[active]);
        else if (filtered.length === 1) choose(filtered[0]);
      } else if (e.key === "Escape") { close(); syncInput(); }
    });
    list.addEventListener("mousedown", function (e) {
      var t = e.target.closest ? e.target.closest(".combo-opt") : null;
      if (t) { e.preventDefault(); choose(filtered[+t.getAttribute("data-i")]); }
    });
    document.addEventListener("click", function (e) {
      if (!wrap.contains(e.target)) { close(); syncInput(); }
    });
    select.addEventListener("change", syncInput);

    syncInput();
  };
})();
