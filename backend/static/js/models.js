/* RegionLens — интерактивное применение ML-моделей на странице «Модели».
   Пользователь выбирает регион и год; форма запрашивает /api/models/predict/, где
   сохранённые модели загружаются из файлов и применяются к готовому профилю региона.
   Показывает предсказанный тип региона и оценку нетипичности. Это демонстрация
   применения модели к профилю, не прогноз будущего и не причинность. */

(function () {
  "use strict";

  var regionSel = document.getElementById("mp-region");
  var yearInput = document.getElementById("mp-year");
  var yearLabel = document.getElementById("mp-year-label");
  var runBtn = document.getElementById("mp-run");
  var resultEl = document.getElementById("mp-result");
  if (!regionSel || !runBtn || !resultEl) return; // блок есть только при обученных моделях

  var state = { year: RL.prefYear(2024) };
  if (yearInput) {
    yearInput.value = state.year;
    if (yearLabel) yearLabel.textContent = state.year;
    yearInput.addEventListener("input", function () {
      state.year = Number(yearInput.value);
      if (yearLabel) yearLabel.textContent = yearInput.value;
    });
  }

  function setResult(html) {
    resultEl.innerHTML = html;
  }

  function renderPrediction(data) {
    var cards = "";

    if (data.typology) {
      var typeName = data.typology.cluster_label || gettext("тип") + " " + data.typology.cluster_id;
      cards +=
        '<div class="kpi"><div class="kpi-label">' + gettext("Классификатор типологии") + "</div>" +
        '<div class="kpi-type">' + typeName + "</div>" +
        '<div class="chart-note">' + gettext("предсказанный тип региона") + "</div></div>";
    }

    if (data.anomaly) {
      // Знак и цвет ведём по флагу выброса; score показываем как справочную оценку.
      var verdict = data.anomaly.is_outlier ? gettext("нетипичный профиль") : gettext("в норме");
      var color = data.anomaly.is_outlier
        ? RL.cssVar("--bad", "#b4532a")
        : RL.cssVar("--good", "#1f6f63");
      cards +=
        '<div class="kpi"><div class="kpi-label">' + gettext("Детектор аномалий") + "</div>" +
        '<div class="kpi-type" style="color:' + color + '">' + verdict + "</div>" +
        '<div class="chart-note">' + gettext("оценка нетипичности") + ": " + data.anomaly.score + "</div></div>";
    }

    if (!cards) {
      setResult('<p class="chart-note">' + gettext("Модели недоступны.") + "</p>");
      return;
    }
    setResult(
      '<p class="chart-note" style="margin-top:14px;">' +
        gettext("Результат для региона") + ": <strong>" + data.region_name + "</strong>, " +
        gettext("год") + " " + data.year +
      '</p><div class="kpi-row">' + cards + "</div>"
    );
  }

  function run() {
    var okato = regionSel.value;
    if (!okato) return;
    setResult('<p class="chart-note" style="margin-top:14px;">' + gettext("Применяем модели…") + "</p>");
    fetch("/api/models/predict/?okato=" + encodeURIComponent(okato) + "&year=" + state.year)
      .then(function (r) {
        if (r.status === 404) {
          throw new Error(gettext("Нет полного профиля региона за выбранный год."));
        }
        if (!r.ok) throw new Error(gettext("Ошибка применения моделей") + " (" + r.status + ")");
        return r.json();
      })
      .then(renderPrediction)
      .catch(function (e) {
        setResult('<p class="chart-note" style="margin-top:14px;">' + RL.errText(e) + "</p>");
      });
  }

  runBtn.addEventListener("click", run);

  // Наполнить список регионов и включить поиск по названию (как на остальных страницах).
  fetch("/api/regions/")
    .then(function (r) { return r.json(); })
    .then(function (rows) {
      rows.sort(function (a, b) {
        return (a.region_name || "").localeCompare(b.region_name || "", "ru");
      });
      regionSel.innerHTML = rows
        .map(function (r) { return '<option value="' + r.okato + '">' + r.region_name + "</option>"; })
        .join("");
      if (rows.length) regionSel.value = rows[0].okato;
      if (RL.enhanceSelect) RL.enhanceSelect(regionSel, gettext("Поиск региона…"));
    })
    .catch(function () {
      setResult('<p class="chart-note">' + gettext("Не удалось загрузить список регионов.") + "</p>");
    });
})();
