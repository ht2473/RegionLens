/* RegionLens — общий клиентский помощник.
   Подключается из base.html ДО постраничных скриптов, доступен как window.RL.
   Назначение — единый понятный текст ошибки на всех страницах: сетевой сбой (fetch отклонён,
   сервер недоступен, база не собрана) больше не показывает сырое браузерное «Failed to fetch». */

(function () {
  "use strict";
  window.RL = window.RL || {};

  // Защитный фолбэк: каталог переводов JS (jsi18n) подключается раньше и определяет gettext.
  // Если он по какой-то причине не загрузился — возвращаем исходную (русскую) строку.
  if (typeof window.gettext !== "function") {
    window.gettext = function (s) {
      return s;
    };
  }

  // Сетевой сбой → fetch отклоняется с TypeError: даёт дружелюбное сообщение. Наши HTTP-ошибки
  // (new Error с кодом статуса) сохраняют свой текст. Иначе — общий безопасный текст.
  window.RL.errText = function (err) {
    if (err instanceof TypeError) {
      return gettext(
        "Не удалось связаться с сервером. Проверьте соединение и что хранилище данных собрано, затем обновите страницу."
      );
    }
    return (err && err.message) || gettext("Произошла ошибка. Обновите страницу.");
  };

  // Текущее значение CSS-переменной темы (для графиков/карты — чтобы цвета следовали теме).
  // Читается при построении графика; data-theme к этому моменту уже выставлен скриптом в <head>.
  // Локализация названий федеральных округов: в данных они хранятся по-русски,
  // здесь переводятся по активному языку через каталог jsi18n (для EN-интерфейса).
  var _fdMap = null;
  window.RL.localizeFederalDistrict = function (name) {
    if (!name) return name;
    if (_fdMap === null) {
      _fdMap = {
        "Дальневосточный": gettext("Дальневосточный"),
        "Приволжский": gettext("Приволжский"),
        "Северо-Западный": gettext("Северо-Западный"),
        "Северо-Кавказский": gettext("Северо-Кавказский"),
        "Сибирский": gettext("Сибирский"),
        "Уральский": gettext("Уральский"),
        "Центральный": gettext("Центральный"),
        "Южный": gettext("Южный"),
      };
    }
    return _fdMap[name] || name;
  };

  // CSRF-токен из cookie (Django) — для операционных POST-запросов из JS (избранное и т.п.).
  window.RL.csrfToken = function () {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  };

  // Переключить закладку (регион/показатель). Возвращает промис с { favorited, count }.
  window.RL.toggleFavorite = function (kind, ref, label) {
    var body = new URLSearchParams({ kind: kind, ref: String(ref), label: label || "" });
    return fetch("/account/favorites/toggle/", {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRFToken": window.RL.csrfToken(),
        "X-Requested-With": "XMLHttpRequest",
      },
      body: body.toString(),
    }).then(function (r) {
      if (!r.ok) throw new Error("favorite toggle failed");
      return r.json();
    });
  };

  // Разрешение начальных значений контролов: URL-параметр > предпочтение (RL_PREFS) > запасное.
  window.RL.prefYear = function (fallback) {
    var u = parseInt(new URLSearchParams(window.location.search).get("year"), 10);
    if (u >= 2010 && u <= 2024) return u;
    var pref = window.RL_PREFS && RL_PREFS.year;
    return pref >= 2010 && pref <= 2024 ? pref : fallback;
  };
  window.RL.prefScheme = function (fallback) {
    var p = new URLSearchParams(window.location.search).get("scheme");
    if (p === "equal" || p === "pca" || p === "expert") return p;
    var pref = window.RL_PREFS && RL_PREFS.scheme;
    return pref || fallback;
  };
  window.RL.prefMeasure = function (fallback) {
    var p = new URLSearchParams(window.location.search).get("measure");
    if (p === "cluster" || p === "index") return p;
    var pref = window.RL_PREFS && RL_PREFS.measure;
    return pref || fallback;
  };
  // Синхронизировать стандартный ползунок года и его подпись с разрешённым значением.
  window.RL.syncYearControl = function (year) {
    var slider = document.getElementById("year-slider");
    var label = document.getElementById("year-label");
    if (slider) slider.value = year;
    if (label) label.textContent = year;
  };

  // Кнопка «Скопировать ссылку»: копирует текущий URL (со всем состоянием страницы в query)
  // в буфер обмена и на ~1.5 с показывает подтверждение. Принимает элемент или его id;
  // если кнопки нет — тихо ничего не делает. Единый помощник для deep-link-страниц.
  window.RL.wireCopyLink = function (el) {
    var btn = typeof el === "string" ? document.getElementById(el) : el;
    if (!btn) return;
    btn.addEventListener("click", function () {
      var prev = btn.textContent;
      var flash = function () {
        btn.textContent = typeof gettext === "function" ? gettext("Ссылка скопирована") : "Ссылка скопирована";
        setTimeout(function () {
          btn.textContent = prev;
        }, 1500);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(window.location.href).then(flash, flash);
      } else {
        flash();
      }
    });
  };

  // Развернуть антимеридиан в geojson России: восточная часть Чукотки лежит в отрицательных
  // долготах (-180..-169), из-за чего bbox данных формально охватывает весь мир (360°) — ломается
  // подгонка кадра и ограничение панорамы, а сама Чукотка рвётся по линии 180°. Сдвигаем
  // отрицательные долготы на +360 (в России нет территорий с lng < 0 западнее Чукотки), получая
  // непрерывный диапазон ~19..191. Мутирует и возвращает переданный объект. Идемпотентно.
  window.RL.unwrapGeojson = function (geo) {
    if (!geo || geo._rlUnwrapped) return geo;
    geo._rlUnwrapped = true;
    var shift = function (c) {
      if (typeof c[0] === "number") {
        if (c[0] < 0) c[0] += 360;
      } else {
        for (var i = 0; i < c.length; i++) shift(c[i]);
      }
    };
    (geo.features || []).forEach(function (f) {
      if (f.geometry && f.geometry.coordinates) shift(f.geometry.coordinates);
    });
    return geo;
  };

  // Кадрировать карту по границам данных с отступами: Россия всегда вписывается в контейнер
  // ровно, без «обрезанного» вида, и подстраивается под любой размер/пропорции вкладки.
  // Защита от антимеридиана: если размах долгот неадекватный (geojson в диапазоне -180..180),
  // подгонку пропускаем — остаётся заданный center/zoom.
  window.RL.fitToData = function (map, geo, padding) {
    try {
      var minLng = Infinity,
        minLat = Infinity,
        maxLng = -Infinity,
        maxLat = -Infinity;
      var scan = function (c) {
        if (typeof c[0] === "number") {
          if (c[0] < minLng) minLng = c[0];
          if (c[0] > maxLng) maxLng = c[0];
          if (c[1] < minLat) minLat = c[1];
          if (c[1] > maxLat) maxLat = c[1];
        } else {
          for (var i = 0; i < c.length; i++) scan(c[i]);
        }
      };
      (geo.features || []).forEach(function (f) {
        if (f.geometry && f.geometry.coordinates) scan(f.geometry.coordinates);
      });
      if (minLng < maxLng && minLat < maxLat && maxLng - minLng < 210) {
        map.fitBounds(
          [
            [minLng, minLat],
            [maxLng, maxLat],
          ],
          { padding: padding == null ? 24 : padding, animate: false }
        );
        // Зафиксировать рамки взаимодействия по фактически видимой области после подгонки:
        // maxBounds = getBounds() и minZoom = текущий зум. Панорамой нельзя открыть пустоту
        // за пределами исходного кадра, а отдалиться дальше стартового вида невозможно —
        // пустые полосы по краям исключены в принципе.
        try {
          map.setMaxBounds(map.getBounds());
          if (map.getZoom) map.setMinZoom(map.getZoom());
        } catch (e2) {
          /* ограничения недоступны — не критично */
        }
        // Держать кадрирование при изменении размера контейнера (один наблюдатель на карту).
        var cont = map.getContainer && map.getContainer();
        if (cont && window.ResizeObserver && !cont._rlFitRO) {
          var raf = null;
          cont._rlFitRO = new ResizeObserver(function () {
            if (raf) cancelAnimationFrame(raf);
            raf = requestAnimationFrame(function () {
              try {
                // Снять ограничения на время перекадрирования, затем зафиксировать под новый кадр.
                map.setMaxBounds(null);
                map.setMinZoom(0);
                map.resize();
                map.fitBounds(
                  [
                    [minLng, minLat],
                    [maxLng, maxLat],
                  ],
                  { padding: padding == null ? 24 : padding, animate: false }
                );
                map.setMaxBounds(map.getBounds());
                map.setMinZoom(map.getZoom());
              } catch (e3) {}
            });
          });
          cont._rlFitRO.observe(cont);
        }
      }
    } catch (e) {
      /* нет данных/границ — оставляем заданный вид */
    }
  };

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

  // Единое поведение карт при наведении: подсветка границ субъекта под курсором и
  // подсказка без «мерцания». Добавляет к карте линейный слой-подсветку (если его ещё нет)
  // и обновляет его фильтр по наведённому региону. Подсказку перепозиционирует на каждом
  // движении, но переписывает её содержимое только при смене региона — иначе повторные
  // mousemove пересобирают DOM и вызывают дрожание. Петля mouseleave→mousemove исключена
  // тем, что попап не перехватывает мышь (pointer-events:none в CSS).
  // Параметры: { source, layer, key, highlightId, popup, html(props)->string, onEnter, onLeave }.
  // Сделать легенду карты сворачиваемой: JS сам добавляет кнопку −/+ и оборачивает содержимое,
  // поэтому шаблоны страниц менять не нужно. Идемпотентно.
  // Смягчить шаг кнопок зума +/− (у NavigationControl в MapLibre шаг фиксированный = 1):
  // заменяем обработчики кнопок на плавный easeTo с шагом ±0.5. Идемпотентно.
  window.RL.softenZoomControls = function (map, step) {
    step = step || 0.5;
    var cont = map.getContainer && map.getContainer();
    if (!cont || cont._rlSoftZoom) return;
    cont._rlSoftZoom = true;
    var rebind = function (sel, dir) {
      var btn = cont.querySelector(sel);
      if (!btn) return;
      var clone = btn.cloneNode(true); // снять штатные обработчики
      btn.parentNode.replaceChild(clone, btn);
      clone.addEventListener("click", function (e) {
        e.preventDefault();
        map.easeTo({ zoom: map.getZoom() + dir * step, duration: 200 });
      });
    };
    rebind(".maplibregl-ctrl-zoom-in", 1);
    rebind(".maplibregl-ctrl-zoom-out", -1);
  };

  window.RL.makeLegendCollapsible = function (el) {
    if (!el || el._rlCollapsible) return;
    el._rlCollapsible = true;
    var body = document.createElement("div");
    body.className = "map-legend-body";
    while (el.firstChild) body.appendChild(el.firstChild);
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "map-legend-toggle";
    btn.textContent = "−";
    btn.setAttribute("aria-label", gettext("Скрыть или показать легенду"));
    btn.title = gettext("Скрыть или показать легенду");
    btn.addEventListener("click", function () {
      var col = el.classList.toggle("collapsed");
      btn.textContent = col ? "+" : "−";
    });
    el.appendChild(btn);
    el.appendChild(body);
  };

  window.RL.attachMapHover = function (map, opts) {
    opts = opts || {};
    // Идемпотентность: повторный вызов на той же карте (напр. после перезагрузки данных) не
    // должен навешивать ещё один обработчик mousemove — иначе попапы дублируются и мигают.
    if (map._rlHoverAttached) return;
    map._rlHoverAttached = true;
    var source = opts.source || "regions";
    var layer = opts.layer || "fill";
    var key = opts.key || "okato";
    var hlId = opts.highlightId || "hl";
    var popup = opts.popup || null;
    var htmlFor = typeof opts.html === "function" ? opts.html : null;
    var none = ["==", ["get", key], "__none__"];

    if (!map.getLayer(hlId)) {
      map.addLayer({
        id: hlId,
        type: "line",
        source: source,
        paint: {
          "line-color": window.RL.cssVar("--map-hover", window.RL.cssVar("--accent", "#1f6f63")),
          "line-width": 2.4,
        },
        filter: none,
      });
      // Цвет подсветки следует активной теме.
      window.RL.onTheme(function () {
        try {
          if (map.getLayer(hlId)) {
            map.setPaintProperty(
              hlId,
              "line-color",
              window.RL.cssVar("--map-hover", window.RL.cssVar("--accent", "#1f6f63"))
            );
          }
        } catch (e) {}
      });
    }

    var current = null;
    map.on("mousemove", layer, function (e) {
      map.getCanvas().style.cursor = "pointer";
      var props = e.features[0].properties;
      var k = props[key];
      // Вместо попапа MapLibre — общий DOM-тултип по координатам курсора: попап MapLibre при
      // обновлении содержимого на кадр вспыхивал в углу карты (мерцание/«дубли»), DOM-тултип
      // от геометрии карты не зависит и позиционируется мгновенно.
      if (htmlFor && e.originalEvent) {
        window.RL.tipShowAt(htmlFor(props), e.originalEvent.clientX, e.originalEvent.clientY);
      }
      if (k !== current) {
        map.setFilter(hlId, ["==", ["get", key], k == null ? "__none__" : k]);
        if (typeof opts.onEnter === "function") opts.onEnter(k, props);
        current = k;
      }
    });
    map.on("mouseleave", layer, function () {
      map.getCanvas().style.cursor = "";
      window.RL.tipHide();
      if (popup) popup.remove();
      map.setFilter(hlId, none);
      current = null;
      if (typeof opts.onLeave === "function") opts.onLeave();
    });
  };

  // Конфигурация базовой карты субъектов РФ (объект для конструктора maplibregl.Map).
  // Единые для всех страниц значения: пустой стиль без внешних тайлов (рисуем только
  // полигоны из geojson), фон-подложка по теме, центр и рамки панорамы по территории
  // страны, антимеридиан не копируем (renderWorldCopies=false). Переопределяемы zoom и
  // minZoom — рейтингу нужен более общий стартовый план, чем детальным картам.
  // Чистая функция (без обращения к DOM/MapLibre, кроме чтения CSS-переменной темы) —
  // удобно тестировать отдельно от браузера.
  window.RL.regionMapConfig = function (opts) {
    opts = opts || {};
    return {
      container: opts.container,
      style: {
        version: 8,
        sources: {},
        layers: [
          { id: "bg", type: "background", paint: { "background-color": window.RL.cssVar("--map-bg", "#eaf0f1") } },
        ],
      },
      center: [99, 66],
      zoom: opts.zoom == null ? 2 : opts.zoom,
      minZoom: opts.minZoom == null ? 1.6 : opts.minZoom,
      maxBounds: [[5, 25], [205, 86]],
      renderWorldCopies: false,
      attributionControl: false,
    };
  };

  // Фабрика хороплета субъектов РФ: единая инициализация, общая для всех карт приложения
  // (обзор, аномалии, обзор показателей, рейтинг). Раньше этот блок дублировался в четырёх
  // файлах; здесь он один, а различия страниц вынесены в опции и хуки. Карта создаётся
  // синхронно и сразу возвращается ({ map, popup }) — постраничные обработчики (слайдер года,
  // кнопки) навешиваются на неё до события load. Загрузка geojson, добавление слоёв заливки
  // и контура, кадрирование, смягчение зума, сворачивание легенды и базовая реакция на тему
  // (фон + контур) выполняются на load; всё, что специфично для страницы, вызывается через
  // хуки onReady/onTheme/onError. Возвращает null, если MapLibre недоступен или нет контейнера
  // (страница тогда работает без карты — как и прежде под guard'ами).
  //
  // Опции:
  //   container   — id элемента-контейнера (обязателен);
  //   zoom,minZoom — стартовый и минимальный зум (по умолчанию 2 и 1.6);
  //   fillOpacity — прозрачность заливки (по умолчанию 0.85);
  //   lineWidth   — толщина контура (по умолчанию 0.6);
  //   legend      — CSS-селектор блока легенды для сворачивания (необязателен);
  //   geojsonUrl  — источник границ (по умолчанию /static/geo/regions.geojson);
  //   extraLayers — массив дополнительных слоёв, добавляемых после заливки и контура
  //                 (напр. слои подсветки/выбора на рейтинге);
  //   onReady(ctx)— вызывается после добавления слоёв и кадрирования; ctx = { map, popup, geo };
  //   onTheme(ctx)— расширение реакции на тему сверх фона и контура (напр. перекраска
  //                 доп. слоёв и заливки); вызывается внутри общего обработчика темы;
  //   onError(err)— обработка недоступного geojson (показать сообщение, скрыть блок и т.п.).
  window.RL.createRegionMap = function (opts) {
    opts = opts || {};
    var el = typeof opts.container === "string" ? document.getElementById(opts.container) : opts.container;
    if (!el || typeof maplibregl === "undefined") return null;

    var map = new maplibregl.Map(window.RL.regionMapConfig(opts));
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    var popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });

    var geojsonUrl = opts.geojsonUrl || "/static/geo/regions.geojson";
    var fillOpacity = opts.fillOpacity == null ? 0.85 : opts.fillOpacity;
    var lineWidth = opts.lineWidth == null ? 0.6 : opts.lineWidth;

    map.on("load", function () {
      fetch(geojsonUrl)
        .then(function (r) {
          if (!r.ok) throw new Error("geojson " + r.status);
          return r.json();
        })
        .then(function (fc) {
          var geo = window.RL && window.RL.unwrapGeojson ? window.RL.unwrapGeojson(fc) : fc;
          map.addSource("regions", { type: "geojson", data: geo });
          map.addLayer({
            id: "fill",
            type: "fill",
            source: "regions",
            paint: { "fill-color": window.RL.cssVar("--map-nodata", "#dcdcdc"), "fill-opacity": fillOpacity },
          });
          map.addLayer({
            id: "line",
            type: "line",
            source: "regions",
            paint: { "line-color": window.RL.cssVar("--map-line", "#ffffff"), "line-width": lineWidth },
          });
          if (opts.extraLayers) {
            opts.extraLayers.forEach(function (layer) {
              map.addLayer(layer);
            });
          }
          if (window.RL.fitToData) window.RL.fitToData(map, geo, 18);
          if (window.RL.softenZoomControls) window.RL.softenZoomControls(map, 0.5);
          if (opts.legend && window.RL.makeLegendCollapsible) {
            var lg = typeof opts.legend === "string" ? document.querySelector(opts.legend) : opts.legend;
            window.RL.makeLegendCollapsible(lg);
          }
          // Общая реакция на смену темы: фон-подложка и цвет контура. Специфика страницы
          // (перекраска заливки, слоёв подсветки/выбора) — через хук onTheme.
          if (window.RL.onTheme) {
            window.RL.onTheme(function () {
              try {
                if (!map.getLayer || !map.getLayer("bg")) return;
                map.setPaintProperty("bg", "background-color", window.RL.cssVar("--map-bg", "#eaf0f1"));
                if (map.getLayer("line")) {
                  map.setPaintProperty("line", "line-color", window.RL.cssVar("--map-line", "#ffffff"));
                }
                if (typeof opts.onTheme === "function") opts.onTheme({ map: map, popup: popup, geo: geo });
              } catch (e) {}
            });
          }
          if (typeof opts.onReady === "function") opts.onReady({ map: map, popup: popup, geo: geo });
        })
        .catch(function (err) {
          if (typeof opts.onError === "function") opts.onError(err);
        });
    });

    return { map: map, popup: popup };
  };

  // Нормировка весов доменов в проценты (сумма = 100%). Если пользователь обнулил все веса,
  // раздаём равные доли, чтобы не делить на ноль. Та же нормировка, что и на бэкенде при
  // расчёте композитного индекса; вынесена в общий помощник, чтобы конструктор индекса и
  // тесты пользовались одной формулой. Чистая функция.
  window.RL.normalizeWeights = function (weights, keys) {
    weights = weights || {};
    var total = 0;
    keys.forEach(function (k) {
      total += Math.max(0, weights[k] || 0);
    });
    var out = {};
    keys.forEach(function (k) {
      out[k] = total > 0 ? (100 * Math.max(0, weights[k] || 0)) / total : 100 / keys.length;
    });
    return out;
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
    input.placeholder = placeholder || gettext("Выберите или введите для поиска…");
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
    // Переносимая подпись под полем: показывает полное название выбранного пункта, если оно
    // не умещается в однострочное поле ввода (длинные названия показателей).
    var selectedCaption = document.createElement("div");
    selectedCaption.className = "combo-selected";
    selectedCaption.hidden = true;
    wrap.appendChild(selectedCaption);
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
      var label = o ? o.textContent : "";
      input.value = label;
      input.title = label;
      try {
        input.setSelectionRange(0, 0);
      } catch (e) {}
      input.scrollLeft = 0;
      // Полную подпись под полем показываем только при реальном переполнении (текст физически
      // не помещается в текущую ширину поля) — измеряем scrollWidth/clientWidth. Раньше порог
      // был по числу символов (>40) и показывал подпись даже тогда, когда широкое поле уже
      // вмещало текст целиком, что дублировало его на экране.
      var overflowing = input.scrollWidth > input.clientWidth + 1;
      if (label && overflowing) {
        selectedCaption.textContent = label;
        selectedCaption.hidden = false;
      } else {
        selectedCaption.textContent = "";
        selectedCaption.hidden = true;
      }
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
        list.innerHTML = '<div class="combo-empty">' + gettext("Ничего не найдено") + "</div>";
        return;
      }
      list.innerHTML = filtered
        .map(function (o, i) {
          var cur = o.value === select.value ? " is-current" : "";
          return (
            '<div class="combo-opt' + cur + '" role="option" data-i="' + i + '">' +
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

/* Экспорт графиков: единый конфиг для всех диаграмм Plotly (кнопки PNG и SVG в панели,
   без логотипа). Реализовано перехватом присвоения window.Plotly — файлы графиков не
   правятся. rl-common.js загружается раньше Plotly и скриптов страниц, поэтому перехват
   успевает встать до создания диаграмм. */
(function () {
  function nameFor(elOrGd) {
    var id = typeof elOrGd === "string" ? elOrGd : (elOrGd && elOrGd.id) || "chart";
    return "regionlens-" + id;
  }
  function mergeConfig(Plotly, cfg, id) {
    cfg = cfg || {};
    var out = Object.assign({ displaylogo: false }, cfg);
    // Панель инструментов Plotly должна быть доступна (в ней живут кнопки экспорта PNG/SVG),
    // но не перекрывать контент. Режим "hover" — панель всплывает поверх правого верхнего угла
    // только при наведении и не загораживает заголовок/легенду в покое.
    out.displayModeBar = "hover";
    if (out.responsive === undefined) out.responsive = true;
    out.toImageButtonOptions = Object.assign(
      { format: "png", filename: nameFor(id), scale: 2 },
      cfg.toImageButtonOptions || {}
    );
    // Оставляем в панели только экспорт (PNG + наш SVG): полный набор из 7 инструментов
    // перекрывал заголовки/легенды. Две иконки в углу по наведению — минимальный след.
    var remove = (cfg.modeBarButtonsToRemove || []).slice();
    ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines",
     "zoom2d", "pan2d", "zoomIn2d", "zoomOut2d", "resetScale2d",
     "hoverClosestCartesian", "hoverCompareCartesian"].forEach(function (b) {
      if (remove.indexOf(b) === -1) remove.push(b);
    });
    out.modeBarButtonsToRemove = remove;
    var add = (cfg.modeBarButtonsToAdd || []).slice();
    add.push({
      name: "downloadSvg",
      title: (window.gettext ? gettext("Скачать SVG") : "Скачать SVG"),
      icon: Plotly.Icons.disk,
      click: function (gd) {
        Plotly.downloadImage(gd, { format: "svg", filename: nameFor(gd) });
      },
    });
    out.modeBarButtonsToAdd = add;
    return out;
  }
  // Встроенная подсказка Plotly при рассинхроне размеров прижималась в угол (0,0) и мерцала.
  // Делаем её полностью прозрачной (событие наведения при этом продолжает срабатывать) и рисуем
  // собственный DOM-тултип по координатам курсора — он не зависит от внутренней геометрии Plotly,
  // поэтому не «съезжает», не мерцает и не дублируется. Работает одинаково в обеих темах и языках.
  function mergeLayout(layout) {
    layout = layout || {};
    layout.hoverlabel = Object.assign(
      {
        bgcolor: "rgba(0,0,0,0)",
        bordercolor: "rgba(0,0,0,0)",
        font: { color: "rgba(0,0,0,0)", size: 1 },
      },
      layout.hoverlabel || {}
    );
    return layout;
  }

  // Единственный переиспользуемый DOM-тултип для всех графиков.
  var _tip = null;
  function chartTip() {
    if (_tip) return _tip;
    _tip = document.createElement("div");
    _tip.className = "rl-chart-tip";
    _tip.style.cssText =
      "position:fixed;z-index:9999;pointer-events:none;display:none;max-width:320px;" +
      "padding:6px 9px;border-radius:7px;font-size:12px;line-height:1.35;" +
      "box-shadow:0 4px 14px rgba(0,0,0,0.18);white-space:normal;";
    document.body.appendChild(_tip);
    return _tip;
  }
  function tipText(pt) {
    if (pt == null) return "";
    if (typeof pt.hovertext === "string" && pt.hovertext) return pt.hovertext;
    var label = null,
      value = null;
    if (typeof pt.y === "string") {
      label = pt.y;
      value = pt.x;
    } else if (typeof pt.x === "string") {
      label = pt.x;
      value = pt.y;
    } else if (pt.theta != null) {
      label = pt.theta;
      value = pt.r;
    } else {
      label = pt.x;
      value = pt.y;
    }
    if (typeof pt.customdata === "string") label = pt.customdata;
    var v = typeof value === "number" ? (Math.round(value * 100) / 100).toString() : value;
    return (label != null && label !== "" ? label + ": " : "") + (v == null ? "" : v);
  }
  function showTip(data) {
    if (!data || !data.points || !data.points.length) return;
    var texts = [];
    for (var i = 0; i < data.points.length; i++) {
      var t = tipText(data.points[i]);
      if (t && texts.indexOf(t) === -1) texts.push(t);
    }
    if (!texts.length) return;
    var tip = chartTip();
    tip.style.background = window.RL ? RL.cssVar("--surface", "#fff") : "#fff";
    tip.style.color = window.RL ? RL.cssVar("--ink", "#1c2530") : "#1c2530";
    tip.style.border = "1px solid " + (window.RL ? RL.cssVar("--line", "#c9cfd6") : "#c9cfd6");
    tip.innerHTML = texts
      .map(function (t) {
        return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      })
      .join("<br>");
    var ev = data.event;
    var x = ev ? ev.clientX + 14 : 0;
    var y = ev ? ev.clientY + 14 : 0;
    tip.style.display = "block";
    // Не выходить за правый/нижний край окна.
    var r = tip.getBoundingClientRect();
    if (x + r.width > window.innerWidth - 8) x = window.innerWidth - r.width - 8;
    if (y + r.height > window.innerHeight - 8) y = ev.clientY - r.height - 14;
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = Math.max(8, y) + "px";
  }
  function hideTip() {
    if (_tip) _tip.style.display = "none";
  }
  // Низкоуровневый показ тултипа: готовый HTML + позиция курсора (для карт и др. виджетов).
  window.RL.tipShowAt = function (html, clientX, clientY) {
    var tip = chartTip();
    tip.style.background = window.RL ? RL.cssVar("--surface", "#fff") : "#fff";
    tip.style.color = window.RL ? RL.cssVar("--ink", "#1c2530") : "#1c2530";
    tip.style.border = "1px solid " + (window.RL ? RL.cssVar("--line", "#c9cfd6") : "#c9cfd6");
    tip.innerHTML = html;
    var x = clientX + 14;
    var y = clientY + 14;
    tip.style.display = "block";
    var r = tip.getBoundingClientRect();
    if (x + r.width > window.innerWidth - 8) x = clientX - r.width - 14;
    if (y + r.height > window.innerHeight - 8) y = clientY - r.height - 14;
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = Math.max(8, y) + "px";
  };
  window.RL.tipHide = hideTip;
  function wrap(Plotly) {
    if (!Plotly || Plotly.__rlExport) return Plotly;
    var _newPlot = Plotly.newPlot;
    var _react = Plotly.react;
    Plotly.newPlot = function (el, data, layout, cfg) {
      var p = _newPlot(el, data, mergeLayout(layout), mergeConfig(Plotly, cfg, el));
      // Если график построен до того, как контейнер получил финальную ширину, координаты
      // наведения оказываются рассчитаны для неверного размера и подсказки «съезжают».
      // Выравниваем график под контейнер на следующем кадре — дёшево и безопасно.
      if (p && typeof p.then === "function") {
        p.then(function () {
          var node = typeof el === "string" ? document.getElementById(el) : el;
          if (!node) return;
          var doResize = function () {
            try {
              if (Plotly.Plots && Plotly.Plots.resize) Plotly.Plots.resize(node);
            } catch (e) {}
          };
          requestAnimationFrame(doResize);
          // Собственный тултип по курсору вместо встроенной подсказки Plotly (ставится один раз).
          if (!node._rlTip && typeof node.on === "function") {
            node._rlTip = true;
            node.on("plotly_hover", showTip);
            node.on("plotly_unhover", hideTip);
            node.addEventListener("mouseleave", hideTip);
          }
          // Веб-шрифты (Golos/Lora) грузятся асинхронно и меняют метрики текста и размер
          // контейнера уже после первой отрисовки — пересчитываем график, когда они готовы.
          if (document.fonts && document.fonts.ready) document.fonts.ready.then(doResize);
          setTimeout(doResize, 350);
          // Контейнер может получить финальную ширину позже (шрифты, вкладки, скроллбар,
          // раскрытие карточек). ResizeObserver держит график в размер контейнера, поэтому
          // координаты наведения и подписи не «съезжают». Наблюдатель ставится один раз.
          if (window.ResizeObserver && !node._rlRO) {
            var raf = null;
            node._rlRO = new ResizeObserver(function () {
              if (raf) cancelAnimationFrame(raf);
              raf = requestAnimationFrame(doResize);
            });
            node._rlRO.observe(node);
          }
        });
      }
      return p;
    };
    if (_react) {
      Plotly.react = function (el, data, layout, cfg) {
        return _react(el, data, mergeLayout(layout), mergeConfig(Plotly, cfg, el));
      };
    }
    Plotly.__rlExport = true;
    return Plotly;
  }
  if (window.Plotly) { wrap(window.Plotly); return; }
  var _p;
  try {
    Object.defineProperty(window, "Plotly", {
      configurable: true,
      get: function () { return _p; },
      set: function (v) { _p = wrap(v); },
    });
  } catch (e) {
    /* свойство недоступно для переопределения — экспорт останется стандартным Plotly */
  }
})();

/* Онбординг: приветственная подсказка для новых посетителей. Показывается, если ранее не
   закрыта; факт закрытия запоминается в localStorage. Действует на любой странице, где есть
   элемент #rl-onboarding (сейчас — главная). */
(function () {
  function init() {
    var el = document.getElementById("rl-onboarding");
    if (!el) return;
    var KEY = "rl-onboarding-dismissed";
    try {
      if (localStorage.getItem(KEY) === "1") return;
    } catch (e) {
      return; /* localStorage недоступен — не показываем, чтобы не «залипало» */
    }
    el.hidden = false;
    var btn = document.getElementById("rl-onboarding-close");
    if (btn) {
      btn.addEventListener("click", function () {
        el.hidden = true;
        try { localStorage.setItem(KEY, "1"); } catch (e) { /* игнорируем */ }
      });
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
