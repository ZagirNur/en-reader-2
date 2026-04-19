# Задача M13.4 — TLS через Let's Encrypt

**Размер.** S (~1 день)
**Зависимости.** M13.1.
**Что строится поверх.** Prod-ready HTTPS. Если нет домена — задача откладывается.

---

## О проекте (контекст)

**en-reader** — веб-читалка. Прод должен ходить по HTTPS. Варианты:
1. **nginx reverse proxy + certbot** — классика; но nginx мы не ставили.
2. **uvicorn с SSL + acme.sh** — без nginx.
3. **Caddy** — авто-TLS из коробки.

Выбираем **Caddy** — проще всего. Он получает сертификаты Let's Encrypt автоматически, раз-в-час перепроверяет, сам редиректит 80→443.

Альтернативно — uvicorn с SSL и acme.sh. Caddy проще.

---

## Что нужно сделать

Установить Caddy, настроить reverse proxy на uvicorn :8080 (переносим app с :80 на :8080), Caddy на :80/:443.

---

## Что входит

### 1. Перенос uvicorn с :80 на :8080

В `deploy/en-reader.service` поменять port на 8080, убрать CAP_NET_BIND_SERVICE (не нужно для high port).

```ini
ExecStart=/opt/en-reader/.venv/bin/uvicorn en_reader.app:app --host 127.0.0.1 --port 8080 --workers 1
```

`--host 127.0.0.1` — Caddy будет обращаться локально, наружу uvicorn не торчит.

### 2. Установить Caddy

```bash
apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update
apt install -y caddy
```

### 3. `/etc/caddy/Caddyfile`

```
DOMAIN.com {
  reverse_proxy 127.0.0.1:8080
  encode gzip
  header {
    Strict-Transport-Security "max-age=31536000"
    X-Content-Type-Options nosniff
    Referrer-Policy no-referrer-when-downgrade
  }
}
```

Caddy сам получит сертификат при первом запросе.

### 4. Firewall

```bash
ufw allow 80/tcp
ufw allow 443/tcp
ufw reload
```

Порт 8080 в ufw **не открываем** — uvicorn слушает только на localhost.

### 5. Запуск

```bash
systemctl enable --now caddy
systemctl restart en-reader
```

### 6. Обновление cookie

В `.env` поставить `ENV=prod` — тогда cookie получит `Secure`.

### 7. Обновить `deploy/README.md`

Секция про TLS:
```markdown
## TLS

1. Привяжи домен к IP VPS (A-запись).
2. Правь `/etc/caddy/Caddyfile`, замени `DOMAIN.com` на реальный.
3. `systemctl restart caddy` — Caddy сам получит Let's Encrypt сертификат.
4. Проверь `https://<домен>/` — зелёный замок.
```

### 8. Ручная проверка

- `https://<домен>/` → зелёный замок, HTML.
- `http://<домен>/` → 301 на https.
- `curl -v https://<домен>/auth/me` → правильные security headers.
- Сессия работает (signup → cookie с Secure=true → login по HTTPS).

---

## Технические детали и ловушки

- **Caddy и домен**. Caddy получает сертификат через HTTP-01 challenge (по :80) или TLS-ALPN-01 (по :443). Нужно, чтобы :80 и :443 были открыты и домен резолвился на этот IP.
- **`--host 127.0.0.1`** на uvicorn — важно для безопасности. Иначе uvicorn доступен напрямую в обход Caddy.
- **HSTS**. Раз включили — минимум год. Заранее уверься, что HTTPS стабильно работает.
- **`ENV=prod`** — cookie Secure. Без HTTPS Secure cookie не отправляется браузером, и пользователь не сможет залогиниться. Не включай до реального HTTPS.

---

## Acceptance

- [ ] `https://<домен>/` работает, зелёный замок.
- [ ] `http://<домен>/` → 301 на https.
- [ ] uvicorn доступен только с localhost (`curl http://<public-ip>:8080/` не проходит).
- [ ] Cookie при login имеет Secure-флаг.
- [ ] `securityheaders.com` — не хуже B.
- [ ] Деплой-документация обновлена.

---

## Что сдавать

- Ветка `task/M13-4-tls-lets-encrypt`, PR в main.

---

## Что НЕ делать

- Не генерируй self-signed сертификаты.
- Не ставь nginx — Caddy достаточен.
- Не форсируй HSTS в dev (localhost без HTTPS).
