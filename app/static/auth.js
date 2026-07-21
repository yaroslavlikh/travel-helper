const $ = (selector) => document.querySelector(selector);

function returnTarget() {
  const requested = new URLSearchParams(window.location.search).get("return_to") || "/";
  return requested.startsWith("/") && !requested.startsWith("//") && !requested.includes("\\")
    ? requested
    : "/";
}

const target = returnTarget();
const loginError = new URLSearchParams(window.location.search).get("error");

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
      $("#auth-card-title").textContent = "Войти в Тудавай";
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
