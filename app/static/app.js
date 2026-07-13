const state = { query: "", sessionId: null, requestId: null, recommendations: [] };
const $ = (selector) => document.querySelector(selector);
const queryForm = $("#query-form"), queryInput = $("#query"), submitButton = $("#submit-button");
const progress = $("#progress"), clarification = $("#clarification"), results = $("#results");
const stages = [["Понимаем ваш запрос", "Собираем важные ограничения для поездки."], ["Ищем подходящие направления", "Сравниваем варианты по вашим условиям."], ["Собираем shortlist", "Показываем причины, риски и допущения."]];

function setProgress(index = 0) { const [title, copy] = stages[index]; $("#progress-title").textContent = title; $("#progress-copy").textContent = copy; }
function setLoading(active) { progress.classList.toggle("hidden", !active); submitButton.disabled = active; if (active) { setProgress(0); setTimeout(() => setProgress(1), 360); setTimeout(() => setProgress(2), 760); } }
function formatMoney(value) { return new Intl.NumberFormat("ru-RU").format(value) + " ₽"; }
function removeHidden() { clarification.classList.add("hidden"); results.classList.add("hidden"); }

async function requestRecommendation(answers = null) {
  setLoading(true); removeHidden();
  try {
    const response = await fetch("/recommend", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: state.query, session_id: state.sessionId, answers }) });
    if (!response.ok) throw new Error("Не удалось получить рекомендации. Попробуйте ещё раз.");
    const payload = await response.json(); state.sessionId = payload.session_id; state.requestId = payload.request_id;
    if (payload.status === "needs_clarification") renderClarification(payload); else renderResults(payload);
  } catch (error) { showError(error.message); } finally { setLoading(false); }
}

function controlFor(question) {
  const field = question.field;
  if (["adults", "budget_total_rub"].includes(field)) return `<input class="answer-input" data-field="${field}" type="number" min="1" placeholder="Введите число" required />`;
  if (field === "month") return `<select class="answer-input" data-field="month" required><option value="">Выберите месяц</option>${["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"].map((month, index) => `<option value="${index + 1}">${month}</option>`).join("")}</select>`;
  if (field === "destination_scope") { const values = [["domestic", "По России"], ["international", "За границу"], ["any", "Оба варианта"]]; return `<div class="answer-options">${values.map(([value,label]) => `<label class="answer-option"><input type="radio" name="${field}" data-field="${field}" value="${value}" required /><span>${label}</span></label>`).join("")}</div>`; }
  return `<input class="answer-input" data-field="${field}" type="text" required placeholder="Ваш ответ" />`;
}
function renderClarification(payload) {
  const fragment = $("#question-template").content.cloneNode(true); const form = fragment.querySelector("form"), list = fragment.querySelector(".question-list");
  payload.questions.forEach((question) => { const wrapper = document.createElement("div"); wrapper.innerHTML = `<div class="question-label">${question.question}</div><p class="question-reason">${question.reason}</p>${controlFor(question)}`; list.append(wrapper); });
  form.addEventListener("submit", (event) => { event.preventDefault(); const answers = {}; form.querySelectorAll("[data-field]").forEach((input) => { if ((input.type !== "radio" || input.checked) && input.value) answers[input.dataset.field] = ["adults", "budget_total_rub", "month"].includes(input.dataset.field) ? Number(input.value) : input.value; }); requestRecommendation(answers); });
  clarification.replaceChildren(fragment); clarification.classList.remove("hidden"); clarification.scrollIntoView({ behavior: "smooth", block: "start" });
}
function metric(label, value) { return `<div class="metric"><b>${label}</b><span>${value || "—"}</span></div>`; }
function card(item) {
  const c = item.candidate, cost = c.estimated_total_cost_rub_min ? `${formatMoney(c.estimated_total_cost_rub_min)}–${formatMoney(c.estimated_total_cost_rub_max)}` : "Нет оценки";
  const sources = c.sources.map((source) => `<li><a href="${source.url}" target="_blank" rel="noreferrer">${source.title}</a> · ${source.provider}</li>`).join("");
  const pros = item.pros.map((value) => `<li>${value}</li>`).join("") || "<li>Соответствует фильтрам</li>", cons = item.risks.map((value) => `<li>${value}</li>`).join("");
  return `<article class="recommendation-card"><div class="score" style="--score:${item.total_score}"><span>${Math.round(item.total_score)}</span></div><div><div class="card-top"><div><div class="destination">${c.city_or_region}</div><div class="country">${c.country} · аэропорт ${c.nearest_airport || "—"}</div></div><span class="confidence">demo · ${Math.round((c.data_confidence || 0) * 100)}% confidence</span></div><div class="metrics">${metric("Примерный бюджет", cost)}${metric("Перелёт", c.flight_duration_hours ? `${c.flight_duration_hours} ч · ${c.transfers_count || 0} пересадок` : null)}${metric("Погода", c.expected_temperature_c ? `${c.expected_temperature_c}°C · море ${c.expected_sea_temperature_c || "—"}°C` : null)}${metric("Въезд", c.visa_complexity === "none" ? "Без визы*" : c.visa_complexity || "Проверить")}</div><div class="card-summary"><div><h3>Почему подходит</h3><ul class="compact-list">${pros}</ul></div><div><h3>Риски</h3><ul class="compact-list">${cons}</ul></div></div><details class="details"><summary>Источники и детали score</summary><ul class="source-list">${sources}</ul><p class="source-list">${item.explanation}</p></details></div></article>`;
}
function renderResults(payload) { state.recommendations = payload.recommendations || []; $("#recommendation-list").innerHTML = state.recommendations.map(card).join("") || "<p>Подходящих demo-вариантов не нашлось.</p>"; $("#assumptions").innerHTML = (payload.assumptions || []).map((note) => `<div class="note">Допущение: ${note}</div>`).join(""); $("#warnings").innerHTML = (payload.warnings || []).map((note) => `<div class="note">${note}</div>`).join(""); results.classList.remove("hidden"); results.scrollIntoView({ behavior: "smooth", block: "start" }); }
function showError(message) { $("#warnings").innerHTML = `<div class="note">${message}</div>`; results.classList.remove("hidden"); }
queryForm.addEventListener("submit", (event) => { event.preventDefault(); state.query = queryInput.value.trim(); state.sessionId = null; if (state.query) requestRecommendation(); });
document.querySelectorAll(".chip").forEach((chip) => chip.addEventListener("click", () => { queryInput.value = chip.dataset.query; queryInput.focus(); }));
$("#restart").addEventListener("click", () => { state.sessionId = null; queryInput.value = ""; results.classList.add("hidden"); queryInput.focus(); window.scrollTo({ top: 0, behavior: "smooth" }); });
document.querySelectorAll(".feedback-button").forEach((button) => button.addEventListener("click", async () => { if (!state.sessionId || !state.requestId) return; await fetch("/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: state.sessionId, request_id: state.requestId, value: button.dataset.value, destination_id: state.recommendations[0]?.candidate.destination_id || null }) }); document.querySelectorAll(".feedback-button").forEach((item) => { item.disabled = true; item.classList.add("sent"); }); }));
