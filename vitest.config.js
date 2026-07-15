// Конфигурация vitest для клиентского JavaScript.
// Окружение jsdom даёт window/document/localStorage, поэтому постраничные скрипты
// (которые вешают функции на window.RL и обращаются к DOM) исполняются как в браузере.
// Тесты ищем только в tests/js — сюда не попадают Python-тесты и e2e-сценарии Playwright.
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["tests/js/**/*.test.js"],
    // Изоляция по файлам: каждый тестовый файл получает свежий jsdom-глобал,
    // поэтому повторное исполнение IIFE постраничного скрипта не конфликтует.
    isolate: true,
  },
});
