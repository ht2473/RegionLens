"""Формы приложения core (Ф10).

- `RegistrationForm` — публичная регистрация (имя, e-mail, пароль);
- `ProfileForm` — редактирование профиля в кабинете (организация, заметка, e-mail);
- `SavedViewForm` — создание сохранённого вида из параметров экрана (год/мера/схема/регион);
  собирает только КОНФИГ (не данные) — инвариант «двух миров» (Хартия §5).
"""

from __future__ import annotations

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from core.models import UserProfile

# Меры карты и схемы весов индекса — согласованы с REFERENCE §1 и эндпойнтами Ф6.
_MEASURE_CHOICES = [("cluster", "Тип (кластер)"), ("index", "Индекс развития")]
_SCHEME_CHOICES = [("equal", "Равные веса"), ("pca", "PCA"), ("expert", "Экспертные")]


class RegistrationForm(UserCreationForm):
    """Регистрация пользователя: имя, e-mail (необязательно) и пароль с подтверждением."""

    email = forms.EmailField(required=False, label="E-mail (необязательно)")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")


class ProfileForm(forms.ModelForm):
    """Редактирование профиля: организация, заметка о роли и e-mail (хранится в `User`)."""

    email = forms.EmailField(required=False, label="E-mail")

    class Meta:
        model = UserProfile
        fields = ("organization", "role_note")


class SavedViewForm(forms.Form):
    """Параметры сохранённого вида. `to_config()` собирает JSON-конфиг экрана (без данных)."""

    name = forms.CharField(max_length=200, label="Название")
    year = forms.IntegerField(min_value=2010, max_value=2024, initial=2024, label="Год")
    measure = forms.ChoiceField(choices=_MEASURE_CHOICES, label="Мера карты")
    scheme = forms.ChoiceField(choices=_SCHEME_CHOICES, label="Схема индекса")
    okato = forms.CharField(max_length=20, required=False, label="ОКАТО региона (необязательно)")

    def to_config(self) -> dict[str, object]:
        """Собрать конфиг экрана из очищенных данных (только параметры, не аналитика)."""
        config: dict[str, object] = {
            "year": self.cleaned_data["year"],
            "measure": self.cleaned_data["measure"],
            "scheme": self.cleaned_data["scheme"],
        }
        okato = self.cleaned_data.get("okato")
        if okato:
            config["okato"] = okato
        return config
