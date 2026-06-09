"""Тесты операционных моделей (Ф10, модуль 1): создание, связи, ограничения, __str__.

Модели живут в Postgres (в тестах — sqlite через DATABASE_URL по умолчанию), поэтому
все тесты помечены django_db. Проверяем контракт REFERENCE §3 и инварианты:
каскад/обнуление FK, уникальность сохранённого вида на пользователя, round-trip JSON,
значения choices/дефолтов, сортировку и человекочитаемый __str__.
"""

from __future__ import annotations

import pytest
from core.models import AuditLog, ExportJob, FeedbackMessage, SavedView, UserProfile
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

pytestmark = pytest.mark.django_db


def _user(username: str = "tester") -> User:
    return User.objects.create_user(username=username, password="pw-12345")


def test_userprofile_one_to_one_and_str() -> None:
    """Профиль 1:1 создаётся сигналом при появлении пользователя; доступен как `user.profile`."""
    u = _user("ivan")
    profile = u.profile  # автосоздан сигналом (Ф10·3)
    profile.role_note = "аналитик"
    profile.organization = "РЭУ"
    profile.save()
    assert UserProfile.objects.get(user=u) == profile
    assert profile.organization == "РЭУ"
    assert str(profile) == "Профиль: ivan"


def test_userprofile_cascade_on_user_delete() -> None:
    """Удаление пользователя каскадно удаляет его профиль (OneToOne, CASCADE)."""
    u = _user("petr")
    assert UserProfile.objects.filter(user=u).exists()  # автосоздан сигналом
    u.delete()
    assert UserProfile.objects.count() == 0


def test_savedview_config_json_roundtrip() -> None:
    """config хранит параметры экрана (а не данные) и переживает round-trip без потерь."""
    u = _user("anna")
    cfg = {"year": 2024, "okato": "45000000", "measure": "index", "scheme": "equal"}
    sv = SavedView.objects.create(user=u, name="Москва 2024", config=cfg)
    sv.refresh_from_db()
    assert sv.config == cfg
    assert str(sv) == "Москва 2024 (anna)"


def test_savedview_unique_name_per_user() -> None:
    """Имя сохранённого вида уникально в пределах пользователя (UniqueConstraint)."""
    u = _user("olga")
    SavedView.objects.create(user=u, name="вид", config={})
    with pytest.raises(IntegrityError), transaction.atomic():
        SavedView.objects.create(user=u, name="вид", config={})


def test_savedview_same_name_different_users_ok() -> None:
    """Одинаковое имя вида у разных пользователей допустимо (ограничение — только в паре)."""
    u1, u2 = _user("u1"), _user("u2")
    SavedView.objects.create(user=u1, name="вид", config={})
    SavedView.objects.create(user=u2, name="вид", config={})
    assert SavedView.objects.filter(name="вид").count() == 2


def test_savedview_cascade_and_ordering() -> None:
    """Каскад при удалении пользователя; сортировка по дате создания (новые первыми)."""
    u = _user("sergey")
    older = SavedView.objects.create(user=u, name="старый", config={})
    newer = SavedView.objects.create(user=u, name="новый", config={})
    assert list(SavedView.objects.all()) == [newer, older]
    u.delete()
    assert SavedView.objects.count() == 0


def test_feedback_anonymous_allowed() -> None:
    """Обратная связь может быть анонимной (user=None), т.к. страница публична."""
    fb = FeedbackMessage.objects.create(user=None, text="Спасибо за карту!")
    assert fb.user is None
    assert fb.is_handled is False
    assert str(fb) == "Обратная связь от аноним"


def test_feedback_user_set_null_on_delete() -> None:
    """При удалении пользователя сообщение сохраняется, а ссылка обнуляется (SET_NULL)."""
    u = _user("author")
    fb = FeedbackMessage.objects.create(user=u, text="есть замечание")
    assert str(fb) == "Обратная связь от author"
    u.delete()
    fb.refresh_from_db()
    assert fb.user_id is None
    assert FeedbackMessage.objects.count() == 1


def test_exportjob_choices_and_defaults() -> None:
    """Формат/статус ограничены choices; статус по умолчанию `done` (синхронный экспорт)."""
    u = _user("exporter")
    job = ExportJob.objects.create(user=u, okato="45000000", fmt=ExportJob.Format.XLSX)
    assert job.status == ExportJob.Status.DONE
    assert job.fmt == "xlsx"
    assert not job.file
    assert str(job) == "Экспорт 45000000 → xlsx (done)"


def test_exportjob_cascade_on_user_delete() -> None:
    """Задания экспорта удаляются вместе с пользователем (CASCADE)."""
    u = _user("temp")
    ExportJob.objects.create(user=u, okato="01000000", fmt=ExportJob.Format.DOCX)
    u.delete()
    assert ExportJob.objects.count() == 0


def test_auditlog_set_null_and_ordering() -> None:
    """Аудит переживает удаление пользователя (SET_NULL); сортировка по времени (новые первыми)."""
    u = _user("admin-user")
    first = AuditLog.objects.create(user=u, action="login")
    second = AuditLog.objects.create(user=u, action="export:xlsx okato=45000000")
    assert list(AuditLog.objects.all()) == [second, first]
    assert str(second) == "admin-user: export:xlsx okato=45000000"
    u.delete()
    assert AuditLog.objects.count() == 2
    assert AuditLog.objects.filter(user__isnull=True).count() == 2


def test_auditlog_str_system_when_no_user() -> None:
    """Без пользователя автор действия в __str__ — «система»."""
    entry = AuditLog.objects.create(user=None, action="pipeline:refresh")
    assert str(entry) == "система: pipeline:refresh"
