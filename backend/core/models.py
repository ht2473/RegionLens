"""Операционные модели RegionLens (PostgreSQL / OLTP, Django ORM).

Это второй из «двух миров» (Хартия §5). Аналитика и справочники живут в DuckDB и
приложением только читаются; изменяемое операционное состояние — пользователи, их
профили, сохранённые виды, обратная связь, задания экспорта и журнал аудита — хранится
здесь, в Postgres, и пишется приложением. Контракт таблиц зафиксирован в REFERENCE §3.

Ключевой инвариант разделения миров: SavedView хранит ТОЛЬКО конфигурацию экрана
(год / регион / мера / схема) в JSON, но НЕ сами аналитические данные — те всегда
перечитываются из DuckDB по сохранённым параметрам. Так связь «офлайн считает →
приложение читает» не нарушается.

Роли (viewer / analyst / admin) реализуются штатными Django Group + права (модуль Ф10·2),
поэтому отдельной модели роли здесь нет.
"""

from __future__ import annotations

from django.contrib.auth.models import User
from django.db import models


class UserProfile(models.Model):
    """Профиль пользователя — операционное расширение стандартного `User`.

    Создаётся автоматически при регистрации (сигнал — модуль Ф10·3). Хранит свободную
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
    по этим параметрам — инвариант «двух миров» (Хартия §5) сохраняется.
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

    class Meta:
        verbose_name = "Сохранённый вид"
        verbose_name_plural = "Сохранённые виды"
        ordering = ["-created", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="uniq_savedview_user_name"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.user.get_username()})"


class FeedbackMessage(models.Model):
    """Сообщение обратной связи.

    Может быть анонимным (страница обратной связи публична), поэтому `user` обнуляется
    при удалении учётной записи. `is_handled` — флаг обработки для админки (Ф10·4).
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
    модель фиксирует факт экспорта и путь к файлу для истории в личном кабинете (Ф10·5)
    и журнале аудита (Ф10·7).
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

    Пишется middleware/сигналами (модуль Ф10·7). `user` обнуляется при удалении учётной
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
