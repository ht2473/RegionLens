// Удобные вход/регистрация: показ/скрытие пароля и живая подсказка по имени пользователя.
(function () {
  "use strict";

  // Показ/скрытие пароля для каждого поля .pass-box.
  var boxes = document.querySelectorAll(".pass-box");
  for (var i = 0; i < boxes.length; i++) {
    (function (box) {
      var input = box.querySelector("input");
      var btn = box.querySelector(".pass-toggle");
      if (!input || !btn) return;
      btn.addEventListener("click", function () {
        var show = input.type === "password";
        input.type = show ? "text" : "password";
        btn.textContent = show ? gettext("Скрыть") : gettext("Показать");
        input.focus();
      });
    })(boxes[i]);
  }

  // Живая подсказка для имени пользователя: только буквы/цифры, счётчик до 40.
  var uname = document.getElementById("id_username");
  var hint = document.getElementById("uname-hint");
  if (uname && hint) {
    var MAX = 40;
    var RE = /^[0-9A-Za-zА-Яа-яЁё]+$/;
    var countEl = hint.querySelector(".uname-count");
    var msgEl = hint.querySelector(".uname-msg");
    uname.setAttribute("maxlength", String(MAX));
    var check = function () {
      var v = uname.value;
      if (countEl) countEl.textContent = v.length + "/" + MAX;
      hint.classList.remove("ok", "bad");
      if (!v) {
        if (msgEl) msgEl.textContent = gettext("Только буквы и цифры");
        return;
      }
      if (!RE.test(v)) {
        hint.classList.add("bad");
        if (msgEl) msgEl.textContent = gettext("Только буквы и цифры, без пробелов и символов");
      } else {
        hint.classList.add("ok");
        if (msgEl) msgEl.textContent = gettext("Имя подходит");
      }
    };
    uname.addEventListener("input", check);
    check();
  }
})();
