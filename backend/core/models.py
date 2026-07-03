"""Операционные модели RegionLens (PostgreSQL / OLTP, Django ORM).

Это второй из «двух миров». Аналитика и справочники живут в DuckDB и
приложением только читаются; изменяемое операционное состояние — пользователи, их
профили, сохранённые виды, обратная связь, задания экспорта и журнал аудита — хранится
здесь, в Postgres, и пишется приложением. Контракт таблиц зафиксирован в моделях ниже.

Ключевой инвариант разделения миров: SavedView хранит ТОЛЬКО конфигурацию экрана
(год / регион / мера / схема) в JSON, но НЕ сами аналитические данные — те всегда
перечитываются из DuckDB по сохранённым параметрам. Так связь «офлайн считает →
приложение читает» не нарушается.

Роли (viewer / analyst / admin) реализуются штатными Django Group + права,
поэтому отдельной модели роли здесь нет.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

from django.contrib.auth.models import User
from django.db import models
from django.urls import reverse


class UserProfile(models.Model):
    """Профиль пользователя — операционное расширение стандартного `User`.

    Создаётся автоматически при регистрации (сигнал). Хранит свободную
    заметку о роли/назначении учётной записи и организацию; собственно права доступа
    задаются членством в Group, а не этими полями.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="Пользователь",
    )
    role_note = models.CharField("Заметка о роли", max_length=200, blank=True, default="")
    organization = models.CharField("Организация", max_length=200, blank=True, default="")
    default_year = models.PositiveIntegerField("Год по умолчанию", default=2024)
    default_scheme = models.CharField(
        "Схема весов по умолчанию",
        max_length=16,
        choices=[("equal", "Равные веса"), ("pca", "PCA"), ("expert", "Экспертные")],
        default="equal",
    )
    default_measure = models.CharField(
        "Мера карты по умолчанию",
        max_length=16,
        choices=[("cluster", "Тип (кластер)"), ("index", "Индекс развития")],
        default="cluster",
    )
    last_region_okato = models.CharField(
        "Последний открытый регион (ОКАТО)", max_length=20, blank=True, default=""
    )
    # Зарезервировано под персональный доступ к API (функция временно отключена).
    api_token = models.CharField(
        "Токен API",
        max_length=43,
        blank=True,
        default="",
        db_index=True,
        help_text="Личный ключ для доступа к API (заголовок Authorization: Token …).",
    )
    created = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Профиль пользователя"
        verbose_name_plural = "Профили пользователей"

    def __str__(self) -> str:
        return f"Профиль: {self.user.get_username()}"


class SavedView(models.Model):
    """Сохранённый вид — именованный набор параметров экрана пользователя.

    `config` — это конфигурация (год, ОКАТО региона, мера карты, схема весов индекса
    и т.п.), а НЕ данные. При открытии вида приложение перечитывает аналитику из DuckDB
    по этим параметрам — инвариант «двух миров» сохраняется.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="saved_views",
        verbose_name="Пользователь",
    )
    name = models.CharField("Название", max_length=200)
    config = models.JSONField("Параметры экрана", default=dict)
    created = models.DateTimeField("Создан", auto_now_add=True)
    share_token = models.CharField(
        "Токен публичной ссылки",
        max_length=43,
        blank=True,
        default="",
        db_index=True,
        help_text="Непустой = вид открыт по публичной ссылке без входа (read-only).",
    )

    class Meta:
        verbose_name = "Сохранённый вид"
        verbose_name_plural = "Сохранённые виды"
        ordering = ["-created", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="uniq_savedview_user_name"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.user.get_username()})"

    @property
    def is_shared(self) -> bool:
        """Открыт ли вид по публичной ссылке."""
        return bool(self.share_token)

    def enable_sharing(self) -> None:
        """Включить публичную ссылку: сгенерировать непредсказуемый токен (если ещё нет)."""
        if not self.share_token:
            self.share_token = secrets.token_urlsafe(32)
            self.save(update_fields=["share_token"])

    def disable_sharing(self) -> None:
        """Отозвать публичную ссылку: очистить токен."""
        if self.share_token:
            self.share_token = ""
            self.save(update_fields=["share_token"])

    def target_url(self) -> str:
        """Экран, восстановленный из конфига, как deep-link на публичную страницу.

        Регион (если задан okato) → дашборд региона с годом; иначе → карта с годом и мерой.
        Аналитика перечитывается из DuckDB по этим параметрам — инвариант «двух миров».
        """
        config = self.config or {}
        year = config.get("year", 2024)
        okato = config.get("okato")
        if okato:
            return f"{reverse('region-dashboard-page', args=[okato])}?year={year}"
        measure = config.get("measure", "cluster")
        return f"{reverse('map')}?year={year}&measure={measure}"

    def public_url(self) -> str:
        """Относительный путь публичной ссылки на вид (валиден, только если расшарен)."""
        return reverse("public_saved_view", args=[self.share_token])


class FeedbackMessage(models.Model):
    """Сообщение обратной связи.

    Может быть анонимным (страница обратной связи публична), поэтому `user` обнуляется
    при удалении учётной записи. `is_handled` — флаг обработки для админки.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feedback_messages",
        verbose_name="Пользователь",
    )
    text = models.TextField("Текст")
    is_handled = models.BooleanField("Обработано", default=False)
    created = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Сообщение обратной связи"
        verbose_name_plural = "Сообщения обратной связи"
        ordering = ["-created", "-id"]

    def __str__(self) -> str:
        author = self.user.get_username() if self.user else "аноним"
        return f"Обратная связь от {author}"


class ExportJob(models.Model):
    """Задание экспорта отчёта по региону (xlsx / docx).

    Экспорт синхронный (файл создаётся в запросе), поэтому статус по умолчанию `done`;
    модель фиксирует факт экспорта и путь к файлу для истории в личном кабинете
    и журнале аудита.
    """

    class Format(models.TextChoices):
        XLSX = "xlsx", "Excel (.xlsx)"
        DOCX = "docx", "Word (.docx)"

    class Status(models.TextChoices):
        PENDING = "pending", "В очереди"
        DONE = "done", "Готово"
        ERROR = "error", "Ошибка"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="export_jobs",
        verbose_name="Пользователь",
    )
    okato = models.CharField("ОКАТО региона", max_length=20)
    fmt = models.CharField("Формат", max_length=8, choices=Format.choices)
    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.DONE)
    file = models.FileField("Файл", upload_to="exports/", blank=True)
    created = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Задание экспорта"
        verbose_name_plural = "Задания экспорта"
        ordering = ["-created", "-id"]

    def __str__(self) -> str:
        return f"Экспорт {self.okato} → {self.fmt} ({self.status})"


class AuditLog(models.Model):
    """Журнал аудита ключевых действий (вход/выход, экспорт, сохранение вида и т.п.).

    Пишется middleware/сигналами. `user` обнуляется при удалении учётной
    записи, чтобы запись аудита сохранялась.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name="Пользователь",
    )
    action = models.CharField("Действие", max_length=120)
    ts = models.DateTimeField("Время", auto_now_add=True)

    class Meta:
        verbose_name = "Запись аудита"
        verbose_name_plural = "Журнал аудита"
        ordering = ["-ts", "-id"]
        indexes = [
            models.Index(fields=["-ts"], name="auditlog_ts_idx"),
            models.Index(fields=["action"], name="auditlog_action_idx"),
        ]

    def __str__(self) -> str:
        author = self.user.get_username() if self.user else "система"
        return f"{author}: {self.action}"


class Favorite(models.Model):
    """Избранное пользователя: закладки на регионы и показатели.

    Хранит ТОЛЬКО ссылку на сущность аналитического мира (`kind` + `ref`) и
    денормализованную подпись (`label`) — чтобы показывать список в кабинете без
    обращения к DuckDB. Сами аналитические данные не дублируются: инвариант «двух
    миров» сохраняется, при открытии закладки экран перечитывается из
    хранилища по ссылке (окато региона или идентификатор показателя).
    """

    class Kind(models.TextChoices):
        REGION = "region", "Регион"
        METRIC = "metric", "Показатель"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="favorites",
        verbose_name="Пользователь",
    )
    kind = models.CharField("Тип", max_length=16, choices=Kind.choices)
    ref = models.CharField("Ссылка", max_length=64, help_text="ОКАТО региона или ID показателя.")
    label = models.CharField("Подпись", max_length=300, blank=True, default="")
    created = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Избранное"
        verbose_name_plural = "Избранное"
        ordering = ["-created", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "kind", "ref"], name="uniq_favorite_user_kind_ref"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.label or self.ref} ({self.user.get_username()})"

    def target_url(self) -> str:
        """Ссылка на объект закладки: регион → дашборд; показатель → explore с метрикой."""
        if self.kind == self.Kind.REGION:
            return reverse("region-dashboard-page", args=[self.ref])
        return f"{reverse('explore')}?metric={self.ref}"


class ComparisonSet(models.Model):
    """Набор сравнения — именованная группа регионов (2–3) для страницы «Сравнение».

    Как и `SavedView`, хранит ТОЛЬКО ссылки на регионы (список ОКАТО) и год — не сами
    аналитические данные. При открытии набора страница сравнения перечитывает аналитику
    из DuckDB по этим параметрам: инвариант «двух миров» сохраняется.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="comparison_sets",
        verbose_name="Пользователь",
    )
    name = models.CharField("Название", max_length=200)
    okatos = models.JSONField("Регионы (ОКАТО)", default=list)
    year = models.PositiveIntegerField("Год", default=2024)
    created = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Набор сравнения"
        verbose_name_plural = "Наборы сравнения"
        ordering = ["-created", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="uniq_comparisonset_user_name"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.user.get_username()})"

    def target_url(self) -> str:
        """Ссылка на страницу сравнения с предвыбранными регионами и годом."""
        params: list[tuple[str, str]] = [("okato", o) for o in (self.okatos or [])]
        params.append(("year", str(self.year)))
        return f"{reverse('compare')}?{urlencode(params)}"
