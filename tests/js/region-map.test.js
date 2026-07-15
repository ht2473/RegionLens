// Юнит-тесты фабрики хороплета РФ (backend/static/js/rl-common.js).
// RL.regionMapConfig — чистая сборка конфигурации MapLibre (проверяем значения по умолчанию,
// переопределения и структуру стиля). RL.createRegionMap создаёт реальную карту MapLibre,
// поэтому под jsdom (без MapLibre) проверяется только защитное поведение — возврат null,
// когда карту построить нельзя. Реальный рендер карт покрыт e2e-сценариями Playwright.
import { beforeAll, describe, expect, it } from "vitest";
import { loadScript } from "./helpers/load-script.js";

beforeAll(() => {
  loadScript("rl-common.js");
});

describe("RL.regionMapConfig — конфигурация базовой карты", () => {
  it("значения по умолчанию: центр, зум, рамки, без копий мира", () => {
    const cfg = window.RL.regionMapConfig({ container: "map" });
    expect(cfg.container).toBe("map");
    expect(cfg.center).toEqual([99, 66]);
    expect(cfg.zoom).toBe(2);
    expect(cfg.minZoom).toBe(1.6);
    expect(cfg.maxBounds).toEqual([[5, 25], [205, 86]]);
    expect(cfg.renderWorldCopies).toBe(false);
    expect(cfg.attributionControl).toBe(false);
  });

  it("переопределяемые zoom и minZoom (случай рейтинга)", () => {
    const cfg = window.RL.regionMapConfig({ container: "rankings-map", zoom: 1.6, minZoom: 1.4 });
    expect(cfg.zoom).toBe(1.6);
    expect(cfg.minZoom).toBe(1.4);
  });

  it("zoom=0 не подменяется значением по умолчанию", () => {
    const cfg = window.RL.regionMapConfig({ container: "m", zoom: 0 });
    expect(cfg.zoom).toBe(0);
  });

  it("стиль — пустой источник и слой-подложка с цветом фона темы", () => {
    const cfg = window.RL.regionMapConfig({ container: "map" });
    expect(cfg.style.version).toBe(8);
    expect(cfg.style.sources).toEqual({});
    expect(cfg.style.layers).toHaveLength(1);
    const bg = cfg.style.layers[0];
    expect(bg.id).toBe("bg");
    expect(bg.type).toBe("background");
    // В jsdom CSS-переменная не разрешается — берётся запасной цвет.
    expect(bg.paint["background-color"]).toBe("#eaf0f1");
  });
});

describe("RL.createRegionMap — защитное поведение без MapLibre", () => {
  it("возвращает null, когда MapLibre недоступен", () => {
    // В jsdom global.maplibregl отсутствует — карту построить нельзя.
    document.body.innerHTML = '<div id="map"></div>';
    expect(window.RL.createRegionMap({ container: "map" })).toBeNull();
  });

  it("возвращает null, когда контейнера нет в DOM", () => {
    document.body.innerHTML = "";
    expect(window.RL.createRegionMap({ container: "absent" })).toBeNull();
  });
});
