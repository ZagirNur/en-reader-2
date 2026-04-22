import { api, getConfig, setConfig, DEFAULT_BASE_URL, ApiError } from "../lib/api.js";

const $ = (id) => document.getElementById(id);
const baseUrlInput = $("baseUrl");
const emailInput = $("email");
const passwordInput = $("password");
const loginBtn = $("loginBtn");
const logoutBtn = $("logoutBtn");
const statusEl = $("status");
const whoRow = $("who");
const whoEmail = $("whoEmail");

function showStatus(text, kind = "info") {
  statusEl.className = `status ${kind}`;
  statusEl.textContent = text;
  statusEl.hidden = false;
}

function hideStatus() {
  statusEl.hidden = true;
}

async function refresh() {
  const cfg = await getConfig();
  baseUrlInput.value = cfg.baseUrl || DEFAULT_BASE_URL;
  if (cfg.token) {
    try {
      const me = await api.me();
      whoEmail.textContent = me.email || "(unknown)";
      whoRow.hidden = false;
      logoutBtn.hidden = false;
      loginBtn.textContent = "Перелогиниться";
      hideStatus();
    } catch (e) {
      whoRow.hidden = true;
      logoutBtn.hidden = true;
      loginBtn.textContent = "Войти";
      showStatus(`Токен недействителен: ${e.message}`, "err");
    }
  } else {
    whoRow.hidden = true;
    logoutBtn.hidden = true;
    loginBtn.textContent = "Войти";
  }
}

loginBtn.addEventListener("click", async () => {
  const baseUrl = baseUrlInput.value.trim() || DEFAULT_BASE_URL;
  const email = emailInput.value.trim();
  const password = passwordInput.value;
  if (!email || !password) {
    showStatus("Укажи email и пароль", "err");
    return;
  }
  loginBtn.disabled = true;
  showStatus("Получаю токен…", "info");
  try {
    await setConfig({ baseUrl });
    const data = await api.login({ email, password, baseUrl });
    if (!data.access_token) {
      throw new ApiError("сервер не вернул access_token", { status: 0 });
    }
    await setConfig({ token: data.access_token });
    passwordInput.value = "";
    showStatus("Готово", "ok");
    await refresh();
  } catch (e) {
    showStatus(e.message || String(e), "err");
  } finally {
    loginBtn.disabled = false;
  }
});

logoutBtn.addEventListener("click", async () => {
  await setConfig({ token: null });
  await refresh();
  showStatus("Вышел", "info");
});

refresh();
