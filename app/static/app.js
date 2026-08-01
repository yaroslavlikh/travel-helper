const STORAGE_KEY = "travel-chat-state-v1";
const ACCOUNT_CACHE_PREFIX = "travel-account-chat-state-v1:";
const SIDEBAR_COLLAPSED_KEY = "travel-sidebar-collapsed-v1";
const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];
const FIELD_LABELS = {
  origin_city: "город вылета",
  origin_country: "страна вылета",
  citizenship: "гражданство",
  month: "месяц",
  date_from: "дата начала",
  date_to: "дата окончания",
  departure_window_from: "окно вылета с",
  departure_window_to: "окно вылета по",
  flight_departure_date: "точная дата вылета",
  flight_return_date: "точная дата возвращения",
  flight_one_way: "билет в одну сторону",
  duration_nights_min: "минимум ночей",
  duration_nights_max: "максимум ночей",
  date_flexibility_days: "гибкость дат",
  adults: "путешественники",
  children: "дети",
  infants: "младенцы",
  budget_total_rub: "бюджет",
  budget_strict: "строгость бюджета",
  destination_scope: "география",
  destination_country_codes: "страны назначения",
  max_flight_duration_hours: "длительность перелёта",
  visa_willingness: "виза",
  sea_required: "море",
  trip_style: "формат отдыха",
  heat_tolerance: "отношение к жаре",
  rain_avoidance: "отношение к дождям",
  preferred_max_temperature_c: "максимальная температура",
  baggage_required: "багаж",
  preferences: "предпочтения",
  avoid: "что исключить",
  avoided_features: "нежелательные особенности",
  priorities: "приоритеты",
};
const $ = (selector) => document.querySelector(selector);
const messageList = $("#message-list");
const composer = $("#composer");
const messageInput = $("#message-input");
const sendButton = $("#send-button");
const destinationComposer = $("#destination-composer");
const destinationInput = $("#destination-input");
let busy = false;
let destinationBusy = false;
let activeDestinationId = null;
let accountReady = false;
let accountState = {
  authEnabled: false,
  authenticated: false,
  account: null,
  csrfToken: null,
};
const syncTimers = new Map();
let syncState = "idle";

function id() {
  return globalThis.crypto?.randomUUID?.() || `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function now() {
  return new Date().toISOString();
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
  } catch {
    return "#";
  }
}

function entryAssessmentCopy(candidate) {
  const assessment = candidate.entry_assessment;
  if (!assessment || assessment.confidence !== "verified") return "Условия въезда пока не проверены";
  if (assessment.outcome === "eligible" && assessment.requirement === "visa_free") return "Без визы";
  if (assessment.outcome === "requires_pretrip_action") return "Нужно оформить до поездки";
  return "Требуется проверка условий въезда";
}

function defaultGreeting() {
  return {
    id: id(),
    role: "assistant",
    text: "Привет! Я помогу выбрать не просто страну, а конкретный сценарий поездки: куда лететь, где жить и что там делать. Пишите как другу — можно начать с настроения, бюджета или дат.",
    createdAt: now(),
  };
}

function createChat() {
  const createdAt = now();
  return {
    id: id(),
    title: "Новая поездка",
    createdAt,
    updatedAt: createdAt,
    messages: [defaultGreeting()],
    snapshot: null,
    recommendations: [],
    destinationThreads: {},
  };
}

function hydrateAdvisoryQuestion(chat) {
  delete chat.pendingQuestionMessageId;
  for (const message of chat.messages || []) {
    delete message.questions;
    delete message.advisoryQuestion;
  }
}

function hasUserMessage(chat) {
  return (chat.messages || []).some((message) => message.role === "user");
}

function loadGuestStore() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (saved?.chats?.length) {
      saved.chats.forEach((chat) => {
        chat.destinationThreads = chat.destinationThreads || {};
        hydrateAdvisoryQuestion(chat);
      });
      const chats = saved.chats.filter(hasUserMessage);
      const retained = chats.length ? chats : [saved.chats[0]];
      const activeExists = retained.some((chat) => chat.id === saved.activeChatId);
      return {
        activeChatId: activeExists ? saved.activeChatId : retained[0].id,
        chats: retained,
      };
    }
  } catch (error) {
    console.warn("Не удалось восстановить локальную историю", error);
  }
  const chat = createChat();
  return { activeChatId: chat.id, chats: [chat] };
}

let store = loadGuestStore();

function setSidebarCollapsed(collapsed) {
  document.body.dataset.sidebarCollapsed = String(collapsed);
  const toggle = $("#sidebar-toggle");
  toggle.setAttribute("aria-expanded", String(!collapsed));
  toggle.setAttribute("aria-label", collapsed ? "Развернуть историю чатов" : "Свернуть историю чатов");
  toggle.title = toggle.getAttribute("aria-label");
  try {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed));
  } catch {
    // The workspace remains usable when private browsing rejects local storage.
  }
}

function persist() {
  const key = accountState.authenticated
    ? `${ACCOUNT_CACHE_PREFIX}${accountState.account.id}`
    : STORAGE_KEY;
  localStorage.setItem(key, JSON.stringify(store));
}

function activeChat() {
  return store.chats.find((chat) => chat.id === store.activeChatId);
}

function touch(chat) {
  chat.updatedAt = now();
  persist();
  scheduleChatSync(chat);
}

function accountHeaders({ json = true, csrf = false } = {}) {
  const headers = {};
  if (json) headers["Content-Type"] = "application/json";
  if (csrf && accountState.csrfToken) headers["X-CSRF-Token"] = accountState.csrfToken;
  return headers;
}

async function refreshAccountState() {
  const response = await fetch("/account/me");
  if (!response.ok) throw new Error("Не удалось обновить сессию аккаунта");
  const status = await response.json();
  accountState = {
    authEnabled: status.auth_enabled,
    authenticated: status.authenticated,
    account: status.account,
    csrfToken: status.csrf_token,
  };
  renderAccountPanel();
  return status;
}

async function accountFetch(url, options) {
  const response = await fetch(url, options);
  if (!accountState.authenticated || response.status !== 403) return response;

  const payload = await response.clone().json().catch(() => null);
  if (payload?.detail !== "Invalid CSRF token") return response;

  const status = await refreshAccountState();
  if (!status.authenticated || !accountState.csrfToken) return response;
  const headers = new Headers(options.headers);
  headers.set("X-CSRF-Token", accountState.csrfToken);
  return fetch(url, { ...options, headers });
}

function serverRecordToChat(record) {
  const chat = { ...record.payload, id: record.id, title: record.title };
  chat.createdAt = chat.createdAt || record.created_at;
  chat.updatedAt = record.updated_at || chat.updatedAt || now();
  chat.messages = chat.messages?.length ? chat.messages : [defaultGreeting()];
  chat.recommendations = chat.recommendations || [];
  chat.destinationThreads = chat.destinationThreads || {};
  hydrateAdvisoryQuestion(chat);
  return chat;
}

function setSyncState(state, label) {
  syncState = state;
  const indicator = $("#sync-status");
  if (indicator) {
    indicator.dataset.state = state;
    indicator.textContent = label || {
      idle: "История синхронизируется",
      saving: "Сохраняю изменения…",
      saved: "Все изменения сохранены",
      error: "Не удалось синхронизировать",
    }[state];
  }
  if (accountState.authenticated && $("#composer-note")) {
    $("#composer-note").textContent = state === "error"
      ? "Локальная копия сохранена · синхронизация не удалась"
      : `${state === "saving" ? "Сохраняю в аккаунт…" : "Синхронизировано с аккаунтом"} · Enter — отправить, Shift+Enter — новая строка`;
  }
}

async function saveAccountChat(chat, { keepalive = false } = {}) {
  if (!accountState.authenticated) return;
  setSyncState("saving");
  const body = JSON.stringify({ title: chat.title, payload: chat });
  const response = await accountFetch(`/account/chats/${encodeURIComponent(chat.id)}`, {
    method: "PUT",
    headers: accountHeaders({ csrf: true }),
    body,
    keepalive: keepalive && body.length < 60_000,
  });
  if (!response.ok) {
    setSyncState("error");
    throw new Error("Не удалось синхронизировать чат");
  }
  setSyncState("saved");
}

function scheduleChatSync(chat) {
  if (!accountState.authenticated) return;
  clearTimeout(syncTimers.get(chat.id));
  syncTimers.set(chat.id, setTimeout(() => {
    syncTimers.delete(chat.id);
    saveAccountChat(chat).catch((error) => console.warn(error.message));
  }, 350));
}

function flushPendingSyncs() {
  if (!accountState.authenticated || !syncTimers.size) return;
  const pendingIds = [...syncTimers.keys()];
  pendingIds.forEach((chatId) => {
    clearTimeout(syncTimers.get(chatId));
    syncTimers.delete(chatId);
    const chat = store.chats.find((item) => item.id === chatId);
    if (chat) saveAccountChat(chat, { keepalive: true }).catch((error) => console.warn(error.message));
  });
}

function shortTime(dateValue) {
  return new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" }).format(new Date(dateValue));
}

function relativeDate(dateValue) {
  const date = new Date(dateValue);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return "сегодня";
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" }).format(date);
}

function titleFromQuery(query) {
  const clean = query.replace(/\s+/g, " ").trim();
  return clean.length > 32 ? `${clean.slice(0, 32).trim()}…` : clean;
}

function addMessage(chat, message) {
  chat.messages.push({ id: id(), createdAt: now(), ...message });
  if (message.role === "user" && chat.title === "Новая поездка") chat.title = titleFromQuery(message.text);
  touch(chat);
}

function renderChatList() {
  const chats = [...store.chats].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  $("#chat-list").innerHTML = chats.map((chat) => `
    <div class="chat-row">
      <button class="chat-item ${chat.id === store.activeChatId ? "active" : ""}" type="button" data-chat-id="${escapeHtml(chat.id)}"${chat.id === store.activeChatId ? ' aria-current="page"' : ""}>
        <span class="chat-icon" aria-hidden="true">${chat.recommendations?.length ? "✦" : "⌁"}</span>
        <strong>${escapeHtml(chat.title)}</strong>
        <small>${relativeDate(chat.updatedAt)} · ${chat.recommendations?.length ? pluralOptions(chat.recommendations.length) : `${Math.max(0, chat.messages.length - 1)} сообщ.`}</small>
      </button>
      <button class="chat-delete" type="button" data-delete-chat="${escapeHtml(chat.id)}" aria-label="Удалить чат">×</button>
    </div>
  `).join("");
  document.querySelectorAll("[data-chat-id]").forEach((button) => {
    button.addEventListener("click", () => switchChat(button.dataset.chatId));
  });
  document.querySelectorAll("[data-delete-chat]").forEach((button) => {
    button.addEventListener("click", () => deleteChat(button.dataset.deleteChat));
  });
}

function changesMarkup(fields = []) {
  if (!fields.length) return "";
  return `<details class="change-summary"><summary>Что изменилось</summary><ul>${fields.map((field) => `<li>${escapeHtml(FIELD_LABELS[field] || field)}</li>`).join("")}</ul></details>`;
}

function renderMessages() {
  const chat = activeChat();
  const hasStarted = chat.messages.some((message) => message.role === "user");
  messageList.innerHTML = chat.messages.map((message) => {
    if (message.role === "user") {
      return `<article class="message user"><div><div class="bubble"><p>${escapeHtml(message.text).replaceAll("\n", "<br>")}</p></div><div class="message-meta">${shortTime(message.createdAt)}</div></div></article>`;
    }
    return `<article class="message assistant"><span class="avatar assistant-avatar" aria-hidden="true">✦</span><div class="message-content"><div class="message-name">Помощник</div><div class="bubble"><p>${escapeHtml(message.text).replaceAll("\n", "<br>")}</p>${changesMarkup(message.changedFields)}</div><div class="message-meta">${shortTime(message.createdAt)}</div></div></article>`;
  }).join("");
  $("#starter-zone").classList.toggle("hidden", hasStarted);
  $("#chat-view").classList.toggle("starter-visible", !hasStarted);
  requestAnimationFrame(() => { messageList.scrollTop = messageList.scrollHeight; });
}

function formatMoney(value) {
  return `${new Intl.NumberFormat("ru-RU").format(value)} ₽`;
}

function recommendationDiff(previous = [], next = []) {
  const oldIds = previous.map((item) => item.candidate.destination_id);
  const newIds = next.map((item) => item.candidate.destination_id);
  if (!oldIds.length) return next.length ? `Лента собрана: ${pluralOptions(next.length)}.` : "";
  const added = newIds.filter((item) => !oldIds.includes(item));
  const removed = oldIds.filter((item) => !newIds.includes(item));
  const reordered = !added.length && !removed.length && oldIds.join("|") !== newIds.join("|");
  const parts = [];
  if (added.length) parts.push(`добавлено ${added.length}`);
  if (removed.length) parts.push(`убрано ${removed.length}`);
  if (reordered) parts.push("порядок пересчитан");
  return parts.length ? `Лента обновлена: ${parts.join(", ")}.` : "Условия сохранены, состав ленты не изменился.";
}

function setBusy(value) {
  busy = value;
  sendButton.disabled = value;
  messageInput.disabled = value;
  $("#typing").classList.toggle("hidden", !value);
  $("#chat-status").textContent = value ? "Обновляю подборку…" : chatStatus(activeChat());
  renderWorkspaceState();
}

function workspaceState(chat = activeChat()) {
  const hasPlanningContext = Boolean(chat.snapshot || chat.recommendations?.length || activeDestinationId);
  if (hasPlanningContext) return "results";
  if (busy) return "opening";
  return "conversation";
}

function renderWorkspaceState() {
  const state = workspaceState();
  document.body.dataset.workspaceState = state;
  const chat = activeChat();
  const hasRequest = hasUserMessage(chat);
  const steps = {
    request: hasRequest ? "done" : "current",
    clarify: state === "opening" ? "current" : (state === "results" ? "done" : "pending"),
    results: state === "results" ? "current" : "pending",
  };
  document.querySelectorAll("[data-journey-step]").forEach((step) => {
    step.dataset.state = steps[step.dataset.journeyStep];
  });
  const feedTab = document.querySelector('.mobile-tab[data-view="feed"]');
  feedTab.disabled = state === "conversation";
  feedTab.setAttribute("aria-disabled", String(feedTab.disabled));
  if (feedTab.disabled && document.body.dataset.mobileView === "feed") setMobileView("chat");
}

async function requestRecommendation(query) {
  const chat = activeChat();
  const chatId = chat.id;
  const openingStartedAt = Date.now();
  setBusy(true);
  try {
    const request = {
      method: "POST",
      headers: accountState.authenticated
        ? accountHeaders({ csrf: true })
        : { "Content-Type": "application/json" },
      body: JSON.stringify({ query, session_id: chat.id }),
    };
    const response = accountState.authenticated
      ? await accountFetch("/recommend", request)
      : await fetch("/recommend", request);
    const rawPayload = await response.text();
    let payload;
    try {
      payload = JSON.parse(rawPayload);
    } catch {
      throw new Error(response.ok ? "Сервис вернул некорректный ответ" : "Сервис временно недоступен");
    }
    if (!response.ok) throw new Error(payload.detail || "Не удалось получить рекомендации");
    const remainingOpeningTime = Math.max(0, 520 - (Date.now() - openingStartedAt));
    if (remainingOpeningTime) await new Promise((resolve) => setTimeout(resolve, remainingOpeningTime));

    const targetChat = store.chats.find((item) => item.id === chatId);
    if (!targetChat) return;
    const previousRecommendations = targetChat.recommendations || [];
    targetChat.snapshot = payload;
    targetChat.recommendations = payload.recommendations || previousRecommendations;
    targetChat.feedUpdate = payload.status === "completed"
      ? recommendationDiff(previousRecommendations, targetChat.recommendations)
      : "Жду ответы, чтобы собрать ленту точнее.";

    const assistantMessage = {
      role: "assistant",
      text: payload.assistant_message || "Условия поездки сохранены.",
      changedFields: payload.changed_fields || [],
    };
    addMessage(targetChat, assistantMessage);
    touch(targetChat);
    if (store.activeChatId === chatId) renderAll();
  } catch (error) {
    const targetChat = store.chats.find((item) => item.id === chatId);
    if (targetChat) {
      addMessage(targetChat, {
        role: "assistant",
        text: `Не получилось обновить подборку: ${error.message}. Условия чата сохранены — можно повторить сообщение.`,
      });
      if (store.activeChatId === chatId) renderAll();
    }
  } finally {
    if (store.activeChatId === chatId) setBusy(false);
  }
}

function criterionMarkup(label, value, changed) {
  if (value === null || value === undefined || value === "" || value === false) return "";
  return `<span class="criterion ${changed ? "changed" : ""}">${escapeHtml(label)}: ${escapeHtml(value)}</span>`;
}

function renderCriteria(snapshot) {
  const request = snapshot?.parsed_request;
  if (!request) return "";
  const changed = new Set(snapshot.changed_fields || []);
  const scope = { domestic: "Россия", international: "за рубеж", any: "любая" }[request.destination_scope];
  const departureDate = request.flight_departure_date || request.date_from;
  const returnDate = request.flight_return_date || request.date_to;
  const exactDates = departureDate && returnDate
    ? `${departureDate} — ${returnDate}`
    : departureDate;
  const departureWindow = request.departure_window_from && request.departure_window_to
    ? `вылет ${request.departure_window_from} — ${request.departure_window_to}`
    : request.departure_window_from;
  return [
    criterionMarkup("Вылет", request.origin_city, changed.has("origin_city")),
    criterionMarkup("Когда", exactDates || departureWindow || (request.month ? MONTHS[request.month - 1] : null), changed.has("month") || changed.has("date_from") || changed.has("date_to") || changed.has("departure_window_from") || changed.has("departure_window_to") || changed.has("flight_departure_date") || changed.has("flight_return_date")),
    criterionMarkup("Бюджет", request.budget_total_rub ? formatMoney(request.budget_total_rub) : null, changed.has("budget_total_rub")),
    criterionMarkup("Куда", scope, changed.has("destination_scope")),
    criterionMarkup("Перелёт", request.max_flight_duration_hours ? `до ${request.max_flight_duration_hours} ч` : null, changed.has("max_flight_duration_hours")),
    criterionMarkup("Море", request.sea_required ? "обязательно" : null, changed.has("sea_required")),
    criterionMarkup("Дожди", request.rain_avoidance ? "нежелательны" : null, changed.has("rain_avoidance")),
  ].join("");
}

function providerActions(candidate, snapshot, index) {
  const flightLink = (candidate.external_links || []).find((link) => link.category === "flight");
  const stayLink = (candidate.external_links || []).find((link) => link.category === "stay");
  const requestId = snapshot?.request_id || "unknown-request";
  const shared = `data-destination-id="${escapeHtml(candidate.destination_id)}" data-rank="${index + 1}" data-request-id="${escapeHtml(requestId)}"`;
  const actions = [];
  if (flightLink?.url) {
    actions.push(`<a class="travel-link aviasales-link" href="${safeUrl(flightLink.url)}" target="_blank" rel="noreferrer" ${shared} data-provider="aviasales" data-link-kind="flight"><span class="travel-link-icon" aria-hidden="true">✈</span><span class="travel-link-copy"><small>Перейти к поиску</small>${escapeHtml(flightLink.title || "Найти билеты")}</span><i aria-hidden="true">↗</i></a>`);
  }
  if (stayLink?.url) {
    actions.push(`<a class="travel-link yandex-link" href="${safeUrl(stayLink.url)}" target="_blank" rel="noreferrer" ${shared} data-provider="yandex_travel" data-link-kind="stay"><span class="travel-link-icon" aria-hidden="true">⌂</span><span class="travel-link-copy"><small>Яндекс Путешествия</small>Найти жильё</span><i aria-hidden="true">↗</i></a>`);
  }
  if (!actions.length) return "";
  return `<div class="card-actions${actions.length === 1 ? " single" : ""}">${actions.join("")}</div>`;
}

function destinationDiscussionAction(candidate, chat) {
  const thread = chat.destinationThreads?.[candidate.destination_id];
  const messageCount = (thread?.messages || []).filter((message) => message.role === "user").length;
  const countLabel = messageCount ? `<span>${messageCount} сообщ.</span>` : "<span>Новый субчат</span>";
  return `<button class="destination-discuss" type="button" data-discuss-destination="${escapeHtml(candidate.destination_id)}"><span class="destination-discuss-icon" aria-hidden="true">✦</span><span class="destination-discuss-copy"><small>Спросить локального гида</small><strong>Обсудить ${escapeHtml(candidate.city_or_region)}</strong></span>${countLabel}<i aria-hidden="true">→</i></button>`;
}

function destinationCard(item, index, chat) {
  const candidate = item.candidate;
  const image = candidate.image;
  const imageUrl = safeUrl(image?.url);
  const highlights = (candidate.highlights || []).map((place, placeIndex) => `
    <a class="place" href="${safeUrl(place.url)}" target="_blank" rel="noreferrer">
      <i aria-hidden="true">${String(placeIndex + 1).padStart(2, "0")}</i><span><strong>${escapeHtml(place.name)}</strong><small>${escapeHtml(place.description)}</small></span><b aria-hidden="true">↗</b>
    </a>`).join("");
  const stayAreas = (candidate.stay_areas || []).map((area) => `<span class="stay-area">${escapeHtml(area)}</span>`).join("");
  const sources = (candidate.sources || []).map((source) => `<a href="${safeUrl(source.url)}" target="_blank" rel="noreferrer"><span aria-hidden="true">↗</span>${escapeHtml(source.title)}</a>`).join("");
  const flight = candidate.flight_duration_hours ? `${candidate.flight_duration_hours} ч · ${candidate.transfers_count || 0} перес.` : "Уточнить";
  const weather = candidate.expected_temperature_c != null ? `${candidate.expected_temperature_c}° · море ${candidate.expected_sea_temperature_c ?? "—"}°` : "Уточнить";
  const actions = providerActions(candidate, chat.snapshot, index);
  const pricing = item.pricing;
  const pricingRows = (pricing?.components || []).map((component) => {
    const value = component.expected_rub != null
      ? formatMoney(component.expected_rub)
      : component.reason || "Нет данных";
    return `<div class="price-breakdown-row ${escapeHtml(component.status)}"><span>${escapeHtml(component.label)}</span><strong>${escapeHtml(value)}</strong></div>`;
  }).join("");
  const pricingMarkup = pricing ? `<section class="price-summary ${escapeHtml(pricing.status)}">
    <div class="price-heading"><span>Бюджет поездки</span><small>на всю группу</small></div>
    <strong>${escapeHtml(pricing.headline)}</strong>
    <p>${escapeHtml(pricing.subtitle)}</p>
    ${pricing.expected_total_rub != null ? `<small class="price-range">От ${formatMoney(pricing.floor_total_rub)} · безопасно до ${formatMoney(pricing.safe_total_rub)}</small>` : ""}
    ${pricingRows ? `<details class="price-breakdown"><summary>${pricing.status === "unavailable" ? "Почему цена недоступна" : "Что входит в расчёт"} <span>＋</span></summary><div>${pricingRows}</div></details>` : ""}
    <small class="price-freshness"><i aria-hidden="true"></i>${escapeHtml(pricing.freshness_label)}</small>
  </section>` : "";
  const stateLabels = {
    ELIGIBLE: "Подтверждённый вариант",
    CONDITIONAL: "Нужно проверить условия",
    FALLBACK: "Ближайший вариант",
  };
  const rankingState = item.state || "ELIGIBLE";
  const stateLabel = stateLabels[rankingState];
  const stateReason = ["CONDITIONAL", "FALLBACK"].includes(rankingState)
    ? (item.cons || [])[0] || (item.assumptions || [])[0] || "Требуется дополнительная проверка."
    : "";
  const pros = (item.pros || []).slice(0, 3).map((pro) => `<li><span aria-hidden="true">✓</span>${escapeHtml(pro)}</li>`).join("");
  const positionLabel = index === 0 ? "Лучшее совпадение" : `Вариант ${index + 1}`;
  return `<article class="destination-card${index === 0 ? " featured" : ""}" style="--card-index: ${index}">
    <div class="card-image">
      ${image ? `<img src="${imageUrl}" alt="${escapeHtml(image.alt)}" loading="lazy" />` : ""}
      <div class="image-shade"></div>
      <div class="card-topline"><span class="rank-badge">${escapeHtml(positionLabel)}</span><span class="demo-tag">Модельная оценка</span></div>
      <span class="ranking-state ${escapeHtml(rankingState.toLowerCase())}"><i aria-hidden="true"></i>${escapeHtml(stateLabel)}</span>
      <div class="image-caption"><div><p>${escapeHtml(candidate.country)} · ${escapeHtml(candidate.nearest_airport || "аэропорт уточняется")}</p><h3>${escapeHtml(candidate.city_or_region)}</h3></div><span class="score-pill"><strong>${Math.round(item.total_score)}%</strong><small>совпадение</small></span></div>
      ${image ? `<a class="image-credit" href="${safeUrl(image.source_url)}" target="_blank" rel="noreferrer">Фото: ${escapeHtml(image.credit)}</a>` : ""}
    </div>
    <div class="card-body">
      <div class="card-overview${pricing ? "" : " no-price"}">
        ${pricingMarkup}
        <div class="quick-metrics">
          <div class="quick-metric"><span aria-hidden="true">↗</span><div><small>Дорога</small><strong>${escapeHtml(flight)}</strong></div></div>
          <div class="quick-metric"><span aria-hidden="true">☼</span><div><small>Сезон</small><strong>${escapeHtml(weather)}</strong></div></div>
          <div class="quick-metric"><span aria-hidden="true">◎</span><div><small>Въезд</small><strong>${escapeHtml(entryAssessmentCopy(candidate))}</strong></div></div>
        </div>
      </div>
      ${stateReason ? `<p class="ranking-note ${escapeHtml(rankingState.toLowerCase())}">${escapeHtml(stateReason)}</p>` : ""}
      ${pros ? `<section class="card-section card-pros"><h4>Почему это может быть ваше</h4><ul>${pros}</ul></section>` : ""}
      ${highlights ? `<section class="card-section"><div class="section-heading"><h4>Что посмотреть</h4><span>Конкретные места</span></div><div class="place-list">${highlights}</div></section>` : ""}
      ${stayAreas ? `<section class="card-section stay-section"><h4>Где остановиться</h4><div class="stay-areas">${stayAreas}</div></section>` : ""}
      ${destinationDiscussionAction(candidate, chat)}
      ${actions}
      ${actions ? '<p class="external-note"><span aria-hidden="true">i</span> Откроется внешний поиск — цены и наличие уточняются там</p>' : ""}
      <details class="card-details"><summary><span>Обоснование, риски и источники</span><i aria-hidden="true">＋</i></summary><div class="card-details-content"><p class="detail-copy">${escapeHtml(item.explanation)} ${item.risks?.length ? `<strong>Риски:</strong> ${escapeHtml(item.risks.join("; "))}.` : ""}</p><div class="source-links">${sources}</div></div></details>
    </div>
  </article>`;
}

function pluralOptions(count) {
  const last = count % 10;
  const lastTwo = count % 100;
  if (last === 1 && lastTwo !== 11) return `${count} вариант`;
  if ([2, 3, 4].includes(last) && ![12, 13, 14].includes(lastTwo)) return `${count} варианта`;
  return `${count} вариантов`;
}

function planningContextMarkup(snapshot) {
  const confidence = snapshot?.planning_confidence;
  if (!confidence) return "";
  const level = {
    high: "уверенная основа",
    medium: "есть условия для уточнения",
    low: "широкий ориентир",
  }[confidence.level] || "ориентир";
  const next = snapshot?.next_best_question;
  const question = next?.question
    ? `<p>Если захочется сузить подборку: <strong>${escapeHtml(next.question)}</strong></p>`
    : "";
  return `<section class="planning-context ${escapeHtml(confidence.level || "low")}">
    <div><span>Точность планирования</span><strong>${escapeHtml(level)}</strong></div>
    <p>${escapeHtml(confidence.summary || "Подборка учитывает доступные условия.")}</p>
    ${question}<small>На него можно не отвечать сейчас — текущая подборка уже рабочая.</small>
  </section>`;
}

function renderFeed() {
  const chat = activeChat();
  const recommendations = chat.recommendations || [];
  $("#criteria").innerHTML = renderCriteria(chat.snapshot);
  $("#result-count").textContent = pluralOptions(recommendations.length);
  $("#mobile-count").textContent = recommendations.length;
  $("#feed-empty").classList.toggle("hidden", Boolean(recommendations.length));
  $("#recommendation-list").innerHTML = recommendations.map((item, index) => destinationCard(item, index, chat)).join("");
  document.querySelectorAll(".travel-link[data-provider]").forEach((link) => {
    link.addEventListener("click", () => trackTravelLink(link));
  });
  document.querySelectorAll("[data-discuss-destination]").forEach((button) => {
    button.addEventListener("click", () => openDestinationChat(button.dataset.discussDestination));
  });
  const update = $("#feed-update");
  update.textContent = chat.feedUpdate || "";
  update.classList.toggle("hidden", !chat.feedUpdate);
  const notices = chat.snapshot?.warnings || [];
  $("#feed-notices").innerHTML = [
    planningContextMarkup(chat.snapshot),
    ...notices.map((notice) => `<div class="notice">${escapeHtml(notice)}</div>`),
  ].join("");
}

function trackTravelLink(link) {
  const chat = activeChat();
  const payload = {
    session_id: chat.id,
    request_id: link.dataset.requestId,
    destination_id: link.dataset.destinationId,
    rank: Number(link.dataset.rank),
    provider: link.dataset.provider,
    link_kind: link.dataset.linkKind,
  };
  fetch("/events/travel-link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => undefined);
}

function recommendationById(chat, destinationId) {
  return (chat.recommendations || []).find((item) => item.candidate.destination_id === destinationId);
}

function ensureDestinationThread(chat, recommendation) {
  const candidate = recommendation.candidate;
  chat.destinationThreads = chat.destinationThreads || {};
  if (!chat.destinationThreads[candidate.destination_id]) {
    chat.destinationThreads[candidate.destination_id] = {
      destinationId: candidate.destination_id,
      destinationName: candidate.city_or_region,
      updatedAt: now(),
      messages: [{
        id: id(),
        role: "assistant",
        text: `Давайте отдельно разберём ${candidate.city_or_region}. Я помню условия этой поездки и опираюсь на текущую карточку; основную подборку здесь не меняю без вашего подтверждения.`,
        createdAt: now(),
        quickReplies: ["Где лучше остановиться?", "Что посмотреть рядом?", "Какие есть риски?"],
      }],
    };
    touch(chat);
  }
  return chat.destinationThreads[candidate.destination_id];
}

function addDestinationMessage(chat, destinationId, message) {
  const thread = chat.destinationThreads[destinationId];
  thread.messages.push({ id: id(), createdAt: now(), quickReplies: [], ...message });
  thread.updatedAt = now();
  touch(chat);
}

function openDestinationChat(destinationId) {
  if (busy || destinationBusy) return;
  const chat = activeChat();
  const recommendation = recommendationById(chat, destinationId);
  if (!recommendation) return;
  ensureDestinationThread(chat, recommendation);
  activeDestinationId = destinationId;
  renderDestinationChat();
  setMobileView("feed");
  destinationInput.focus();
}

function closeDestinationChat() {
  if (destinationBusy) return;
  activeDestinationId = null;
  renderDestinationChat();
}

function destinationMessageMarkup(message) {
  const applyAction = message.proposedTripChange
    ? `<button class="apply-trip-change" type="button" data-apply-trip-change="${escapeHtml(message.proposedTripChange)}">Применить ко всей поездке <span>→</span></button>`
    : "";
  const places = (message.places || []).map((place, index) => `
    <a class="destination-poi" href="${safeUrl(place.description?.source?.url || place.source?.url)}" target="_blank" rel="noreferrer" data-place-id="${escapeHtml(place.place_id)}" data-place-position="${index + 1}" data-place-retrieval-id="${escapeHtml(message.placeRetrievalId || "")}" data-place-ranking-version="${escapeHtml(message.placeRankingVersion || "")}">
      <strong>${escapeHtml(place.name)}</strong><span>${escapeHtml(place.category || "Место")} · ${escapeHtml((place.tags || []).slice(0, 3).join(" · "))}</span>${place.description ? `<em>${escapeHtml(place.description.text)}</em><small>Описание: ${escapeHtml(place.description.source?.name || "проверить")}</small>` : ""}<small>Источник: ${escapeHtml(place.source?.name || "проверить")}</small>
    </a>`).join("");
  const placesMarkup = places ? `<section class="destination-pois"><p>Места из каталога</p>${places}</section>` : "";
  const warningsMarkup = (message.warnings || []).map((warning) => `<p class="destination-warning">${escapeHtml(warning)}</p>`).join("");
  return `<article class="destination-message ${message.role}">
    ${message.role === "assistant" ? '<span class="avatar assistant-avatar" aria-hidden="true">✦</span>' : ""}
    <div><div class="destination-bubble">${escapeHtml(message.text).replaceAll("\n", "<br>")}${applyAction}</div>${placesMarkup}${warningsMarkup}<small>${shortTime(message.createdAt)}</small></div>
  </article>`;
}

function renderDestinationChat() {
  const chat = activeChat();
  const recommendation = activeDestinationId ? recommendationById(chat, activeDestinationId) : null;
  const panel = $("#destination-chat-view");
  const isOpen = Boolean(recommendation);
  $("#feed-content").classList.toggle("hidden", isOpen);
  panel.classList.toggle("hidden", !isOpen);
  $("#feed-panel").classList.toggle("subchat-open", isOpen);
  if (!recommendation) {
    activeDestinationId = null;
    return;
  }

  const candidate = recommendation.candidate;
  const thread = ensureDestinationThread(chat, recommendation);
  $("#destination-chat-title").textContent = candidate.city_or_region;
  $("#destination-chat-subtitle").textContent = `${candidate.country} · отдельная ветка этой поездки`;
  const image = $("#destination-chat-image");
  image.src = safeUrl(candidate.image?.url);
  image.alt = candidate.image?.alt || candidate.city_or_region;
  $("#destination-message-list").innerHTML = thread.messages.map(destinationMessageMarkup).join("");
  const latestAssistant = [...thread.messages].reverse().find((message) => message.role === "assistant");
  $("#destination-quick-replies").innerHTML = destinationBusy ? "" : (latestAssistant?.quickReplies || []).map((reply) => `<button type="button" data-destination-starter="${escapeHtml(reply)}">${escapeHtml(reply)}</button>`).join("");
  document.querySelectorAll("[data-destination-starter]").forEach((button) => {
    button.addEventListener("click", () => sendDestinationMessage(button.dataset.destinationStarter));
  });
  document.querySelectorAll("[data-apply-trip-change]").forEach((button) => {
    button.addEventListener("click", () => applyTripChange(button.dataset.applyTripChange));
  });
  document.querySelectorAll("[data-place-id]").forEach((place) => {
    place.addEventListener("click", () => trackDestinationPoi(place));
  });
  destinationInput.disabled = destinationBusy;
  $("#destination-send").disabled = destinationBusy;
  $("#destination-typing").classList.toggle("hidden", !destinationBusy);
  requestAnimationFrame(() => {
    const list = $("#destination-message-list");
    list.scrollTop = list.scrollHeight;
  });
}

async function sendDestinationMessage(text) {
  if (!accountReady || busy || destinationBusy || !text?.trim() || !activeDestinationId) return;
  const chat = activeChat();
  const chatId = chat.id;
  const destinationId = activeDestinationId;
  const query = text.trim();
  addDestinationMessage(chat, destinationId, { role: "user", text: query });
  destinationInput.value = "";
  destinationBusy = true;
  renderDestinationChat();
  try {
    const request = {
      method: "POST",
      headers: accountState.authenticated
        ? accountHeaders({ csrf: true })
        : { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: chatId, destination_id: destinationId, query }),
    };
    const response = accountState.authenticated
      ? await accountFetch("/destination-chat", request)
      : await fetch("/destination-chat", request);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Не удалось получить ответ");
    const targetChat = store.chats.find((item) => item.id === chatId);
    if (!targetChat?.destinationThreads?.[destinationId]) return;
    addDestinationMessage(targetChat, destinationId, {
      role: "assistant",
      text: payload.assistant_message,
      quickReplies: payload.quick_replies || [],
      proposedTripChange: payload.proposed_trip_change || null,
      places: payload.places || [],
      placeRetrievalId: payload.place_retrieval_id || null,
      placeRankingVersion: payload.place_ranking_version || null,
      warnings: payload.warnings || [],
    });
  } catch (error) {
    const targetChat = store.chats.find((item) => item.id === chatId);
    if (targetChat?.destinationThreads?.[destinationId]) {
      addDestinationMessage(targetChat, destinationId, {
        role: "assistant",
        text: `Не получилось продолжить разговор: ${error.message}. История ветки сохранена — попробуйте ещё раз.`,
      });
    }
  } finally {
    destinationBusy = false;
    if (store.activeChatId === chatId && activeDestinationId === destinationId) {
      renderFeed();
      renderDestinationChat();
    }
  }
}

function trackDestinationPoi(place) {
  const chat = activeChat();
  const retrievalId = place.dataset.placeRetrievalId;
  if (!retrievalId) return;
  fetch("/events/place", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event_type: "place_opened",
      session_id: chat.id,
      place_id: place.dataset.placeId,
      retrieval_id: retrievalId,
      position: Number(place.dataset.placePosition),
      ranking_version: place.dataset.placeRankingVersion || null,
    }),
    keepalive: true,
  }).catch(() => undefined);
}

async function applyTripChange(change) {
  if (!change || busy || destinationBusy) return;
  closeDestinationChat();
  setMobileView("chat");
  await sendCurrentMessage(change);
}

function chatStatus(chat) {
  const count = chat.recommendations?.length || 0;
  if (count) return `${pluralOptions(count)} · можно уточнять дальше`;
  return "Расскажите, куда хочется · память включена";
}

function renderAll() {
  const chat = activeChat();
  renderWorkspaceState();
  $("#chat-title").textContent = chat.title;
  $("#chat-status").textContent = busy ? "Обновляю подборку…" : chatStatus(chat);
  renderChatList();
  renderMessages();
  renderFeed();
  renderDestinationChat();
}

function switchChat(chatId) {
  if (busy || destinationBusy || !store.chats.some((chat) => chat.id === chatId)) return;
  activeDestinationId = null;
  store.activeChatId = chatId;
  persist();
  renderAll();
  setMobileView("chat");
}

async function openNewChat() {
  if (!accountReady || busy || destinationBusy) return;
  if (!hasUserMessage(activeChat())) {
    messageInput.focus();
    return;
  }
  activeDestinationId = null;
  let chat = createChat();
  if (accountState.authenticated) {
    const response = await accountFetch("/account/chats", {
      method: "POST",
      headers: accountHeaders({ csrf: true }),
      body: JSON.stringify({ title: chat.title, payload: chat }),
    });
    if (!response.ok) {
      window.alert("Не удалось создать синхронизируемый чат. Попробуйте ещё раз.");
      return;
    }
    chat = serverRecordToChat(await response.json());
  }
  store.chats.push(chat);
  store.activeChatId = chat.id;
  persist();
  renderAll();
  setMobileView("chat");
  messageInput.focus();
}

async function deleteChat(chatId) {
  if (!accountReady || busy || destinationBusy || !window.confirm("Удалить этот чат и его рекомендации?")) return;
  if (accountState.authenticated) {
    const response = await accountFetch(`/account/chats/${encodeURIComponent(chatId)}`, {
      method: "DELETE",
      headers: accountHeaders({ json: false, csrf: true }),
    });
    if (!response.ok) {
      window.alert("Не удалось удалить чат.");
      return;
    }
  }
  store.chats = store.chats.filter((chat) => chat.id !== chatId);
  if (!store.chats.length) {
    await openNewChat();
    return;
  }
  if (store.activeChatId === chatId) store.activeChatId = store.chats[0].id;
  persist();
  renderAll();
}

function renderAccountPanel() {
  const loggedIn = accountState.authenticated;
  $("#login-button").classList.toggle("hidden", loggedIn);
  $("#account-profile").classList.toggle("hidden", !loggedIn);
  $("#auth-unavailable").classList.toggle("hidden", loggedIn || accountState.authEnabled);
  $("#account-name").textContent = accountState.account?.display_name
    || accountState.account?.email
    || "Аккаунт";
  $("#mobile-login-button").textContent = loggedIn ? "Аккаунт" : "Войти";
  $("#mobile-login-button").disabled = false;
  $("#composer-note").textContent = loggedIn
    ? `${syncState === "error" ? "Локальная копия сохранена · синхронизация не удалась" : "Синхронизируем с аккаунтом"} · Enter — отправить, Shift+Enter — новая строка`
    : "Сохраняем в этом браузере · Enter — отправить, Shift+Enter — новая строка";
  if (loggedIn && syncState === "idle") setSyncState("saved");
}

function beginLogin() {
  if (accountState.authenticated) return;
  window.location.assign("/login?return_to=/");
}

async function logoutAccount() {
  if (!accountState.authenticated) return;
  const response = await accountFetch("/auth/logout", {
    method: "POST",
    headers: accountHeaders({ json: false, csrf: true }),
  });
  if (!response.ok) {
    window.alert("Не удалось завершить сессию.");
    return;
  }
  accountState = { authEnabled: true, authenticated: false, account: null, csrfToken: null };
  syncState = "idle";
  store = loadGuestStore();
  persist();
  renderAccountPanel();
  renderAll();
}

async function deleteAccountData() {
  if (!accountState.authenticated) return;
  const warning = "Удалить аккаунт, все переписки и сохранённые рекомендации без возможности восстановления?";
  if (!window.confirm(warning)) return;
  const response = await accountFetch("/account", {
    method: "DELETE",
    headers: accountHeaders({ csrf: true }),
    body: JSON.stringify({ confirmation: "DELETE" }),
  });
  if (!response.ok) {
    window.alert("Не удалось удалить данные аккаунта.");
    return;
  }
  localStorage.removeItem(`${ACCOUNT_CACHE_PREFIX}${accountState.account.id}`);
  accountState = { authEnabled: true, authenticated: false, account: null, csrfToken: null };
  syncState = "idle";
  store = loadGuestStore();
  renderAccountPanel();
  renderAll();
}

function meaningfulGuestChats(guestStore, accountId) {
  const markerKey = `travel-account-imported-v1:${accountId}`;
  let imported = [];
  try {
    imported = JSON.parse(localStorage.getItem(markerKey)) || [];
  } catch {
    imported = [];
  }
  return guestStore.chats.filter((chat) => (
    !imported.includes(chat.id)
    && (chat.messages || []).some((message) => message.role === "user")
  ));
}

async function importGuestChats(chats) {
  const importedIds = [];
  for (const chat of chats) {
    const response = await accountFetch("/account/chats/import", {
      method: "POST",
      headers: accountHeaders({ csrf: true }),
      body: JSON.stringify({
        client_import_id: `local-v1:${chat.id}`,
        title: chat.title,
        payload: chat,
      }),
    });
    if (!response.ok) throw new Error(`Не удалось перенести «${chat.title}»`);
    importedIds.push(chat.id);
  }
  const markerKey = `travel-account-imported-v1:${accountState.account.id}`;
  const previous = JSON.parse(localStorage.getItem(markerKey) || "[]");
  localStorage.setItem(markerKey, JSON.stringify([...new Set([...previous, ...importedIds])]));
}

async function loadAccountChats() {
  const response = await fetch("/account/chats");
  if (!response.ok) throw new Error("Не удалось загрузить историю аккаунта");
  let chats = (await response.json()).map(serverRecordToChat);
  if (!chats.length) {
    const fresh = createChat();
    const created = await accountFetch("/account/chats", {
      method: "POST",
      headers: accountHeaders({ csrf: true }),
      body: JSON.stringify({ title: fresh.title, payload: fresh }),
    });
    if (!created.ok) throw new Error("Не удалось создать первый чат аккаунта");
    chats = [serverRecordToChat(await created.json())];
  }
  store = { activeChatId: chats[0].id, chats };
  persist();
}

async function initializeAccount() {
  try {
    const response = await fetch("/account/me");
    if (!response.ok) throw new Error("Не удалось проверить сессию");
    const status = await response.json();
    accountState = {
      authEnabled: status.auth_enabled,
      authenticated: status.authenticated,
      account: status.account,
      csrfToken: status.csrf_token,
    };
    renderAccountPanel();
    if (!accountState.authenticated) return true;
    const guestStore = loadGuestStore();
    const candidates = meaningfulGuestChats(guestStore, accountState.account.id);
    if (candidates.length) {
      const label = candidates.length === 1 ? "одну локальную поездку" : `${candidates.length} локальных поездки`;
      if (window.confirm(`Сохранить ${label} в аккаунте? Локальные копии останутся в браузере.`)) {
        await importGuestChats(candidates);
      }
    }
    await loadAccountChats();
    renderAll();
    return true;
  } catch (error) {
    console.warn(error.message);
    renderAccountPanel();
    return false;
  }
}

async function sendCurrentMessage(text) {
  if (!accountReady || busy || !text.trim()) return;
  const chat = activeChat();
  const query = text.trim();
  addMessage(chat, { role: "user", text: query });
  messageInput.value = "";
  resizeComposer();
  renderAll();
  await requestRecommendation(query);
}

function resizeComposer() {
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 120)}px`;
}

function setMobileView(view) {
  document.body.dataset.mobileView = view;
  document.querySelectorAll(".mobile-tab").forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
}

function refineResults() {
  setMobileView("chat");
  messageInput.focus();
}

destinationComposer.addEventListener("submit", (event) => {
  event.preventDefault();
  sendDestinationMessage(destinationInput.value);
});
destinationInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    destinationComposer.requestSubmit();
  }
});
$("#destination-back").addEventListener("click", closeDestinationChat);
$("#refine-results").addEventListener("click", refineResults);

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  sendCurrentMessage(messageInput.value);
});
messageInput.addEventListener("input", resizeComposer);
messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    composer.requestSubmit();
  }
});
document.querySelectorAll("[data-starter]").forEach((button) => {
  button.addEventListener("click", () => sendCurrentMessage(button.dataset.starter));
});
$("#new-chat").addEventListener("click", openNewChat);
$("#mobile-new-chat").addEventListener("click", openNewChat);
$("#sidebar-toggle").addEventListener("click", () => {
  setSidebarCollapsed(document.body.dataset.sidebarCollapsed !== "true");
});
$("#login-button").addEventListener("click", beginLogin);
$("#mobile-login-button").addEventListener("click", () => {
  window.location.assign("/login?return_to=/");
});
$("#logout-button").addEventListener("click", logoutAccount);
$("#delete-account-button").addEventListener("click", deleteAccountData);
document.querySelectorAll(".mobile-tab").forEach((button) => {
  button.addEventListener("click", () => setMobileView(button.dataset.view));
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") flushPendingSyncs();
});

setSidebarCollapsed(localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true");
persist();
setMobileView("chat");
renderAll();
renderAccountPanel();
initializeAccount().then((ready) => {
  accountReady = ready;
  if (!ready) $("#chat-status").textContent = "Не удалось загрузить состояние сервиса";
});
