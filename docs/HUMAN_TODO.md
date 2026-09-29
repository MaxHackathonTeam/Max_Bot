# Чек-лист запуска «Афиши рядом»

Инструкция рассчитана на Mac и production-сервер Ubuntu. Иди сверху вниз: для каждого шага
указано, где его выполнить (`Mac`, сайт сервиса или `VPS`), что ввести и какой результат ожидать.
Команды в блоке вводи по одной, если не сказано иначе. Текст вида `<IPv4 VPS>` — подсказка
заменить значение на своё; угловые скобки в команду не вводить.

**Домен проекта:** `vse-vezde.ru`. Куплен, но DNS пока не опубликован: по проверке от 27.09.2026
публичные резолверы не возвращали его NS/A-записи. **VPS, IP и доступы к внешним кабинетам
пока неизвестны.** Не запускай Caddy, пока DNS не указывает на IP VPS.

## Защита данных

- Никогда не вставляй в этот файл и чат `.env`, токены, пароли, приватные/публичные SSH-ключи,
  телефоны пользователей, MAX `initData`, полный объект `contact` или дамп БД.
- Секрет генерируй и вставляй прямо на VPS. Для проверки показывай только имя переменной и факт
  наличия. Если секрет попал в лог/скриншот/чат, считай его скомпрометированным и перевыпусти.
- Не запускай `docker system prune --volumes`: команда может удалить базу данных.
- Не запускай production-бот с `bot-poller`: он удалит webhook-подписку.

## Как вести чек-лист

- `[ ]` — не сделано; `[~]` — начато, допиши оставшийся шаг; `[x]` — проверено.
- После `[x]` добавляй дату, например: `Подтверждение: 2026-09-27, /health вернул status=ok`.
- Если результат отличается от ожидаемого, остановись на этом шаге. Сохрани текст ошибки,
  удали из него секреты/персональные данные и только затем попроси помощи.
- В `<...>` подставляй значения, полученные в панели провайдера. Не угадывай IP, ключи, endpoint
  или юридические реквизиты.

## Быстрый маршрут

1. Проверить покупку и настроить DNS `vse-vezde.ru`.
2. Получить VPS в РФ и выполнить его защитную настройку.
3. Развернуть production и настроить резервное копирование.
4. Подключить бота и мини-приложение в MAX.
5. Получить ключи интеграций, проверить реальные сценарии и документы.
6. Выполнить контроль качества и подготовить материалы сдачи.

## Этап 1. Домен, VPS и первый запуск

### 1. PR этапа 1 (только если PR ещё не создан)

Выполнять на Mac в Terminal из папки репозитория:

```bash
cd /Users/zhiroffjaroslav/VSProjects/Max_Bot
git status --short
git branch --show-current
```

Если текущая ветка `stage-1`, обнови авторизацию GitHub CLI:

```bash
gh auth login --web
gh auth status
```

В браузере заверши вход, выбери GitHub.com и подтверди доступ. `gh auth status` должен показать
аккаунт и активную авторизацию. Затем создай PR:

```bash
gh pr create --base main --head stage-1 --fill
```

Если организация запрещает текущий токен, открой [сравнение веток](https://github.com/MaxHackathonTeam/Max_Bot/compare/main...stage-1?expand=1),
проверь список коммитов и нажми **Create pull request**. Если PR уже существует, этот шаг отметь
выполненным; второй PR не создавай.

### 1.1. Купить домен и настроить DNS

- `[x]` Домен `vse-vezde.ru` куплен. Осталось проверить управление им в кабинете регистратора.
- `[x]` Получить VPS с публичным IPv4. Требования: провайдер в РФ, Ubuntu 24.04 LTS, минимум
  2 vCPU, 4 ГБ RAM и SSD 30–40 ГБ. При заказе сохранить IPv4 и данные для первого входа в
  менеджер паролей. В панели найти веб-консоль/VNC на случай проблем с SSH.
- `[x]` Войти в кабинет регистратора домена `vse-vezde.ru`. Открыть карточку домена и проверить
  статус регистрации, срок действия и e-mail владельца. Подтвердить данные владельца, если кабинет
  этого требует; включить автопродление и 2FA.
- `[x]` В разделе **DNS-серверы / управление DNS-зоной** посмотреть активные NS. Если это REG.RU,
  ожидаются `ns1.reg.ru` и `ns2.reg.ru`. Если NS иные, записи нужно менять в панели именно того
  DNS-провайдера, чьи NS делегированы домену.
- `[ ]` После получения IPv4 VPS открыть DNS-зону. Удалить парковочные A-записи `@` и `www`, если
  они ведут на заглушку регистратора. Добавить запись:

  | Тип | Имя | Значение |
  |---|---|---|
  | A | `@` | `<IPv4 VPS>` |
  | TXT | `@` | `v=spf1 -all` |
  | TXT | `_dmarc` | `v=DMARC1; p=reject` |

  TXT записи запрещают использование домена для почтовых рассылок. Не добавляй их, если на домене
  планируется почта; сначала согласуй SPF/DMARC с почтовым провайдером. `www` и AAAA пока не
  создавай. TTL, если доступен, поставь 300–600 секунд.
- `[x]` Проверить распространение DNS на Mac. Подставлять домен не нужно:

  ```bash
  dig +short NS vse-vezde.ru @8.8.8.8
  dig +short A vse-vezde.ru @8.8.8.8
  dig +short A vse-vezde.ru @1.1.1.1
  ```

  `NS` должен показать DNS-серверы, назначенные в панели. Обе `A` команды должны вывести ровно
  IPv4 твоего VPS. Если вывод пуст или IP другой — проверь панель/делегацию и подожди обновления;
  Caddy пока не запускай. Проверка на авторитетном сервере (если используется REG.RU):

  ```bash
  dig +short A vse-vezde.ru @ns1.reg.ru
  ```

### 1.2. Подготовить Mac и SSH-ключ

На Mac открой Terminal. Убедись, что приватный ключ не перезапишется:

```bash
ls -l ~/.ssh/id_ed25519 ~/.ssh/id_ed25519.pub
```

Если обеих файлов нет, создай ключ. Если уже есть, используй имеющийся и не запускай команду
генерации поверх него:

```bash
ssh-keygen -t ed25519 -C "vse-vezde-vps"
```

На вопросы оставь путь по умолчанию (`Enter`) и задай парольную фразу. Вывести публичный ключ для
вставки в панель VPS можно так (это файл `.pub`, не приватный ключ):

```bash
cat ~/.ssh/id_ed25519.pub
```

В панели создания VPS вставь эту строку в поле SSH key, если оно есть. Не отправляй приватный файл
`~/.ssh/id_ed25519` кому-либо.

### 1.3. Первый вход на сервер

На Mac подключись по IP, который показан в панели:

```bash
ssh root@<IPv4 VPS>
```

Если просит подтвердить fingerprint нового сервера, сравни его с показанным в панели (если доступен)
и введи `yes`. Затем, уже в shell VPS, выполни:

```bash
apt update
apt full-upgrade -y
timedatectl set-timezone UTC
hostnamectl set-hostname vse-vezde
adduser deploy
usermod -aG sudo deploy
```

На `adduser` задай новый пароль пользователя `deploy`, запиши его в менеджер паролей; имя, комнату
и телефон можно оставить пустыми (Enter), на подтверждение нажать `Y`. Пароль нужен для `sudo`,
позже SSH по паролю будет выключен.

Если публичный ключ был добавлен в панели VPS, установи его пользователю `deploy`:

```bash
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
install -m 600 -o deploy -g deploy /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
```

Если `/root/.ssh/authorized_keys` не существует и ключ не добавлялся в панели, выполни с другого
окна Terminal на Mac:

```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub deploy@<IPv4 VPS>
```

Проверь новый вход **во втором окне Terminal, не закрывая root-сессию**:

```bash
ssh deploy@<IPv4 VPS>
sudo -v
```

`sudo -v` может запросить пароль `deploy`; успешное выполнение не должно показать ошибку. Если вход
не работает, исправь ключ из root-сессии/VNC, не переходи к закрытию root-доступа.

### 1.4. Закрыть парольный и root-вход, включить защиту

В shell VPS под `deploy` создай настройки SSH:

```bash
sudo tee /etc/ssh/sshd_config.d/00-hardening.conf >/dev/null <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
AllowUsers deploy
EOF
sudo sshd -t
sudo systemctl restart ssh
sudo sshd -T | grep -Ei 'permitrootlogin|passwordauthentication|allowusers'
```

Последняя команда должна показать `permitrootlogin no`, `passwordauthentication no` и `allowusers deploy`.
Открой ещё одно окно Mac и снова проверь `ssh deploy@<IPv4 VPS>` прежде, чем закрывать текущую сессию.

Настрой UFW, оставив SSH доступным:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw enable
sudo ufw status verbose
```

На вопрос `Proceed with operation` ответь `y`. В статусе должны быть SSH/22, 80/tcp, 443/tcp,
443/udp. В панели облачного firewall выставь такие же входящие правила. Порты 5432, 6379, 8000,
8080 не открывай.

Поставь fail2ban и автоустановку обновлений:

```bash
sudo apt install -y fail2ban unattended-upgrades
sudo tee /etc/fail2ban/jail.local >/dev/null <<'EOF'
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled = true
backend = systemd
EOF
sudo systemctl enable --now fail2ban
sudo fail2ban-client status sshd
sudo dpkg-reconfigure -plow unattended-upgrades
```

В диалоге unattended-upgrades ответь `Yes`. В статусе fail2ban должна быть секция `sshd`.

### 1.5. Поставить Docker и swap

Выполняй на VPS под `deploy`:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
```

Выйди с VPS (`exit`) и подключись заново, чтобы группа применилась:

```bash
ssh deploy@<IPv4 VPS>
docker compose version
```

Версия Docker Compose должна быть 2.24 или новее. Настрой ограничение логов и перезапусти Docker:

```bash
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {"max-size": "10m", "max-file": "3"}
}
EOF
sudo systemctl restart docker
```

Создай swap 2 ГБ (если его ещё нет: сначала проверь `swapon --show`):

```bash
swapon --show
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

Если `swapon --show` уже показывает `/swapfile`, повторно его не создавай. В `free -h` строка Swap
должна показывать примерно 2 GiB.

### 1.6. Добавить SSH-алиас на Mac

На Mac (не на VPS) выполни:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
cat >> ~/.ssh/config <<'EOF'
Host vse-vezde
    HostName 77.110.105.235
    User deploy
    IdentityFile ~/.ssh/id_ed25519
EOF
chmod 600 ~/.ssh/config
ssh vse-vezde
```

Если такой блок уже есть, отредактируй `nano ~/.ssh/config`, не добавляй дубликат. Успешное
подключение должно открыть shell `deploy` на сервере.

### 1.7. Подготовить доступ к приватному GitHub-репозиторию

На VPS под `deploy` проверь доступ. Если clone уже доступен, перейди к следующему пункту:

```bash
ssh -T git@github.com
```

Если доступ запрещён, создай на VPS отдельный read-only deploy key:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N '' -C 'vse-vezde-readonly'
cat ~/.ssh/github_deploy.pub
```

Скопируй выведенную **публичную** строку. В GitHub открой репозиторий `MaxHackathonTeam/Max_Bot` →
**Settings → Deploy keys → Add deploy key**. Название, например `vse-vezde VPS`; вставь ключ;
галочку **Allow write access** не ставь; сохрани. Вернись на VPS:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
    IdentityFile ~/.ssh/github_deploy
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
ssh -T git@github.com
```

GitHub может сообщить, что shell access не предоставляется; это ожидаемо, если аутентификация
успешна и показано имя аккаунта/репозитория.

### 1.8. Склонировать проект и заполнить production `.env`

На VPS:

```bash
git clone git@github.com:MaxHackathonTeam/Max_Bot.git ~/afisha
cd ~/afisha
python3 backend/scripts/configure_env.py
```

Скрипт сам создаст `.env` с правами `600`, сгенерирует независимые пароли PostgreSQL, JWT и
webhook, подставит пароли в оба URL базы и спросит значения интеграций. Секретные ответы вводятся
без отображения на экране. Для необязательных интеграций нажми Enter, чтобы оставить поле пустым.
Команда рассчитана на новый checkout без существующего `.env`; если файл уже есть, скрипт остановится
и не перезапишет его. Не запускай `cat .env` и не присылай его содержимое: там секреты.

### 1.9. Запустить production

Перед запуском ещё раз проверь A-запись:

```bash
dig +short A vse-vezde.ru @8.8.8.8
```

Она должна в точности совпадать с IPv4 VPS. Затем на VPS в `~/afisha` запусти:

```bash
cd ~/afisha
docker compose -f compose.yaml -f compose.prod.yaml up -d --build --wait
docker compose -f compose.yaml -f compose.prod.yaml ps
```

Дождись завершения сборки. В `ps` сервисы должны быть `Up`/`healthy`; при ошибке смотри только
логи нужного сервиса и перед передачей удаляй секреты:

```bash
docker compose -f compose.yaml -f compose.prod.yaml logs --tail=100 api
docker compose -f compose.yaml -f compose.prod.yaml logs --tail=100 caddy
```

С Mac проверь HTTPS:

```bash
curl -i https://vse-vezde.ru/health
curl -i https://vse-vezde.ru/ready
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://vse-vezde.ru/bot/webhook \
  -H 'X-Max-Bot-Api-Secret: wrong' -H 'Content-Type: application/json' -d '{}'
```

Ожидается: `/health` HTTP 200 и `{"status":"ok"}`; `/ready` HTTP 200; webhook с неверным
секретом HTTP 401. Проверка лога webhook на VPS:

```bash
cd ~/afisha
docker compose -f compose.yaml -f compose.prod.yaml logs api | grep bot_webhook
```

После подключения токена бота лог должен содержать `bot_webhook_subscribed`. Не копируй строки,
если они содержат токен или персональные данные.

### 1.10. Проверить внешние порты

На VPS выполни:

```bash
sudo ss -tulpn
sudo ufw status verbose
```

Из интернета должны быть доступны только SSH/22, HTTP/80 и HTTPS/443 (TCP/UDP); напрямую API,
web, Postgres и Redis наружу не публикуются. На Mac выполни:

```bash
nc -zv -w3 <IPv4 VPS> 5432
nc -zv -w3 <IPv4 VPS> 6379
nc -zv -w3 <IPv4 VPS> 8000
nc -zv -w3 <IPv4 VPS> 8080
curl -I http://vse-vezde.ru
ssh root@<IPv4 VPS>
```

`nc` на приватных портах должен сообщить отказ/timeout; HTTP должен перенаправить на HTTPS (обычно
308); SSH root должен отказать. Убедись, что ошибка root-входа именно в запрете, а `ssh vse-vezde`
по-прежнему работает.

### 1.11. Включить ежедневную резервную копию

На VPS, под `deploy`, создай скрипт. Команды копируй целиком:

```bash
mkdir -p ~/bin ~/backups
cat > ~/bin/afisha-backup.sh <<'EOF'
#!/bin/sh
set -eu
cd "$HOME/afisha"
f="$HOME/backups/afisha-$(date +%F-%H%M).dump"
docker compose exec -T db pg_dump -U afisha -Fc afisha > "$f"
find "$HOME/backups" -name 'afisha-*.dump' -mtime +7 -delete
EOF
chmod 700 ~/bin/afisha-backup.sh
```

Запусти вручную и проверь, что появился непустой файл:

```bash
~/bin/afisha-backup.sh
ls -lh ~/backups
```

Добавь запуск ежедневно в 03:30 по времени VPS (UTC):

```bash
crontab -e
```

Если редактор спросит, выбери `nano`. В конец добавь ровно эту строку, сохрани `Ctrl+O`, Enter,
`Ctrl+X`:

```cron
30 3 * * * $HOME/bin/afisha-backup.sh >> $HOME/backups/backup.log 2>&1
```

Проверь запись командой `crontab -l`. До важного демо скачай dump на Mac, заменив имя файлом из
`ls -lh`:

```bash
scp vse-vezde:~/backups/<имя-файла>.dump ~/Downloads/
```

В панели VPS создай snapshot перед демо. Dump содержит персональные данные: храни в закрытом месте.
Проверку восстановления делай только на отдельном тестовом сервере/БД, не на production. На
production не вводи приведённую ниже команду восстановления:

```bash
docker compose exec -T db pg_restore -U afisha -d afisha --clean --if-exists < ~/backups/<имя-файла>.dump
```

## Этап 2. MAX: бот, Mini App и администраторы

### 2.1. Создать или выбрать бота

В браузере на Mac открой [business.max.ru](https://business.max.ru/) и войди в аккаунт, которому
принадлежит бот. В каталоге ботов выбери существующего бота либо создай нового. Открой настройки
Bot API, включи возможность работы с API/webhook. Скопируй токен и username в менеджер паролей.
Токен — секрет, username — публичное имя без `@`.

На VPS открой `.env` через `nano ~/afisha/.env` и заполни `MAX_BOT_TOKEN`, `MAX_BOT_USERNAME`.
Сохрани `Ctrl+O`, Enter, `Ctrl+X`. Перезапусти api/worker:

```bash
cd ~/afisha
docker compose up -d --force-recreate api worker
docker compose logs --tail=100 api
```

Проверяй только наличие `bot_webhook_subscribed`; никогда не печатай значение токена.

Проверь, что в `~/afisha/.env` заполнены (значения не печатай, только наличие:
`grep -cE '^(ADMIN_MAX_USER_IDS|PUBLIC_BASE_URL|MAX_WEBHOOK_SECRET|MAX_BOT_USERNAME)=.+' ~/afisha/.env`
должно вывести `4`):

- [ ] `PUBLIC_BASE_URL=https://vse-vezde.ru` — обязательно `https://`, иначе webhook и ссылки в боте не работают;
- [ ] `MAX_WEBHOOK_SECRET` — `openssl rand -hex 24`;
- [ ] `MAX_BOT_USERNAME` — имя бота без `@`;
- [ ] `ADMIN_MAX_USER_IDS` — см. 2.3.

После перезапуска прогони диагностику и, если она показывает проблему с подпиской, — исправление:

```bash
cd ~/afisha
docker compose -f compose.yaml -f compose.prod.yaml exec api python -m app.bot.doctor
docker compose -f compose.yaml -f compose.prod.yaml exec api python -m app.bot.doctor --fix
curl -fsS https://vse-vezde.ru/ready    # в "bot" должно быть "state": "ok"
```

- [ ] В MAX: `/start` → приветствие и меню; в меню команд видны `/find`, `/add`, `/my`, `/myid`
  (что клиенты MAX показывают команды из `PATCH /me/commands` — не подтверждено, проверь глазами).
- [ ] «Найти» → выбери пункт → две отдельные ленты «Официальные» и «От жителей»; для пункта без событий
  бот предлагает ближайшие.
- [ ] «Добавить афишу» → пройди мастер до конца → бот пишет, что заявка на модерации.

### 2.2. Подключить Mini App

В настройках выбранного бота открой раздел **Мини-приложение**. В URL укажи:

```text
https://vse-vezde.ru/
```

Сохрани настройку, затем открой бота в MAX и запусти приложение из меню. Проверь, что приложение
загрузилось по HTTPS и запрос согласия отображается. Диплинк события имеет вид
`https://max.ru/<MAX_BOT_USERNAME>?startapp=ev_1` (замени username на имя бота без `@`).

### 2.3. Назначить администраторов

С каждого аккаунта, который должен быть администратором, открой бота и отправь `/myid` — бот
ответит числовым `user_id`. Не используй номер телефона и не публикуй полный update. На VPS:

```bash
nano ~/afisha/.env
```

Укажи ID через запятую без пробелов, например `ADMIN_MAX_USER_IDS=123456789,987654321`, сохрани
файл и выполни:

```bash
cd ~/afisha
docker compose up -d --force-recreate api worker
docker compose logs --tail=100 api worker
```

С админского аккаунта отправь `/queue`. Должна открыться очередь модерации либо понятный ответ о
пустой очереди. Если бот говорит, что доступа нет, перепроверь цифры ID и перезапуск сервисов.

- [ ] С обычного аккаунта добавь афишу через бота — каждому админу приходит сообщение о новой заявке
  с кнопкой-ссылкой на `https://vse-vezde.ru/moderation/<id>`.
- [ ] Отклони её с причиной — автор получает сообщение с причиной.

## Этап 3. Пройти ручную проверку приложения

### 3.1. Локальный прогон на Mac

На Mac в терминале из корня проекта:

```bash
cd /Users/zhiroffjaroslav/VSProjects/Max_Bot
cp .env.example .env
```

Открой `.env` в редакторе и временно выставь `DEV_AUTH=1`, `OFFLINE_MODE=1`. Затем подними локальный
стек:

```bash
docker compose up -d --build --wait
```

Открой `http://localhost:8080`. Если это первый запуск, дождись сборки. Пройди сценарии из
`docs/QA_CHECKLIST.md`: согласие, каталог, фильтры, карточка, «Пойду», настройки, удаление аккаунта,
организатор и модерация. У демо-событий должен быть бейдж «Демо-данные». Отметь ошибки и шаги
воспроизведения; не записывай настоящие персональные данные.

По завершении останови локальные контейнеры:

```bash
docker compose down
```

Не запускай локальный `bot-poller` с production токеном.

### 3.2. MAX на телефоне, вебе и десктопе

На каждом устройстве войди в MAX аккаунтом пользователя и пройди последовательно:

1. Открыть бота и отправить `/start`.
2. Принять согласие и разрешить геолокацию либо вручную указать населённый пункт.
3. Нажать «📍 Открыть афишу» и проверить загрузку Mini App.
4. Открыть карточку события по диплинку `startapp=ev_1`.
5. Проверить кнопку «Пойду», возврат BackButton, светлую и тёмную темы.
6. На телефоне проверить запрос геолокации/контакта, открытие ссылки на карту/билеты и отправку
   приглашения. Если Bridge действие не поддержано, проверить, что показан fallback.
7. Уменьшить ширину окна до 320 px и проверить, что текст/кнопки не обрезаны.

Записывай модель устройства, версию MAX, шаг и итог в таблицу:

| Платформа / версия MAX | Сценарий | Результат | Ошибка/номер скриншота |
|---|---|---|---|
| iOS / заполнить | `/start` → Mini App | заполнить | заполнить |
| Android / заполнить | `/start` → Mini App | заполнить | заполнить |
| Web / заполнить | `/start` → Mini App | заполнить | заполнить |
| Desktop / заполнить | `/start` → Mini App | заполнить | заполнить |

Скриншоты перед передачей проверь на телефоны, user ID, initData, токены и другие персональные
данные. При ошибке Bridge сравни поведение с [документацией MAX Bridge](https://dev.max.ru/docs/webapps/bridge)
и передай только обезличенную структуру проблемы.

## Этап 4. Получить ключи интеграций и проверить организацию

### 4.1. GigaChat

1. Открой [developers.sber.ru](https://developers.sber.ru/) и войди через Сбер ID.
2. Создай проект/доступ к GigaChat API по инструкции кабинета и выпусти authorization key.
3. Сохрани ключ в менеджер паролей; в чат его не копируй.
4. Открой официальную актуальную документацию этого API и скопируй оттуда OAuth и API endpoints.
   Не используй URL из старых примеров.
5. На VPS добавь через `nano ~/afisha/.env`:

   ```dotenv
   GIGACHAT_AUTH_KEY=<ключ>
   GIGACHAT_SCOPE=GIGACHAT_API_PERS
   GIGACHAT_OAUTH_URL=<OAuth URL из актуальной документации>
   GIGACHAT_API_URL=<API URL из актуальной документации>
   GIGACHAT_CA_BUNDLE=/app/certs/<имя-файла>
   ```

6. Получи корневой сертификат НУЦ Минцифры из инструкции GigaChat. Если скачан DER/CER и инструкция
   требует PEM, преобразуй локально на Mac командой из инструкции; не переименовывай сертификат,
   не изменив формат.
7. Помести сертификат в `infra/certs/` в checkout проекта на VPS согласно структуре volume проекта.
   Проверь `infra/certs/README.md`; не удаляй этот файл. Сертификат не является секретом, но не
   коммить его без необходимости.
8. Пересоздай worker и проверь ошибки подключения:

   ```bash
   cd ~/afisha
   docker compose up -d --build --force-recreate worker
   docker compose logs --tail=100 worker
   ```

   В логах не должно быть TLS/401 ошибки от GigaChat. Не выводи `.env`.

Если ключа пока нет, приложение должно работать в fallback режиме: модерация остаётся ручной в
`/queue`, проверка сайта — ручная. Отметь `[~]` до получения ключа.

### 4.2. DaData и проверка организации

1. Открой [dadata.ru](https://dadata.ru/), создай аккаунт и открой кабинет API.
2. Выпусти API key; Secret key добавляй только если он требуется выбранным тарифом/API-методом.
3. На VPS открой `nano ~/afisha/.env`, заполни `DADATA_API_KEY` и при необходимости
   `DADATA_SECRET_KEY`, сохрани файл.
4. Подготовь реальную организацию: её ИНН, официальный HTTPS-сайт и опубликованный телефон,
   доступный владельцу аккаунта MAX. Используй только данные организации, которой разрешено
   управлять.
5. В Mini App открой **Настройки → Кабинет организатора** и пройди создание организации по ИНН.
   Выбери предусмотренный продуктом способ проверки B.
6. Запусти проверку контакта из бота и заверши подтверждение кодом на сайте. Проверь статус
   организации; не вводи код в чат с помощником и не публикуй телефон.
7. Создай тестовое событие и проверь, что подтверждённое событие появляется в «Официальных» с
   бейджем. Со второго MAX аккаунта предложи отдельное событие и проверь появление в «От сообщества».
8. Отправь тестовый запрещённый текст (например, «онлайн-казино») и проверь понятный отказ/причину.
9. На админском аккаунте отправь `/queue`, проверь approve/reject, причину отказа, отзыв верификации
   и `/admin/audit`.
10. В кабинете организатора проверь создание организации, приглашение editor, экран верификации,
    форму события по шагам (сеансы и часовой пояс → площадка → обложка → доступная среда → просмотр
    перед отправкой), отправку, отмену, удаление и статусы списка.
11. Если `request_contact` возвращает ошибку подписи, зафиксируй платформу, шаг и названия полей,
    но удали значения `phone`, имя и `vcf_info`. Нужен разбор по актуальному формату MAX.

### 4.3. Юридические документы и согласия

1. Открой `frontend/src/pages/LegalPage.tsx` в редакторе проекта.
2. Передай черновики `/legal/privacy`, `/legal/terms`, `/legal/org_pd` юристу/оператору ПДн.
3. Подготовь точные данные владельца сервиса: полное наименование/ФИО, ИНН или ОГРНИП, адрес
   для обращений и рабочий e-mail. Не придумывай реквизиты; если их нет, запроси у владельца проекта.
4. Внеси согласованные формулировки и реквизиты в LegalPage, проверь тексты в браузере:
   `https://vse-vezde.ru/legal/privacy`, `/legal/terms`, `/legal/org_pd`.
5. После изменения согласия увеличь версию `VERSION` в `LegalPage.tsx` и соответствующие версии
   в `CONSENT_VERSIONS` файла `backend/app/services/users.py`, чтобы фронтенд и сервер требовали
   одну и ту же версию.
6. Пересобери web/api и пройди onboarding чистым тестовым аккаунтом. Сохрани дату и одобрение
   ответственного юриста. Это юридическое решение, не отмечай выполненным до его проверки.

## Этап 5. Импорт данных, уведомления и eval-наборы

### 5.1. PRO.Культура.РФ

1. Подготовь короткий запрос с названием проекта, описанием, организацией, контактным лицом и
   регионами, которые планируется покрывать.
2. Отправь запрос на `partners@team.culture.ru` с рабочего адреса организации.
3. После выдачи ключа сохрани его в менеджере паролей, затем на VPS в `.env` заполни
   `PROCULTURE_API_KEY`.
4. Найди административную команду импорта в интерфейсе/README проекта или запроси её у Claude;
   сначала проверь справку команды (`--help`), не запускай неизвестную destructive-команду.
5. Выполни импорт по выбранным регионам, проверь число загруженных/дедуплицированных событий и
   запись аудита. До получения ключа источником остаётся помеченная фикстура
   `data/fixtures/proculture.json`.

### 5.2. Разметить eval JSONL

На Mac из корня репозитория изучи примеры и eval-скрипт:

```bash
cd /Users/zhiroffjaroslav/VSProjects/Max_Bot
head -5 data/eval/enrich_100.jsonl
head -5 data/eval/moderation_60.jsonl
sed -n '1,240p' backend/scripts/eval.py
```

Открой файлы `data/eval/enrich_100.jsonl` и `data/eval/moderation_60.jsonl` в редакторе, который
не форматирует JSON автоматически. Для каждой строки заполни `label` по схеме соседних примеров:
для enrich ожидаются поля вроде `category` и `youth_score`; для moderation — `verdict`. Сверяйся
с кодом eval и допустимыми enum в приложении. Не меняй `input`, не удаляй строки, сохраняй ровно
один JSON-объект на строку. Перед запуском проверь число строк и валидность JSON:

```bash
wc -l data/eval/enrich_100.jsonl data/eval/moderation_60.jsonl
python3 -c 'import json,pathlib; [json.loads(x) for p in map(pathlib.Path, ["data/eval/enrich_100.jsonl", "data/eval/moderation_60.jsonl"]) for x in p.read_text().splitlines() if x.strip()]; print("JSONL OK")'
```

Ожидается 100 и 60 строк и `JSONL OK`. Затем, из корня:

```bash
make eval
```

Сохрани итоговые метрики, дату и версию/commit в рабочем отчёте. Не переобучай/не меняй метки,
чтобы искусственно повысить результат; спорные примеры отдельно запиши для обсуждения.

### 5.3. Проверить расписание бота и уведомления

На чистом тестовом аккаунте пройди `/start`, согласие, геолокацию или ввод города, «Сегодня»,
«Выходные», «По Пушкинской», «Ещё», «⭐ Пойду», «Мои Пойду», настройки радиуса/интересов/тихих
часов/уведомлений и `/delete_me` с подтверждением. Для каждой команды проверь, что при пустой
выдаче или временной сетевой ошибке бот отвечает и предлагает действие.

Создай тестовое событие с будущим сеансом и проверь напоминания за 24 и 2 часа, а также дайджест.
Проверь, что на production настроены worker и расписание/cron, необходимые проекту; посмотри
текущую конфигурацию worker в `compose.yaml` и не создавай второй cron, если расписание уже
выполняется сервисом. Запиши фактическое время запуска и полученное уведомление.

## Этап 6. Финальный контроль качества

### 6.1. Выполнить команды проекта

Команды запускать на Mac из корня свежего checkout. Они могут занять несколько минут. Сначала
проверь, что Docker запущен, затем:

```bash
cd /Users/zhiroffjaroslav/VSProjects/Max_Bot
make openapi
make lint
make test
make eval
```

`make test` для DB-тестов требует Postgres/PostGIS на localhost:55432. Если тестовой БД нет, запусти:

```bash
docker run -d --name afisha-testdb -p 55432:5432 \
  -e POSTGRES_USER=afisha -e POSTGRES_PASSWORD=afisha -e POSTGRES_DB=afisha \
  postgis/postgis:16-3.4
```

После окончания тестов останови только эту тестовую БД:

```bash
docker stop afisha-testdb
docker rm afisha-testdb
```

Выполни аудит зависимостей:

```bash
cd backend
uv run pip-audit
cd ../frontend
npm audit --audit-level=high
cd ..
```

Зафиксируй команду, дату, успешный/неуспешный результат и известные уязвимости/ограничения.
Ничего не прячь подавлением вывода. Если команды предлагают обновления, сначала изучи diff и
регрессионный риск.

### 6.2. Полный приёмочный прогон

Открой `docs/QA_CHECKLIST.md` и пройди каждый пункт на локальном окружении, затем повтори публичные
пункты на production: `/health`, `/ready`, Mini App, юридические страницы, заголовки безопасности,
неверный webhook → 401 и админская очередь. На Mac:

```bash
curl -i https://vse-vezde.ru/health
curl -i https://vse-vezde.ru/ready
curl -I https://vse-vezde.ru/legal/privacy
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://vse-vezde.ru/bot/webhook \
  -H 'X-Max-Bot-Api-Secret: wrong' -H 'Content-Type: application/json' -d '{}'
```

Ожидаемый HTTP: 200, 200, 200, 401. Проверь резервный dump и внешний snapshot; не проверяй
восстановление на единственной production-БД.

### 6.3. Данные хакатона и презентация

1. Открой официальный сайт/кабинет хакатона, скачай актуальный шаблон `DATA-API.yaml` и требования.
2. Сверь название проекта, поля API, форматы дат, ограничения и сроки с `DATA-API.yaml` в корне.
   Не подставляй неподтверждённые endpoint/данные.
3. Запиши официальный дедлайн и часовой пояс в календарь проекта.
4. Подготовь PDF-презентацию: проблема, сценарий пользователя, архитектура, происхождение данных,
   демонстрационный сценарий, результат ручного гейта и ограничения. На первом слайде оставь
   обязательную служебную информацию из требований хакатона.
5. Открой экспортированный PDF на другом устройстве и проверь шрифты, ссылки, читаемость и отсутствие
   токенов/персональных данных.

### 6.4. Заморозить сдаваемую версию

После успешного QA на Mac:

```bash
git status --short
git rev-parse HEAD
```

Проверь незакоммиченные изменения и согласуй каждое с командой. Запиши commit hash. После решения
команды создай тег (если у тебя есть право push):

```bash
git tag -a v1.0-submission -m "Release v1.0 submission"
git push origin v1.0-submission
```

Не создавай тег до финального одобрения версии. После тега фиксируй новые правки отдельным решением.

### 6.5. Решить, публиковать ли инструкции из `docs/`

Сейчас `docs/` игнорируется Git. На Mac проверь:

```bash
git check-ignore -v docs/HUMAN_TODO.md
git status --short --ignored docs/
```

Если команда решила передать документацию вместе с репозиторием, добавляй нужные файлы явно и
проверь staging:

```bash
git add -f docs/HUMAN_TODO.md docs/DEPLOY.md docs/VPS_SETUP.md docs/TECHDOC.md docs/DEV_PLAN.md
git status --short
```

Если документы остаются рабочими локальными инструкциями, ничего не добавляй. Не добавляй `.env`,
дампы, сертификаты или другие секреты.

## Переработка B. Автодеплой из GitHub Actions и веб-версия

Нужно один раз, после этапа 1 (VPS с `~/afisha`, `.env` и работающим production). После этого
каждый зелёный CI на `main` сам выкатывается на сервер (`.github/workflows/deploy.yml`), а при
ошибке сервер возвращается на предыдущий коммит. Подробности — `docs/DEPLOY.md`, раздел «CI/CD».

- [ ] **B.1. `deploy` в группе docker.** На VPS под `deploy`:

  ```bash
  id -nG | tr ' ' '\n' | grep -x docker
  docker compose version
  ```

  Ожидаемо: `docker` в выводе и версия Compose. Если `docker` нет — выполни шаг 1.5
  (`sudo usermod -aG docker deploy`), выйди и зайди снова.

- [x] **B.2. Отдельный ключ для GitHub Actions.** На Mac (не на VPS) — ключ только для деплоя,
  без пароля, не путать с личным `~/.ssh/id_ed25519`:

  ```bash
  ssh-keygen -t ed25519 -f ~/.ssh/afisha_actions -N '' -C 'afisha-github-actions'
  ssh-copy-id -i ~/.ssh/afisha_actions.pub vse-vezde
  ssh -i ~/.ssh/afisha_actions -o IdentitiesOnly=yes vse-vezde 'cd ~/afisha && git rev-parse --short HEAD'
  ```

  Ожидаемо: короткий хеш коммита без запроса пароля. Ключ попадает в
  `/home/deploy/.ssh/authorized_keys` на VPS. Если `ssh-copy-id` не сработал — добавь строку из
  `~/.ssh/afisha_actions.pub` в конец этого файла вручную (`nano ~/.ssh/authorized_keys`, права `600`).

- [ ] **B.3. Отпечаток хоста (known_hosts).** На Mac:

  ```bash
  ssh-keyscan -p 22 -t ed25519 77.110.105.235 > ~/afisha_known_hosts
  ssh-keygen -lf ~/afisha_known_hosts
  ```

  Сверь отпечаток `SHA256:…` с тем, что показывает сам VPS (на VPS:
  `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`). Совпал — файл годится; не совпал — стоп,
  ничего не заноси в GitHub. Если SSH на VPS не на 22 порту — подставь свой в `-p`.

- [x] **B.4. Environment `production` и секреты в GitHub.** Репозиторий `MaxHackathonTeam/Max_Bot` →
  **Settings → Environments → New environment** → имя ровно `production` → **Configure environment**.
  - По желанию: **Deployment branches and tags → Selected branches and tags → Add rule** → `main`.
  - По желанию: **Required reviewers** — тогда каждую выкладку надо будет подтверждать кнопкой.
  - В том же окне **Environment secrets → Add environment secret**, по одному:

  | Имя | Значение |
  |---|---|
  | `DEPLOY_SSH_KEY` | всё содержимое `~/.ssh/afisha_actions` (приватный, **без** `.pub`), включая строки `-----BEGIN…` и `-----END…`. Скопировать: `pbcopy < ~/.ssh/afisha_actions` |
  | `DEPLOY_HOST` | `77.110.105.235` (или домен, если по нему ходит SSH) |
  | `DEPLOY_USER` | `deploy` |
  | `DEPLOY_PORT` | `22` (или свой порт SSH) |
  | `DEPLOY_KNOWN_HOSTS` | содержимое `~/afisha_known_hosts`: `pbcopy < ~/afisha_known_hosts` |

  После этого удали с Mac временный файл: `rm ~/afisha_known_hosts`. Приватный ключ никуда кроме
  GitHub не вставляй; если он попал в чат или лог — удали строку из `authorized_keys` на VPS и повтори B.2.

- [ ] **B.5. Доступ сервера к репозиторию.** Если репозиторий приватный, у VPS должен быть
  read-only deploy key — это шаг 1.7 (галочку **Allow write access** не ставить). Проверка на VPS:

  ```bash
  cd ~/afisha && git fetch --dry-run origin && echo fetch-ok
  ```

- [ ] **B.6. Первая выкладка.** GitHub → **Actions → Deploy → Run workflow** → ветка `main` → поле
  `sha` оставить пустым → **Run workflow**. Ожидаемо: зелёный job, в логе
  «Готово: <sha> отвечает на /ready». Через то же окно с заполненным `sha` делается откат.
  - После включения автодеплоя сервер стоит на detached HEAD: команда `git pull --ff-only` из раздела
    «Обновление приложения» перестанет работать — вместо неё
    `git fetch && git checkout --detach origin/main && docker compose up -d --build --wait --remove-orphans`.

- [ ] **B.7. Веб без MAX.** Открой `https://vse-vezde.ru/` в обычном браузере (не в MAX):
  лента, поиск и карточка события открываются без входа; «Пойду» → согласие → событие появляется
  в «Пойду»; «Профиль → Войти через MAX» показывает код и ждёт подтверждения в боте.
  Подтверждение кода в боте проверяй после выкладки бэкенда переработки A.

- [ ] **B.8. Версия юридических документов.** Из политики конфиденциальности убраны DaData и
  GigaChat как получатели, текст согласия организатора изменён. Версия документов (`2026-09-23`)
  не поднята: она должна совпадать с `CONSENT_VERSIONS` на бэкенде. Реши вместе с юристом/командой,
  поднимать ли версию (тогда пользователи увидят согласие заново) — и поменяй её одновременно
  во фронте (`frontend/src/pages/LegalPage.tsx`) и бэкенде.

## Переработка A. Бэкенд без внешних сервисов

- [ ] На сервере удалить из `.env` переменные, которые больше не читаются: `GIGACHAT_AUTH_KEY`, `GIGACHAT_SCOPE`, `GIGACHAT_OAUTH_URL`, `GIGACHAT_API_URL`, `GIGACHAT_MODEL`, `GIGACHAT_CA_BUNDLE`, `LLM_DAILY_TOKEN_BUDGET`, `DADATA_API_KEY`, `DADATA_SECRET_KEY`, `NOMINATIM_USER_AGENT`, `PROCULTURE_API_KEY`, `OFFLINE_MODE`. Ключи GigaChat/DaData можно отозвать в их кабинетах. Этапы 4.1, 4.2, 5.1, 5.2 этого чек-листа больше не нужны.
- [ ] Убедиться, что в серверном `.env` задан `MAX_BOT_USERNAME` (без @) — без него вход на сайте кодом отвечает 503.
- [ ] После деплоя применить миграцию (`make migrate` или автодеплой) — она удаляет таблицы `llm_calls`, `import_runs` и колонку `proculture_org_id`. Перед этим — свежий бэкап.
- [ ] Проверить вход на сайте кодом в MAX руками:
  1. Открыть сайт в браузере (не в MAX), нажать «Войти через MAX».
  2. Перейти по ссылке `https://max.ru/<бот>?start=login_<код>` — бот должен прислать «Подтвердить вход на сайте?» с кнопкой.
  3. Нажать кнопку — сайт в течение пары секунд должен войти, «Пойду» гостя — остаться.
  4. Повторить, когда диалог с ботом **уже открыт** (не первый запуск). Если бот молчит — отправить боту текстом `/start login_<код>`; записать в «Отчёт», какой вариант сработал (это не подтверждено документацией MAX).
  5. Подождать 5 минут без подтверждения — сайт должен показать «Код истёк».

## Сайт: афиша, публикация, модерация (ветка `feature/site-afisha`)

- [ ] Посмотреть PR из `feature/site-afisha` и решить, когда мёржить: ветку нужно перебазировать
  на `feature/bot-ux-localities` (справочник РФ, `GET /admin/events/{id}`, уведомления админам).
  Без неё карточка `/moderation/<id>` показывает ошибку, хотя решение принять можно.
- [ ] Проверить, что в серверном `.env` в `ADMIN_MAX_USER_IDS` есть все модераторы: только они видят
  «Модерация» в меню профиля и могут открыть `/moderation`.
- [ ] После выкладки пройти на сервере сценарий из `docs/QA_CHECKLIST.md`, раздел «Сайт: афиша,
  публикация, модерация», уже с настоящим входом кодом через бота. Отдельно проверить, что автору
  приходит в бот сообщение о решении модератора (одобрено / отклонено с причиной / возвращено).
- [ ] Решить, устраивает ли разбор анонса: сейчас название черновика — весь текст анонса, автор
  правит его на первом шаге.

## Сайт: полировка, тёмная тема, демо Казань/Москва (ветка `feature/site-polish-demo`)

Бот не ответил при локальной проверке 29.09. Причина в коде (`make up` не поднимал `bot-poller`)
исправлена; остальное — внешние настройки, их можешь сделать только ты.

- [ ] `Mac`: открыть MAX API из своей сети. Сейчас `platform-api2.max.ru` резолвится в адрес
  `240.0.1.x` (подмена DNS в VPN), и соединение обрывается по таймауту. Выключи VPN или добавь
  `*.max.ru` в исключения, затем проверь:
  ```bash
  curl -sS -o /dev/null -w '%{http_code}\n' https://platform-api2.max.ru/me
  ```
  Ожидаемо: любой HTTP-код (без токена — ошибка авторизации). Таймаут или `000` — сеть всё ещё
  блокирует.
- [ ] `Mac`: в локальном `.env` заполнить `MAX_BOT_USERNAME` (имя бота без `@`; узнать —
  `uv run python tools/get_max_bot_name.py`) и `ADMIN_MAX_USER_IDS` (свой id — команда `/myid`
  в боте). Без `MAX_BOT_USERNAME` кнопка «Войти через MAX» отвечает «Вход через MAX сейчас
  недоступен». Значения в чат не присылай.
- [ ] `Mac`: убедиться, что токен в `.env` — **не** от production-бота с живым webhook.
  `make up` теперь поднимает `bot-poller`, а он снимает webhook. Для боевого бота заведи
  отдельного тестового бота.
- [ ] `Mac`: `make up`, затем `docker compose exec api python -m app.bot.doctor`. Ожидаемо:
  `GET /me` ок, bot-poller недавно опрашивал MAX, проблем нет. Написать боту `/start` и любой
  текст — должен ответить меню и подсказкой.
- [ ] `Mac`: на http://127.0.0.1:8080 нажать «Войти через MAX», открыть ссылку, подтвердить в
  боте — сайт должен войти сам в течение нескольких секунд.
- [ ] Кабинет MAX (шаг 2.2): мини-приложение привязать **к тому же боту**, чей токен на сервере,
  и указать HTTPS-URL сайта (`https://vse-vezde.ru/`). Иначе подпись initData не сойдётся и
  вход в MAX вернёт ошибку.
- [ ] Глазами проверить тёмную тему (переключатель в шапке и в «Настройках») на своём телефоне
  и favicon во вкладке браузера и на домашнем экране iOS. Тема в MAX берётся из системной:
  Bridge не сообщает тему приложения MAX.
- [ ] Проверить на карте координаты новых демо-площадок в `data/seed/cities.json` (Казань:
  театр оперы и балета им. Джалиля, театр Качалова, ГМИИ РТ, «Чёрное озеро»; Москва: 8
  площадок). Они указаны по памяти, геокодер не использовался; если точка заметно смещена —
  поправь `lat`/`lon`.

### Прод: нет афиш в Москве и Казани, «Открыть бота» не уводит с сайта (29.09)

Проверка https://vse-vezde.ru 29.09: `/api/v1/events` отдаёт 0 событий в обеих лентах не только
в Москве и Казани, но и в Великом Новгороде. Значит, демо-набор на проде не загружен совсем.
`/auth/web-code` работает и отдаёт ссылку на бота, то есть `MAX_BOT_USERNAME` задан. Кнопка
«Открыть бота» ничего не делала в браузере — это баг кода, он исправлен в этой ветке.

- [ ] GitHub: открыть PR ветки `feature/site-polish-demo`
  (https://github.com/MaxHackathonTeam/Max_Bot/pull/new/feature/site-polish-demo) и смёржить в
  `main` после зелёного CI. Без этого на проде нет ни Москвы, ни исправления кнопки.
- [ ] `VPS`: в `~/afisha/.env` должна быть строка `SEED_DEMO=1` (сейчас демо не грузится —
  скорее всего там `SEED_DEMO=0`). После выкладки `main` загрузить демо и проверить:
  ```bash
  cd ~/afisha
  grep -c '^SEED_DEMO=1$' .env   # ожидаемо 1
  docker compose -f compose.yaml -f compose.prod.yaml run --rm migrate
  curl -s 'https://vse-vezde.ru/api/v1/events?locality_id=14077&tier=official' | head -c 300
  ```
  Ожидаемо: в логе `migrate` строка `seed_loaded` с созданными событиями (не `seed_skipped`), а
  в ответе `curl` непустой `items`. Для Москвы — `locality_id=144067`.
- [ ] Браузер: на https://vse-vezde.ru «Войти через MAX» → «Открыть бота». Должна открыться
  новая вкладка с ботом в MAX; на телефоне удобнее отсканировать QR-код. Подтвердить вход в
  боте — сайт войдёт сам.

## Обновление приложения и повседневные команды

На VPS под `deploy`:

```bash
ssh vse-vezde
cd ~/afisha
git pull --ff-only
docker compose up -d --build --remove-orphans
docker compose ps
```

Так как в production `.env` задан `COMPOSE_FILE=compose.yaml:compose.prod.yaml`, обычный Compose
подхватывает оба файла. Проверить логи:

```bash
docker compose logs -f --tail=100 api worker caddy
```

Выйти из потока логов: `Ctrl+C` (контейнеры продолжат работать). Проверить место и Docker:

```bash
df -h
docker system df
```

Если нужно освободить место, сначала изучи `docker system df`, затем можно удалить только
неиспользуемые образы:

```bash
docker image prune -f
```

Не запускай `docker system prune --volumes`.

Для внешнего мониторинга создай аккаунт у выбранного uptime-сервиса, добавь HTTP(S) мониторинг
`https://vse-vezde.ru/health` с периодом около 5 минут и уведомление владельцу. Не вводи в сервис
секреты приложения. При желании проверь TLS на [SSL Labs](https://www.ssllabs.com/ssltest/).

## Инциденты

- **Утёк секрет:** в кабинете MAX отзови/перевыпусти bot token; остальные значения пересоздай на VPS
  через `openssl rand -hex 32` (webhook — `openssl rand -hex 24`), замени `.env`, пересоздай
  затронутые сервисы. После изменения токена удостоверься, что webhook снова подписан.
- **Потерян SSH-доступ:** не закрывай текущую активную сессию. Войди через VNC/web console провайдера,
  проверь `/home/deploy/.ssh/authorized_keys`, `sshd -t` и UFW, затем проверь новый вход из второго
  окна Mac.
- **Не хватает места:** проверь `df -h` и `docker system df`. Сначала скачай/сохрани актуальный dump;
  не удаляй Docker volumes и файлы БД.
- **Нет HTTPS:** проверь A-запись, UFW и облачный firewall на 80/443; на VPS смотри
  `docker compose logs --tail=100 caddy`. Не перезапускай Caddy многократно при неверной DNS-записи.
- **Снаружи открыты 5432/6379/8000/8080:** пошагово — раздел ниже.

### Открыты приватные порты (5432, 6379, 8000, 8080)

**Сначала исключи ложную тревогу:** `nc -zv -w3 <IP> 54321` (там заведомо пусто). Если и он
«succeeded» — соединения принимает VPN/прокси в TUN-режиме на Mac, а не сервер (так и было
27.09.2026). Выключи VPN или проверь порты через check-host.net → TCP.

В репозитории `db` и `redis` порты не публикуют вовсе, а `api`/`web` с 27.09.2026 слушают только
`127.0.0.1`. Если порт всё равно открыт — его держит либо стек, запущенный без `compose.prod.yaml`,
либо что-то постороннее на сервере.

**Шаг 1. Mac: отправить фикс `compose.yaml` на GitHub** (если ещё не отправлен):

```bash
cd ~/VSProjects/Max_Bot
git add compose.yaml && git commit -m "Порты api/web только на 127.0.0.1" && git push
```

**Шаг 2. VPS: выяснить, кто держит порты.**

```bash
ssh vse-vezde
cd ~/afisha
sudo ss -tlnp | grep -E ':(5432|6379|8000|8080)\b'
docker ps --format 'table {{.Names}}\t{{.Ports}}'
grep -c '^COMPOSE_FILE=compose.yaml:compose.prod.yaml' .env   # должно быть ≥ 1
docker compose version                                          # нужно ≥ 2.24
git status --short                                              # локальных правок быть не должно
```

Как читать `ss`: в конце строки `users:(("docker-proxy",…))` — порт открыл контейнер;
`("postgres",…)` / `("redis-server",…)` — служба, установленная в систему.

**Шаг 3. Закрыть порты — по результату шага 2.**

- *Системные Postgres/Redis* (в `ss` — `postgres`, `redis-server`). Проекту не нужны, он использует
  свои контейнеры:
  ```bash
  sudo systemctl disable --now postgresql redis-server
  ```
  Если сервис называется иначе — `systemctl list-units --type=service | grep -Ei 'postgres|redis'`.
- *Посторонние контейнеры* (в `docker ps` имя не `afisha-…`, но порт 5432/6379/8000/8080).
  Убедись, что они не нужны, затем `docker stop <имя> && docker rm <имя>`.
- *Наши контейнеры `afisha-…` с портами.* Значит, prod-файл не подхватился или на сервере правлен
  `compose.yaml`. Если `grep` вернул `0` — допиши в `.env` строку
  `COMPOSE_FILE=compose.yaml:compose.prod.yaml`. Если `git status` показал правки — посмотри их
  (`git diff`) и откати: `git checkout -- compose.yaml compose.prod.yaml`. Затем пересоздай стек
  (данные в volumes сохраняются; **не добавляй `-v`**):
  ```bash
  git pull --ff-only
  docker compose down
  docker compose up -d --build --wait
  docker ps --format 'table {{.Names}}\t{{.Ports}}'
  ```
  Порты должны быть только у `afisha-caddy-1` (80, 443).

**Шаг 4. Mac: проверить снаружи.**

```bash
for p in 5432 6379 8000 8080; do nc -zv -w3 77.110.105.235 $p; done   # все — timeout/refused
curl -sI https://vse-vezde.ru/health | head -1                        # HTTP/2 200
```

Дополнительно включи в панели хостера облачный firewall (входящие только 22, 80, 443 TCP и 443
UDP) — он работает до Docker и страхует от повторения. UFW Docker-порты не закрывает.

**Шаг 5. VPS: сменить пароли БД — только если в шаге 2 порт 5432 был у `afisha-db`.**
Postgres не меняет пароль по новому `.env` в существующем volume, поэтому пароль владельца меняем
в самой БД, а пароль `afisha_app` выставит `migrate` при перезапуске:

```bash
cd ~/afisha
cp .env .env.bak && chmod 600 .env.bak
NEW_PG=$(openssl rand -hex 32); NEW_APP=$(openssl rand -hex 32)
printf "ALTER ROLE afisha PASSWORD '%s';\n" "$NEW_PG" \
  | docker compose exec -T db psql -U afisha -d afisha -v ON_ERROR_STOP=1
sed -i \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$NEW_PG|" \
  -e "s|^APP_DB_PASSWORD=.*|APP_DB_PASSWORD=$NEW_APP|" \
  -e "s|^MIGRATE_DATABASE_URL=.*|MIGRATE_DATABASE_URL=postgresql+asyncpg://afisha:$NEW_PG@db:5432/afisha|" \
  -e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+asyncpg://afisha_app:$NEW_APP@db:5432/afisha|" \
  .env
unset NEW_PG NEW_APP
docker compose up -d --force-recreate --wait
curl -s https://vse-vezde.ru/ready
```

Если `psql` вывел ошибку — остановись: `.env` ещё не менялся. Если `/ready` не 200 — пришли
`docker compose logs --tail=50 migrate api` (без секретов); **не возвращай `.env.bak`**: пароль в БД
уже новый. После успешной проверки: `shred -u .env.bak`.

**Шаг 6. VPS: проверить следы взлома — если Redis (любой) был открыт.** Открытый Redis без пароля
часто используют, чтобы записать SSH-ключ или задание cron:

```bash
sudo crontab -l; crontab -l; ls -la /etc/cron.d
sudo cat /root/.ssh/authorized_keys; cat ~/.ssh/authorized_keys
```

Чужие ключи или непонятные задания — удали и сообщи; при сомнениях проще пересоздать VPS.

## Отчёт о готовности

Заполни и отправь команде только после удаления IP (если нежелателен), персональных данных и
любых секретов:

```text
Домен: vse-vezde.ru
DNS A указывает на VPS: да/нет
VPS: провайдер/регион, Ubuntu версия
Проверки: health=200/..., ready=200/..., неверный webhook=401/...
MAX: Mini App подключён=да/нет, username=<публичный username без @>
Ключи заведены: MAX=да/нет
Проверки устройств: iOS=..., Android=..., web=..., desktop=...
Бэкап: ручной dump=да/нет, cron=да/нет, копия вне VPS=да/нет, snapshot=да/нет
Проверки: lint=..., test=..., QA checklist=...
Блокеры: <список или «нет»>
```

## Сделано
