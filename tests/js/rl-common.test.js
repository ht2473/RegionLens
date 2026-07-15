// Юнит-тесты общего клиентского помощника window.RL (backend/static/js/rl-common.js).
// Покрываются чистые функции, не зависящие от MapLibre/Plotly: разворот антимеридиана,
// кадрирование по данным, текст ошибки, локализация округов, разрешение начальных
// значений контролов. Эти функции стоят на критическом пути карт и графиков —
// именно вокруг них (антимеридиан/Чукотка) ранее ловились реальные регрессии.
import { beforeAll, describe, expect, it, vi } from "vitest";
import { loadScript } from "./helpers/load-script.js";

// rl-common.js вешает функции на window.RL при исполнении; загружаем один раз на файл.
beforeAll(() => {
  loadScript("rl-common.js");
});

describe("RL.unwrapGeojson — разворот антимеридиана", () => {
  it("сдвигает отрицательные долготы на +360 (восточная Чукотка)", () => {
    const geo = {
      features: [
        { geometry: { type: "Point", coordinates: [-175, 66] } },
      ],
    };
    const out = window.RL.unwrapGeojson(geo);
    expect(out.features[0].geometry.coordinates[0]).toBe(185);
    // широта не трогается
    expect(out.features[0].geometry.coordinates[1]).toBe(66);
  });

  it("не трогает положительные долготы", () => {
    const geo = { features: [{ geometry: { type: "Point", coordinates: [99, 55] } }] };
    window.RL.unwrapGeojson(geo);
    expect(geo.features[0].geometry.coordinates).toEqual([99, 55]);
  });

  it("рекурсивно обрабатывает вложенную геометрию (полигон)", () => {
    const geo = {
      features: [
        {
          geometry: {
            type: "Polygon",
            coordinates: [[[-179, 65], [178, 64], [-170, 66]]],
          },
        },
      ],
    };
    window.RL.unwrapGeojson(geo);
    expect(geo.features[0].geometry.coordinates[0]).toEqual([[181, 65], [178, 64], [190, 66]]);
  });

  it("идемпотентна: повторный вызов ничего не сдвигает", () => {
    const geo = { features: [{ geometry: { type: "Point", coordinates: [-175, 66] } }] };
    window.RL.unwrapGeojson(geo);
    window.RL.unwrapGeojson(geo); // второй прогон — по флагу _rlUnwrapped
    expect(geo.features[0].geometry.coordinates[0]).toBe(185); // а не 545
  });

  it("не падает на пустом/отсутствующем вводе", () => {
    expect(window.RL.unwrapGeojson(null)).toBeNull();
    expect(() => window.RL.unwrapGeojson({})).not.toThrow();
    expect(() => window.RL.unwrapGeojson({ features: [] })).not.toThrow();
  });
});

describe("RL.fitToData — кадрирование по границам данных", () => {
  // Заглушка карты: фиксируем факт и аргументы вызова fitBounds; остальные методы —
  // безопасные пустышки, чтобы функция прошла до конца без реального MapLibre.
  function fakeMap() {
    return {
      fitBounds: vi.fn(),
      getBounds: () => [[0, 0], [1, 1]],
      getZoom: () => 3,
      setMaxBounds: vi.fn(),
      setMinZoom: vi.fn(),
      getContainer: () => null,
    };
  }

  it("кадрирует по bbox нормальных данных", () => {
    const map = fakeMap();
    const geo = {
      features: [
        { geometry: { type: "Point", coordinates: [30, 50] } },
        { geometry: { type: "Point", coordinates: [180, 70] } },
      ],
    };
    window.RL.fitToData(map, geo, 18);
    expect(map.fitBounds).toHaveBeenCalledTimes(1);
    const [bounds, opts] = map.fitBounds.mock.calls[0];
    expect(bounds).toEqual([[30, 50], [180, 70]]);
    expect(opts.padding).toBe(18);
    expect(opts.animate).toBe(false);
  });

  it("пропускает кадрирование при неадекватном размахе долгот (>=210°)", () => {
    const map = fakeMap();
    // geojson в диапазоне -180..180 без разворота: формальный размах 360° — защита от антимеридиана
    const geo = {
      features: [
        { geometry: { type: "Point", coordinates: [-179, 66] } },
        { geometry: { type: "Point", coordinates: [179, 66] } },
      ],
    };
    window.RL.fitToData(map, geo, 18);
    expect(map.fitBounds).not.toHaveBeenCalled();
  });

  it("не падает на пустых данных", () => {
    const map = fakeMap();
    expect(() => window.RL.fitToData(map, { features: [] }, 18)).not.toThrow();
    expect(map.fitBounds).not.toHaveBeenCalled();
  });
});

describe("RL.errText — единый текст ошибки", () => {
  it("сетевой сбой (TypeError) даёт дружелюбное сообщение о связи с сервером", () => {
    const msg = window.RL.errText(new TypeError("Failed to fetch"));
    expect(msg).toMatch(/сервер/i);
    expect(msg).not.toBe("Failed to fetch");
  });

  it("наша HTTP-ошибка сохраняет свой текст со статусом", () => {
    expect(window.RL.errText(new Error("Ошибка загрузки слоя (500)."))).toBe(
      "Ошибка загрузки слоя (500)."
    );
  });

  it("пустой ввод даёт общий безопасный текст", () => {
    expect(window.RL.errText(null)).toMatch(/ошибка/i);
  });
});

describe("RL.localizeFederalDistrict — локализация округов", () => {
  it("известный округ проходит через каталог переводов", () => {
    // gettext в тестовой среде — тождество, поэтому имя возвращается как есть, но по карте.
    expect(window.RL.localizeFederalDistrict("Сибирский")).toBe("Сибирский");
  });

  it("неизвестное имя возвращается без изменений", () => {
    expect(window.RL.localizeFederalDistrict("Марсианский")).toBe("Марсианский");
  });

  it("пустое имя возвращается как есть", () => {
    expect(window.RL.localizeFederalDistrict("")).toBe("");
    expect(window.RL.localizeFederalDistrict(null)).toBeNull();
  });
});

describe("RL.prefYear — разрешение года: URL > предпочтение > запасное", () => {
  it("запасное значение, когда нет ни URL, ни предпочтения", () => {
    window.RL_PREFS = undefined;
    expect(window.RL.prefYear(2020)).toBe(2020);
  });

  it("берёт год из RL_PREFS, если он в допустимом диапазоне", () => {
    window.RL_PREFS = { year: 2018 };
    expect(window.RL.prefYear(2020)).toBe(2018);
  });

  it("год вне диапазона 2010–2024 игнорируется в пользу запасного", () => {
    window.RL_PREFS = { year: 1999 };
    expect(window.RL.prefYear(2020)).toBe(2020);
  });
});
