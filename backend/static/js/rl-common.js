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
})();
