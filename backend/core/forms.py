"""Формы приложения core (Ф10).

- `RegistrationForm` — публичная регистрация (имя, e-mail, пароль);
- `ProfileForm` — редактирование профиля в кабинете (организация, заметка, e-mail);
- `SavedViewForm` — создание сохранённого вида из параметров экрана (год/мера/схема/регион);
  собирает только КОНФИГ (не данные) — инвариант «двух миров».
"""

from __future__ import annotations

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

from core.models import UserProfile

# Меры карты и схемы весов индекса согласованы со справочником показателей и API.
_MEASURE_CHOICES = [("cluster", _("Тип (кластер)")), ("index", _("Индекс развития"))]
_SCHEME_CHOICES = [("equal", _("Равные веса")), ("pca", "PCA"), ("expert", _("Экспертные"))]


# Имя пользователя: только буквы (латиница/кириллица) и цифры, без пробелов и символов.
USERNAME_RE = r"^[0-9A-Za-zА-Яа-яЁё]+$"
USERNAME_MAX = 40
_username_validator = RegexValidator(
    USERNAME_RE,
    _("Имя пользователя может содержать только буквы и цифры (без пробелов и символов)."),
)


class RegistrationForm(UserCreationForm):
    """Регистрация пользователя: имя, e-mail (необязательно) и пароль с подтверждением."""

    username = forms.CharField(
        label=_("Имя пользователя"),
        max_length=USERNAME_MAX,
        validators=[_username_validator],
        help_text=_("Только буквы и цифры, до 40 символов."),
    )
    email = forms.EmailField(required=False, label=_("E-mail (необязательно)"))

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")


class ProfileForm(forms.ModelForm):
    """Редактирование профиля: организация, заметка о роли и e-mail (хранится в `User`)."""

    email = forms.EmailField(required=False, label=_("E-mail"))

    class Meta:
        model = UserProfile
        fields = ("organization", "role_note")


class SavedViewForm(forms.Form):
    """Параметры сохранённого вида. `to_config()` собирает JSON-конфиг экрана (без данных)."""

    name = forms.CharField(max_length=200, label=_("Название"))
    year = forms.IntegerField(min_value=2010, max_value=2024, initial=2024, label=_("Год"))
    measure = forms.ChoiceField(choices=_MEASURE_CHOICES, label=_("Мера карты"))
    scheme = forms.ChoiceField(choices=_SCHEME_CHOICES, label=_("Схема индекса"))
    okato = forms.CharField(max_length=20, required=False, label=_("ОКАТО региона (необязательно)"))

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


class PreferencesForm(forms.ModelForm):
    """Пользовательские предпочтения отображения: дефолтные год, схема весов и мера карты.

    Значения применяются как начальные на аналитических страницах (через глобальный
    `window.RL_PREFS`); URL-параметр всегда важнее предпочтения (deep-link не ломается).
    """

    default_year = forms.TypedChoiceField(
        choices=[(y, str(y)) for y in range(2024, 2009, -1)],
        coerce=int,
        label=_("Год по умолчанию"),
    )
    default_scheme = forms.ChoiceField(choices=_SCHEME_CHOICES, label=_("Схема весов по умолчанию"))
    default_measure = forms.ChoiceField(
        choices=_MEASURE_CHOICES, label=_("Мера карты по умолчанию")
    )

    class Meta:
        model = UserProfile
        fields = ["default_year", "default_scheme", "default_measure"]

    def clean_default_year(self) -> int:
        """Ограничить год окном доступных данных (2010–2024)."""
        year = self.cleaned_data["default_year"]
        if not (2010 <= year <= 2024):
            raise forms.ValidationError(_("Год должен быть в диапазоне 2010–2024."))
        return year
