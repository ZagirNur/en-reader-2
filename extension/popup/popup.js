const $ = (id) => document.getElementById(id);
const whoEl = $("who");
const activateBtn = $("activate");
const optionsBtn = $("options");
const statusEl = $("status");

function showStatus(text, kind = "info") {
  statusEl.className = `status ${kind}`;
  statusEl.textContent = text;
  statusEl.hidden = false;
}

function hideStatus() {
  statusEl.hidden = true;
}

async function refresh() {
  const cfg = await chrome.runtime.sendMessage({ type: "getConfig" });
  if (!cfg?.hasToken) {
    whoEl.textContent = "Не авторизован";
    activateBtn.disabled = true;
    return;
  }
  try {
    const res = await chrome.runtime.sendMessage({ type: "api", name: "me", args: [] });
    if (res?.ok) {
      whoEl.textContent = res.result?.email ? `Вошёл как ${res.result.email}` : "Авторизован";
      activateBtn.disabled = false;
    } else {
      whoEl.textContent = `Токен недействителен`;
      activateBtn.disabled = true;
    }
  } catch (e) {
    whoEl.textContent = String(e);
    activateBtn.disabled = true;
  }
}

activateBtn.addEventListener("click", async () => {
  activateBtn.disabled = true;
  hideStatus();
  showStatus("Активирую…", "info");
  try {
    const res = await chrome.runtime.sendMessage({ type: "activate" });
    if (res?.ok) {
      showStatus("Готово — кликай на слова", "ok");
      setTimeout(() => window.close(), 600);
    } else {
      showStatus(res?.error || "ошибка", "err");
      activateBtn.disabled = false;
    }
  } catch (e) {
    showStatus(String(e), "err");
    activateBtn.disabled = false;
  }
});

optionsBtn.addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
  window.close();
});

refresh();
