"""Формы приложения core (Ф10).

`RegistrationForm` — публичная регистрация: имя пользователя, необязательный e-mail и
пароль с подтверждением (валидаторы пароля — из settings.AUTH_PASSWORD_VALIDATORS).
"""

from __future__ import annotations

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class RegistrationForm(UserCreationForm):
    """Регистрация пользователя: имя, e-mail (необязательно) и пароль с подтверждением."""

    email = forms.EmailField(required=False, label="E-mail (необязательно)")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")
