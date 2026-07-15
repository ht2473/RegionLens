// Загрузка постраничного скрипта RegionLens в текущее окружение jsdom.
// Скрипты фронтенда — это IIFE, которые вешают функции на window.RL и рассчитаны
// на исполнение тегом <script> в браузере (модульных экспортов у них нет). Чтобы
// протестировать реальный отгружаемый код без его переписывания, читаем исходник
// файла и исполняем его в глобальной области jsdom — ровно так же, как это сделал бы
// браузер. После вызова нужные функции доступны через window.RL.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// vitest запускается из корня репозитория, поэтому путь к скриптам строим от cwd:
// под jsdom import.meta.url не гарантированно относится к схеме file, и резолв через
// него ненадёжен.
const JS_DIR = resolve(process.cwd(), "backend/static/js");

// Исполнить файл backend/static/js/<name> в глобальном контексте jsdom.
export function loadScript(name) {
  const source = readFileSync(resolve(JS_DIR, name), "utf8");
  // Function-конструктор исполняет код в глобальной области (а не в области модуля),
  // поэтому window/document скрипта — это jsdom-глобалы теста.
  // eslint-disable-next-line no-new-func
  new Function(source)();
}
