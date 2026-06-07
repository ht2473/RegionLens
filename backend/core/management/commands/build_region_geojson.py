"""Management-команда: проставить okato в GeoJSON границ субъектов по region_dim (Ф7).

Зачем: публичные GeoJSON границ обычно ключуются по ИМЕНИ региона (а имена «грязные»),
тогда как канон проекта — ОКАТО. Авторитетный кроссволк имя↔okato живёт в region_dim,
поэтому здесь мы джойним фичи исходного GeoJSON к region_dim и пишем чистый
backend/static/geo/regions.geojson с единственным ключом okato (+ name для подписи).

Использование:
    python backend/manage.py build_region_geojson --source path/to/source.geojson
    # если в исходнике уже есть свойство с ОКАТО:
    python backend/manage.py build_region_geojson --source src.geojson --okato-prop OKATO
    # ручные доопределения для несопоставленных имён (JSON: {"исходное имя": "okato"}):
    python backend/manage.py build_region_geojson --source src.geojson --overrides fix.json

Результат — отчёт о сопоставленных/несопоставленных фичах и непокрытых регионах.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from core.duck import q

# Слова-типы субъекта, не несущие различающего смысла при сопоставлении имён.
_TYPE_WORDS = {
    "автономная",
    "автономный",
    "область",
    "округ",
    "край",
    "республика",
    "город",
    "респ",
    "обл",
    "ао",
    "г",
}
# Частые имена свойства с названием региона в публичных GeoJSON.
_NAME_PROPS = ("name", "NAME", "name_ru", "NL_NAME_1", "NAME_1", "full_name", "region", "shapeName")


def normalize_name(name: str) -> str:
    """Нормализовать имя региона для сопоставления: регистр, ё→е, без скобок/типа/пунктуации."""
    s = (name or "").lower().replace("ё", "е").strip()
    s = re.sub(r"\(.*?\)", " ", s)  # убрать скобочные пояснения «(с автономным округом)»
    s = re.sub(r"[^\w\s-]", " ", s, flags=re.UNICODE)  # пунктуацию убрать, дефис оставить
    tokens = [t for t in re.split(r"\s+", s) if t and t not in _TYPE_WORDS]
    return " ".join(tokens)


def _pick_name(props: dict[str, Any], name_prop: str | None) -> str | None:
    """Достать имя региона из свойств фичи (по заданному ключу или по частым ключам)."""
    if name_prop:
        value = props.get(name_prop)
        return str(value) if value is not None else None
    for key in _NAME_PROPS:
        if props.get(key):
            return str(props[key])
    return None


def tag_features(
    features: list[dict[str, Any]],
    name_index: dict[str, str],
    *,
    name_prop: str | None = None,
    okato_prop: str | None = None,
    overrides: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Проставить okato в фичи; вернуть (обработанные фичи, несопоставленные имена)."""
    overrides = overrides or {}
    tagged: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for feat in features:
        props = feat.get("properties") or {}
        raw_name = _pick_name(props, name_prop)
        okato: str | None = None
        if okato_prop and props.get(okato_prop) is not None:
            okato = str(props[okato_prop])
        elif raw_name and raw_name in overrides:
            okato = overrides[raw_name]
        elif raw_name:
            okato = name_index.get(normalize_name(raw_name))
        if okato is None:
            unmatched.append(raw_name or "(без имени)")
            continue
        tagged.append(
            {
                "type": "Feature",
                "geometry": feat.get("geometry"),
                "properties": {"okato": okato, "name": raw_name},
            }
        )
    return tagged, unmatched


class Command(BaseCommand):
    """Собрать backend/static/geo/regions.geojson с ключом okato из исходного GeoJSON."""

    help = "Проставить okato в GeoJSON границ субъектов по region_dim и записать в static/geo."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--source", required=True, help="Путь к исходному GeoJSON границ.")
        parser.add_argument("--name-prop", default=None, help="Свойство фичи с именем региона.")
        parser.add_argument("--okato-prop", default=None, help="Свойство фичи с готовым ОКАТО.")
        parser.add_argument(
            "--overrides", default=None, help="JSON {имя: okato} для ручных правок."
        )
        parser.add_argument("--out", default=None, help="Куда писать (по умолч. static/geo).")

    def handle(self, *args: Any, **options: Any) -> None:
        source = Path(options["source"])
        if not source.exists():
            self.stderr.write(self.style.ERROR(f"Исходный файл не найден: {source}"))
            return

        out = (
            Path(options["out"])
            if options["out"]
            else settings.BASE_DIR / "static" / "geo" / "regions.geojson"
        )
        overrides: dict[str, str] = {}
        if options["overrides"]:
            overrides = json.loads(Path(options["overrides"]).read_text(encoding="utf-8"))

        rows = q("SELECT okato, region_name FROM region_dim WHERE included_flag = TRUE")
        name_index = {normalize_name(str(r["region_name"])): str(r["okato"]) for r in rows}

        raw = json.loads(source.read_text(encoding="utf-8"))
        features = raw["features"] if isinstance(raw, dict) else raw

        tagged, unmatched = tag_features(
            features,
            name_index,
            name_prop=options["name_prop"],
            okato_prop=options["okato_prop"],
            overrides=overrides,
        )

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"type": "FeatureCollection", "features": tagged}, ensure_ascii=False),
            encoding="utf-8",
        )

        covered = {str(f["properties"]["okato"]) for f in tagged}
        missing = sorted({str(r["okato"]) for r in rows} - covered)

        self.stdout.write(self.style.SUCCESS(f"Записано: {out} ({len(tagged)} фич)"))
        self.stdout.write(
            f"Сопоставлено: {len(tagged)} · не сопоставлено фич источника: {len(unmatched)}"
        )
        if unmatched:
            self.stdout.write(self.style.WARNING("Несопоставленные имена источника:"))
            for nm in unmatched:
                self.stdout.write(f"  · {nm}")
        if missing:
            self.stdout.write(
                self.style.WARNING(f"Регионы region_dim без геометрии ({len(missing)}):")
            )
            self.stdout.write("  " + ", ".join(missing))
        if not unmatched and not missing:
            self.stdout.write(self.style.SUCCESS("Все 85 субъектов сопоставлены 1:1."))
