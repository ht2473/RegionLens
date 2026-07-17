// Юнит-тест общего помощника RL.wireCopyLink (кнопка «Скопировать ссылку» deep-link-страниц).
import { beforeAll, describe, expect, it, vi } from "vitest";
import { loadScript } from "./helpers/load-script.js";

beforeAll(() => {
  loadScript("rl-common.js");
});

describe("RL.wireCopyLink", () => {
  it("по клику копирует текущий URL и показывает подтверждение", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    document.body.innerHTML = '<button id="cp">Скопировать ссылку</button>';
    const btn = document.getElementById("cp");

    window.RL.wireCopyLink("cp");
    btn.click();

    expect(writeText).toHaveBeenCalledWith(window.location.href);
    await Promise.resolve();
    await Promise.resolve(); // дать промису clipboard разрешиться
    expect(btn.textContent).toBe("Ссылка скопирована");
  });

  it("принимает и элемент, и id; на отсутствующей кнопке не падает", () => {
    expect(() => window.RL.wireCopyLink("missing-id")).not.toThrow();
    expect(() => window.RL.wireCopyLink(null)).not.toThrow();
  });
});
