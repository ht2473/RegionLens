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
})();
