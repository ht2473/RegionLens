"""Регистрация операционных моделей в админке Django.

Закрывает требование «панель администратора ≥5 страниц»: вместе со встроенными разделами
«Пользователи» и «Группы» (django.contrib.auth) здесь регистрируются пять моделей
приложения core. У каждой настроены колонки списка, фильтры и поиск; журнал аудита —
только для чтения (append-only), у обратной связи — массовые действия обработки.
"""

from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from core.models import AuditLog, ExportJob, FeedbackMessage, SavedView, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role_note", "created")
    search_fields = ("user__username", "organization", "role_note")
    readonly_fields = ("created",)
    autocomplete_fields = ("user",)


@admin.register(SavedView)
class SavedViewAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "created")
    list_filter = ("created",)
    search_fields = ("name", "user__username")
    readonly_fields = ("created",)
    autocomplete_fields = ("user",)


@admin.register(FeedbackMessage)
class FeedbackMessageAdmin(admin.ModelAdmin):
    list_display = ("text_preview", "user", "is_handled", "created")
    list_display_links = ("text_preview",)
    list_filter = ("is_handled", "created")
    search_fields = ("text", "user__username")
    readonly_fields = ("created",)
    actions = ("mark_handled", "mark_unhandled")

    @admin.display(description="Сообщение")
    def text_preview(self, obj: FeedbackMessage) -> str:
        """Короткий предпросмотр текста для колонки списка."""
        text = obj.text or ""
        return text if len(text) <= 70 else f"{text[:70]}…"

    @admin.action(description="Пометить как обработанные")
    def mark_handled(self, request: HttpRequest, queryset: QuerySet[FeedbackMessage]) -> None:
        updated = queryset.update(is_handled=True)
        self.message_user(request, f"Помечено обработанными: {updated}.")

    @admin.action(description="Пометить как необработанные")
    def mark_unhandled(self, request: HttpRequest, queryset: QuerySet[FeedbackMessage]) -> None:
        updated = queryset.update(is_handled=False)
        self.message_user(request, f"Помечено необработанными: {updated}.")


@admin.register(ExportJob)
class ExportJobAdmin(admin.ModelAdmin):
    list_display = ("okato", "fmt", "status", "user", "created")
    list_filter = ("fmt", "status", "created")
    search_fields = ("okato", "user__username")
    readonly_fields = ("created",)
    autocomplete_fields = ("user",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Журнал аудита — только просмотр (append-only): записи не создаются и не правятся вручную."""

    list_display = ("ts", "user", "action")
    list_filter = ("ts",)
    search_fields = ("action", "user__username")
    readonly_fields = ("user", "action", "ts")
    date_hierarchy = "ts"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: AuditLog | None = None) -> bool:
        return False
