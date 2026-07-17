const STORAGE_KEY = "travel-chat-state-v1";
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
  max_flight_duration_hours: "длительность перелёта",
  visa_willingness: "виза",
  sea_required: "море",
  trip_style: "формат отдыха",
  heat_tolerance: "отношение к жаре",
  preferred_max_temperature_c: "максимальная температура",
  baggage_required: "багаж",
  preferences: "предпочтения",
  avoid: "что исключить",
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

function defaultGreeting() {
  return {
    id: id(),
    role: "assistant",
    text: "Привет! Я помогу выбрать не просто страну, а конкретные места: где остановиться, что посмотреть и какие варианты сравнить. Расскажите о поездке — можно писать как другу.",
    createdAt: now(),
    questions: [],
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
    pendingQuestionMessageId: null,
    destinationThreads: {},
  };
}

function loadStore() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (saved?.chats?.length) {
      saved.chats.forEach((chat) => {
        chat.destinationThreads = chat.destinationThreads || {};
      });
      const activeExists = saved.chats.some((chat) => chat.id === saved.activeChatId);
      saved.activeChatId = activeExists ? saved.activeChatId : saved.chats[0].id;
      return saved;
    }
  } catch (error) {
    console.warn("Не удалось восстановить локальную историю", error);
  }
  const chat = createChat();
  return { activeChatId: chat.id, chats: [chat] };
}

let store = loadStore();

function persist() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
}

function activeChat() {
  return store.chats.find((chat) => chat.id === store.activeChatId);
}

function touch(chat) {
  chat.updatedAt = now();
  persist();
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
  chat.messages.push({ id: id(), createdAt: now(), questions: [], ...message });
  if (message.role === "user" && chat.title === "Новая поездка") chat.title = titleFromQuery(message.text);
  touch(chat);
}

function renderChatList() {
  const chats = [...store.chats].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  $("#chat-list").innerHTML = chats.map((chat) => `
    <button class="chat-item ${chat.id === store.activeChatId ? "active" : ""}" type="button" data-chat-id="${escapeHtml(chat.id)}">
      <strong>${escapeHtml(chat.title)}</strong>
      <small>${relativeDate(chat.updatedAt)} · ${Math.max(0, chat.messages.length - 1)} сообщ.</small>
      <span class="chat-icon" aria-hidden="true">›</span>
    </button>
  `).join("");
  document.querySelectorAll("[data-chat-id]").forEach((button) => {
    button.addEventListener("click", () => switchChat(button.dataset.chatId));
  });
}

function controlFor(question, messageId) {
  const field = question.field;
  const fieldName = `${messageId}-${field}`;
  if (field === "adults") {
    return `<select class="answer-input" data-field="${field}" required><option value="">Выберите</option><option value="1">1 взрослый</option><option value="2">2 взрослых</option><option value="3">3 взрослых</option><option value="4">4 взрослых</option></select>`;
  }
  if (field === "budget_total_rub") {
    return `<input class="answer-input" data-field="${field}" type="number" min="10000" step="5000" placeholder="Например, 150000" required />`;
  }
  if (field === "month") {
    return `<select class="answer-input" data-field="month" required><option value="">Выберите месяц</option>${MONTHS.map((month, index) => `<option value="${index + 1}">${month}</option>`).join("")}</select>`;
  }
  if (field === "destination_scope") {
    const values = [["domestic", "По России"], ["international", "За границу"], ["any", "Оба варианта"]];
    return `<div class="answer-options">${values.map(([value, label]) => `<label class="answer-option"><input type="radio" name="${fieldName}" data-field="${field}" value="${value}" required /><span>${label}</span></label>`).join("")}</div>`;
  }
  if (field === "origin_city" && question.options?.length) {
    return `<input class="answer-input" data-field="${field}" type="text" list="${fieldName}-options" placeholder="Например, Москва" required /><datalist id="${fieldName}-options">${question.options.slice(0, 2).map((value) => `<option value="${escapeHtml(value)}"></option>`).join("")}</datalist>`;
  }
  return `<input class="answer-input" data-field="${field}" type="text" placeholder="Ваш ответ" required />`;
}

function questionMarkup(question, messageId) {
  if (question.resolved) {
    return `<div class="question-item resolved"><div class="question-label">${escapeHtml(question.question || question.field)}</div><div class="resolved-answer">✓ ${escapeHtml(question.answerDisplay || "Ответ сохранён")}</div></div>`;
  }
  return `<div class="question-item"><div class="question-label">${escapeHtml(question.question || question.field)}</div><p class="question-reason">${escapeHtml(question.reason || "")}</p>${controlFor(question, messageId)}</div>`;
}

function questionsMarkup(message) {
  if (!message.questions?.length) return "";
  const hasOpen = message.questions.some((question) => !question.resolved);
  return `<form class="question-block" data-question-message="${escapeHtml(message.id)}"><div class="question-items">${message.questions.map((question) => questionMarkup(question, message.id)).join("")}</div>${hasOpen ? '<button class="question-submit" type="submit">Сохранить ответы <span>→</span></button>' : ""}</form>`;
}

function changesMarkup(fields = []) {
  if (!fields.length) return "";
  return `<div class="change-summary">${fields.map((field) => `<span>Обновлено: ${escapeHtml(FIELD_LABELS[field] || field)}</span>`).join("")}</div>`;
}

function renderMessages() {
  const chat = activeChat();
  messageList.innerHTML = chat.messages.map((message) => {
    if (message.role === "user") {
      return `<article class="message user"><div><div class="bubble"><p>${escapeHtml(message.text).replaceAll("\n", "<br>")}</p></div><div class="message-meta">${shortTime(message.createdAt)}</div></div></article>`;
    }
    return `<article class="message assistant"><span class="avatar assistant-avatar" aria-hidden="true">✦</span><div class="message-content"><div class="message-name">Помощник</div><div class="bubble"><p>${escapeHtml(message.text).replaceAll("\n", "<br>")}</p>${changesMarkup(message.changedFields)}${questionsMarkup(message)}</div><div class="message-meta">${shortTime(message.createdAt)}</div></div></article>`;
  }).join("");

  document.querySelectorAll("[data-question-message]").forEach((form) => {
    if (form.querySelector(".question-submit")) form.addEventListener("submit", submitQuestionAnswers);
  });
  $("#starter-zone").classList.toggle("hidden", chat.messages.some((message) => message.role === "user"));
  requestAnimationFrame(() => { messageList.scrollTop = messageList.scrollHeight; });
}

function readableAnswer(field, value) {
  if (field === "month") return MONTHS[Number(value) - 1] || value;
  if (field === "budget_total_rub") return `${formatMoney(Number(value))}`;
  if (field === "adults") return `${value} взросл.`;
  if (field === "destination_scope") return { domestic: "по России", international: "за границу", any: "Россия и зарубежье" }[value] || value;
  return String(value);
}

function collectAnswers(form) {
  const answers = {};
  form.querySelectorAll("[data-field]").forEach((input) => {
    if (input.type === "radio" && !input.checked) return;
    if (!input.value) return;
    const numeric = ["adults", "budget_total_rub", "month"].includes(input.dataset.field);
    answers[input.dataset.field] = numeric ? Number(input.value) : input.value;
  });
  return answers;
}

function answerSummary(answers) {
  return Object.entries(answers).map(([field, value]) => `${FIELD_LABELS[field] || field}: ${readableAnswer(field, value)}`).join("; ");
}

async function submitQuestionAnswers(event) {
  event.preventDefault();
  if (busy) return;
  const form = event.currentTarget;
  const answers = collectAnswers(form);
  if (!Object.keys(answers).length) return;
  const summary = answerSummary(answers);
  const chat = activeChat();
  addMessage(chat, { role: "user", text: summary });
  renderAll();
  await requestRecommendation(summary, answers, form.dataset.questionMessage);
}

function resolveQuestions(chat, messageId, answerText, answers) {
  const message = chat.messages.find((item) => item.id === messageId);
  if (!message) return;
  message.questions = message.questions.map((question) => ({
    ...question,
    resolved: true,
    answerDisplay: answers?.[question.field] !== undefined
      ? readableAnswer(question.field, answers[question.field])
      : `ответ в сообщении: «${answerText}»`,
  }));
  if (chat.pendingQuestionMessageId === messageId) chat.pendingQuestionMessageId = null;
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
}

async function requestRecommendation(query, answers = null, questionMessageId = null) {
  const chat = activeChat();
  const chatId = chat.id;
  setBusy(true);
  try {
    const response = await fetch("/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, session_id: chat.id, answers }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Не удалось получить рекомендации");

    const targetChat = store.chats.find((item) => item.id === chatId);
    if (!targetChat) return;
    if (questionMessageId) resolveQuestions(targetChat, questionMessageId, query, answers);
    else if (targetChat.pendingQuestionMessageId) {
      resolveQuestions(targetChat, targetChat.pendingQuestionMessageId, query, null);
    }

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
      questions: (payload.questions || []).map((question) => ({ ...question, resolved: false })),
    };
    addMessage(targetChat, assistantMessage);
    if (assistantMessage.questions.length) {
      targetChat.pendingQuestionMessageId = targetChat.messages.at(-1).id;
    }
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
  ].join("");
}

function costRange(candidate) {
  if (candidate.estimated_total_cost_rub_min == null) return "Нет оценки";
  return `${formatMoney(candidate.estimated_total_cost_rub_min)} – ${formatMoney(candidate.estimated_total_cost_rub_max)}`;
}

function providerActions(candidate, snapshot, index) {
  const flightLink = (candidate.external_links || []).find((link) => link.category === "flight");
  const stayLink = (candidate.external_links || []).find((link) => link.category === "stay");
  const requestId = snapshot?.request_id || "unknown-request";
  const shared = `data-destination-id="${escapeHtml(candidate.destination_id)}" data-rank="${index + 1}" data-request-id="${escapeHtml(requestId)}"`;
  return `<div class="card-actions">
    <a class="travel-link aviasales-link" href="${safeUrl(flightLink?.url || "https://www.aviasales.ru/")}" target="_blank" rel="noreferrer" ${shared} data-provider="aviasales" data-link-kind="flight"><span aria-hidden="true">✈</span> ${escapeHtml(flightLink?.title || "Найти билеты")} <small>Aviasales</small></a>
    <a class="travel-link yandex-link" href="${safeUrl(stayLink?.url || "https://travel.yandex.ru/")}" target="_blank" rel="noreferrer" ${shared} data-provider="yandex_travel" data-link-kind="stay"><span aria-hidden="true">⌂</span> Найти жильё <small>Яндекс Путешествия</small></a>
  </div>`;
}

function destinationDiscussionAction(candidate, chat) {
  const thread = chat.destinationThreads?.[candidate.destination_id];
  const messageCount = (thread?.messages || []).filter((message) => message.role === "user").length;
  const countLabel = messageCount ? `<span>${messageCount} сообщ.</span>` : "<span>Новый субчат</span>";
  return `<button class="destination-discuss" type="button" data-discuss-destination="${escapeHtml(candidate.destination_id)}"><span class="destination-discuss-icon" aria-hidden="true">✦</span><strong>Обсудить ${escapeHtml(candidate.city_or_region)}</strong>${countLabel}<i aria-hidden="true">→</i></button>`;
}

function destinationCard(item, index, chat) {
  const candidate = item.candidate;
  const image = candidate.image;
  const imageUrl = safeUrl(image?.url);
  const highlights = (candidate.highlights || []).map((place) => `
    <a class="place" href="${safeUrl(place.url)}" target="_blank" rel="noreferrer">
      <strong>↗ ${escapeHtml(place.name)}</strong><span>${escapeHtml(place.description)}</span>
    </a>`).join("");
  const stayAreas = (candidate.stay_areas || []).map((area) => `<span class="stay-area">${escapeHtml(area)}</span>`).join("");
  const sources = (candidate.sources || []).map((source) => `<a href="${safeUrl(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.title)}</a>`).join("");
  const flight = candidate.flight_duration_hours ? `${candidate.flight_duration_hours} ч · ${candidate.transfers_count || 0} перес.` : "Уточнить";
  const weather = candidate.expected_temperature_c != null ? `${candidate.expected_temperature_c}° · море ${candidate.expected_sea_temperature_c ?? "—"}°` : "Уточнить";
  return `<article class="destination-card">
    <div class="card-image">
      ${image ? `<img src="${imageUrl}" alt="${escapeHtml(image.alt)}" loading="lazy" />` : ""}
      <div class="image-shade"></div><span class="rank-badge">#${index + 1} вариант</span><span class="demo-tag">DEMO</span>
      <div class="image-caption"><div><h3>${escapeHtml(candidate.city_or_region)}</h3><p>${escapeHtml(candidate.country)} · ${escapeHtml(candidate.nearest_airport || "аэропорт уточняется")}</p></div><span class="score-pill">${Math.round(item.total_score)} / 100</span></div>
      ${image ? `<a class="image-credit" href="${safeUrl(image.source_url)}" target="_blank" rel="noreferrer">Фото: ${escapeHtml(image.credit)}</a>` : ""}
    </div>
    <div class="card-body">
      <div class="quick-metrics">
        <div class="quick-metric"><span>Ориентир бюджета</span><strong>${escapeHtml(costRange(candidate))}</strong></div>
        <div class="quick-metric"><span>Перелёт</span><strong>${escapeHtml(flight)}</strong></div>
        <div class="quick-metric"><span>Погода</span><strong>${escapeHtml(weather)}</strong></div>
      </div>
      ${highlights ? `<div class="card-section"><h4>Конкретные места</h4><div class="place-list">${highlights}</div></div>` : ""}
      ${stayAreas ? `<div class="card-section"><h4>Районы для проживания</h4><div class="stay-areas">${stayAreas}</div></div>` : ""}
      ${destinationDiscussionAction(candidate, chat)}
      ${providerActions(candidate, chat.snapshot, index)}
      <p class="external-note">Внешний поиск · цены и наличие не подтверждены</p>
      <details class="card-details"><summary>Почему подходит, риски и источники</summary><p class="detail-copy">${escapeHtml(item.explanation)} ${item.risks?.length ? `Риски: ${escapeHtml(item.risks.join("; "))}.` : ""} Въезд: ${escapeHtml(candidate.entry_requirements || "нужно проверить")}.</p><div class="source-links">${sources}</div></details>
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
  $("#feed-notices").innerHTML = notices.map((notice) => `<div class="notice">${escapeHtml(notice)}</div>`).join("");
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
  if (busy || destinationBusy || !text?.trim() || !activeDestinationId) return;
  const chat = activeChat();
  const chatId = chat.id;
  const destinationId = activeDestinationId;
  const query = text.trim();
  addDestinationMessage(chat, destinationId, { role: "user", text: query });
  destinationInput.value = "";
  destinationBusy = true;
  renderDestinationChat();
  try {
    const response = await fetch("/destination-chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: chatId, destination_id: destinationId, query }),
    });
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
  if (chat.pendingQuestionMessageId) return "Жду ваши уточнения · память включена";
  if (count) return `${pluralOptions(count)} · можно уточнять дальше`;
  return "Расскажите, куда хочется · память включена";
}

function renderAll() {
  const chat = activeChat();
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

function openNewChat() {
  if (busy || destinationBusy) return;
  activeDestinationId = null;
  const chat = createChat();
  store.chats.push(chat);
  store.activeChatId = chat.id;
  persist();
  renderAll();
  setMobileView("chat");
  messageInput.focus();
}

async function sendCurrentMessage(text) {
  if (busy || !text.trim()) return;
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
  document.querySelectorAll(".mobile-tab").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
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
document.querySelectorAll(".mobile-tab").forEach((button) => {
  button.addEventListener("click", () => setMobileView(button.dataset.view));
});

persist();
setMobileView("chat");
renderAll();
