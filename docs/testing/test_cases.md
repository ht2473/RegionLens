# Тест-кейсы RegionLens

Набор представительных тест-кейсов по ключевым функциям системы. Каждый кейс прослеживается
до автоматизированного теста (колонка «Автотест»), что обеспечивает трассируемость
«требование → проверка». Формат: предусловие → шаги → ожидаемый результат.

Обозначения автотестов: `<файл>::<функция>` из каталога `tests/`.

## Аналитика: индекс и сценарии

| ID | Предусловие | Шаги | Ожидаемый результат | Автотест |
|---|---|---|---|---|
| TC-01 | Есть доменные баллы регионов за год | Задать пользовательские веса доменов и пересчитать рейтинг | Рейтинг пересобран по весам; порядок соответствует взвешенной сумме | `test_custom_index::test_custom_ranking_reweights_and_ranks` |
| TC-02 | Есть доменные баллы за год | Передать все веса нулевыми | Модель откатывается к равным весам, а не делит на ноль | `test_custom_index::test_custom_ranking_zero_weights_falls_back_to_equal` |
| TC-03 | Регион не в лидерах | Поднять слабый домен до высокого перцентиля | Место региона в рейтинге улучшается (delta > 0) | `test_scenario::test_scenario_raising_weak_domain_improves_rank` |
| TC-04 | Витрина индекса за год | Запросить сценарий для несуществующего ОКАТО | Возвращается пустой результат (None), без исключения | `test_scenario::test_scenario_unknown_region_returns_none` |
| TC-05 | Индекс посчитан по трём схемам | Сравнить места региона по equal/pca/expert | Возвращается коридор мест и мера согласованности | `test_scheme_agreement` |

## Типология и аномалии

| ID | Предусловие | Шаги | Ожидаемый результат | Автотест |
|---|---|---|---|---|
| TC-06 | Матрица признаков регион-год | Построить кластеры и профили | Стабильные идентификаторы кластеров, непустые профили | `test_typology::test_build_clusters_stable_ids_and_profile` |
| TC-07 | Матрица признаков за год | Выбрать число кластеров | Выбирается k=3 согласно критерию | `test_typology::test_choose_k_picks_three_clusters` |
| TC-08 | Регион с явно выделяющимся профилем | Прогнать поиск пространственных аномалий | Регион помечается как выброс | `test_anomalies::test_spatial_flags_clear_outlier` |
| TC-09 | Ряд со скачком уровня | Прогнать поиск структурных сдвигов | Сдвиг обнаружен в точке скачка | `test_anomalies::test_structural_break_detected_at_shift` |
| TC-10 | Ряд с линейным трендом | Прогнать поиск структурных сдвигов | Плавный тренд НЕ помечается как сдвиг | `test_anomalies::test_structural_ignores_linear_trend` |

## API: контракт, версионирование, лимиты

| ID | Предусловие | Шаги | Ожидаемый результат | Автотест |
|---|---|---|---|---|
| TC-11 | Витрина индекса за год | `GET /api/index/custom/` с весами | 200; строки с местом, баллом и сдвигом | `test_custom_index::test_custom_index_endpoint` |
| TC-12 | Витрина индекса за год | `GET /api/index/scenario/` с перцентилями | 200; базовое и сценарное место, чувствительность | `test_scenario::test_scenario_endpoint` |
| TC-13 | Приложение запущено | Разрешить имя `api:regions` | Каноническое имя ведёт на `/api/v1/regions/` | `test_api_versioning::test_canonical_reverse_is_versioned` |
| TC-14 | Приложение запущено | Разрешить имя алиаса | Алиас ведёт на `/api/regions/` (совместимость) | `test_api_versioning::test_alias_reverse_is_unversioned` |
| TC-15 | Схема OpenAPI генерируется | Сгенерировать схему | Присутствует security-схема `ApiTokenAuth` (apiKey/header) | `test_api_versioning::test_schema_documents_token_authentication` |
| TC-16 | Лимит anon = 3/мин (override) | Сделать 4 запроса подряд | Первые 3 разрешены, 4-й → 429 | `test_api_throttling::test_anonymous_throttle_blocks_over_limit` |
| TC-17 | Настройки DRF | Прочитать конфигурацию throttling | Классы anon/user и их ставки заданы | `test_api_throttling::test_throttling_is_configured` |

## Аутентификация по токену

| ID | Предусловие | Шаги | Ожидаемый результат | Автотест |
|---|---|---|---|---|
| TC-18 | Пользователь с выпущенным токеном | Запрос с заголовком `Authorization: Token <ключ>` | Запрос аутентифицирован как этот пользователь | `test_api_token::test_valid_token_authenticates_user` |
| TC-19 | — | Захешировать один и тот же ключ дважды | Хеш стабилен, не равен сырому ключу, длина 64 | `test_api_token::test_hash_is_stable_and_not_raw` |
| TC-20 | — | Запрос со схемой `Bearer` | Метод токена игнорирует чужую схему (None) | `test_api_token::test_non_token_scheme_is_ignored` |

## Доступ и роли

| ID | Предусловие | Шаги | Ожидаемый результат | Автотест |
|---|---|---|---|---|
| TC-21 | Чистая БД | Выполнить `setup_roles` | Создаются три группы: viewer/analyst/admin | `test_roles::test_setup_roles_creates_three_groups` |
| TC-22 | Роли настроены | Сравнить права admin и viewer | У admin строго больше прав | `test_roles::test_admin_group_has_more_perms_than_viewer` |
| TC-23 | Чистая БД | Выполнить `seed_demo` | Три демо-пользователя в корректных ролях | `test_seed_demo::test_creates_three_demo_users_in_correct_roles` |
| TC-24 | Демо-пользователи созданы | Зайти в админ-панель под каждой ролью | Доступ только у admin; остальным запрещено | `test_seed_demo::test_admin_can_access_admin_panel_others_cannot` |

## Веб-интерфейс, локализация, экспорт

| ID | Предусловие | Шаги | Ожидаемый результат | Автотест |
|---|---|---|---|---|
| TC-25 | Приложение запущено | Открыть сайт без выбора языка | Язык по умолчанию — русский | `test_i18n::test_default_language_is_russian` |
| TC-26 | Приложение запущено | Переключить язык на английский | Навигация и главная переведены | `test_i18n::test_switch_to_english_translates_navigation_and_home` |
| TC-27 | Анонимный пользователь | Запросить экспорт отчёта региона | Требуется вход (редирект/запрет) | `test_export::test_export_requires_login` |
| TC-28 | Вошедший пользователь | Экспортировать отчёт региона в XLSX | Возвращается корректная книга Excel | `test_export::test_region_xlsx_is_valid_workbook` |

## Эксплуатация и качество данных

| ID | Предусловие | Шаги | Ожидаемый результат | Автотест |
|---|---|---|---|---|
| TC-29 | Приложение запущено | `GET /healthz` | 200, статус «жив» | `test_health::test_healthz_ok` |
| TC-30 | Витрина DuckDB недоступна | `GET /readyz` | Возвращается «не готов» | `test_health::test_readyz_not_ready_when_duckdb_missing` |
| TC-31 | Приложение запущено | `GET /metrics` | Экспонируются метрики Prometheus | `test_health::test_metrics_endpoint_exposes_prometheus` |
| TC-32 | Витрина фактов загружена | Посчитать покрытие метрик | Доли наблюдаемых/импутированных значений корректны | `test_data_quality::test_basic_counts_and_shares` |

## Сводка трассируемости

Приведённые 32 кейса покрывают функциональные области из раздела 2 тест-плана и являются
подмножеством автоматизированного набора (463 тест-функции, 527 прогонов). Полный набор
исполняется в CI на каждый push/PR; ручной проверке подлежат кроссбраузерность и визуальная
консистентность (см. отчёт security-review).
