const $ = (selector) => document.querySelector(selector);

function returnTarget() {
  const requested = new URLSearchParams(window.location.search).get("return_to") || "/";
  return requested.startsWith("/") && !requested.startsWith("//") && !requested.includes("\\")
    ? requested
    : "/";
}

const target = returnTarget();
const loginError = new URLSearchParams(window.location.search).get("error");
let passwordMode = "register";

function showState(id) {
  ["#auth-loading", "#auth-ready", "#auth-signed-in", "#auth-unavailable-state"]
    .forEach((selector) => $(selector).classList.toggle("hidden", selector !== id));
}

function showError(message) {
  $("#auth-error").textContent = message;
  $("#auth-error").classList.remove("hidden");
}

function continueToWorkspace() {
  window.location.assign(target);
}

function setPasswordMode(mode) {
  passwordMode = mode;
  const registering = mode === "register";
  const passwordAvailable = $("#password-form").dataset.enabled === "true";
  $("#password-form").classList.toggle("hidden", !passwordAvailable);
  $("#password-confirm-row").classList.toggle("hidden", !registering);
  $("#password-confirm").required = registering;
  $("#password-value").autocomplete = registering ? "new-password" : "current-password";
  $("#password-submit").innerHTML = registering
    ? 'Создать аккаунт <span aria-hidden="true">→</span>'
    : 'Войти <span aria-hidden="true">→</span>';
  $("#password-mode").textContent = registering
    ? "Уже есть аккаунт? Войти"
    : "Нет аккаунта? Создать";
}

async function initializeAuthPage() {
  try {
    const response = await fetch("/account/me", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("Не удалось проверить состояние входа");
    const status = await response.json();
    if (status.authenticated) {
      const name = status.account?.display_name || status.account?.email || "Аккаунт";
      $("#auth-card-title").textContent = "Вы уже вошли";
      $("#profile-name").textContent = name;
      $("#profile-initial").textContent = name.trim().slice(0, 1).toUpperCase() || "Т";
      $("#auth-logout").dataset.csrf = status.csrf_token || "";
      showState("#auth-signed-in");
      return;
    }
    if (status.auth_enabled) {
      const passwordEnabled = Boolean(status.password_enabled);
      $("#password-form").dataset.enabled = passwordEnabled ? "true" : "";
      $("#password-form").classList.toggle("hidden", !passwordEnabled);
      $("#password-mode").classList.toggle("hidden", !passwordEnabled);
      $("#provider-choice").classList.toggle("hidden", !passwordEnabled || !status.oidc_enabled);
      $("#provider-login").classList.toggle("hidden", !status.oidc_enabled);
      $("#auth-card-title").textContent = passwordEnabled ? "Создайте аккаунт" : "Войти в Тудавай";
      setPasswordMode("register");
      showState("#auth-ready");
      return;
    }
    $("#auth-card-title").textContent = "Гостевой режим готов";
    showState("#auth-unavailable-state");
  } catch (error) {
    $("#auth-card-title").textContent = "Не удалось подключиться";
    showState("#auth-unavailable-state");
    showError(`${error.message}. Гостевые поездки всё равно доступны.`);
  }
}

if (loginError) {
  showError("Не удалось завершить вход. Попробуйте ещё раз или продолжите без аккаунта.");
}

$("#provider-login").addEventListener("click", () => {
  window.location.assign(`/auth/login?return_to=${encodeURIComponent(target)}`);
});
$("#password-mode").addEventListener("click", () => {
  setPasswordMode(passwordMode === "register" ? "login" : "register");
});
$("#password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = $("#password-email").value;
  const password = $("#password-value").value;
  if (passwordMode === "register" && password !== $("#password-confirm").value) {
    showError("Пароли не совпадают.");
    return;
  }
  const response = await fetch(`/auth/password/${passwordMode === "register" ? "register" : "login"}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    showError(payload.detail || "Не удалось выполнить вход. Попробуйте ещё раз.");
    return;
  }
  continueToWorkspace();
});
$("#guest-continue").addEventListener("click", continueToWorkspace);
$("#signed-continue").addEventListener("click", continueToWorkspace);
$("#unavailable-continue").addEventListener("click", continueToWorkspace);
$("#auth-logout").addEventListener("click", async (event) => {
  const response = await fetch("/auth/logout", {
    method: "POST",
    headers: { "X-CSRF-Token": event.currentTarget.dataset.csrf || "" },
  });
  if (!response.ok) {
    showError("Не удалось выйти. Обновите страницу и попробуйте ещё раз.");
    return;
  }
  window.location.reload();
});

initializeAuthPage();
