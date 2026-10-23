# FitCheck: запуск, наблюдение и восстановление (ANY-654)

## Что подготовлено

`compose.yaml` запускает PostgreSQL 17, однократную миграцию, API, worker и сайт.
Профиль `operations` добавляет ежедневные локальные копии, еженедельное проверочное
восстановление и Prometheus. `compose.prod.yaml` ограничивает логи и привилегии.
Реальные окружения Dokploy эти файлы автоматически не меняют.

Внешнее S3 и получатель уведомлений ещё не настроены. Локальный том бэкапов не
защищает от потери сервера. Правила alerts доступны в Prometheus; доставка сообщений
начнёт работать после подключения Alertmanager и проверки реального получателя.
SMTP подключается отдельно; без него регистрация и восстановление пароля недоступны.

## Окружение и первый запуск

Скопировать `.env.compose.example` в `.env.compose`, файлы `ops/env/*.env.example`
в одноимённые `.env`, а `ops/backup/pg_service.conf.example` в `pg_service.conf`.
Заполнить разные секреты dev/prod непосредственно на сервере/Dokploy:

- PostgreSQL: один пароль в Compose, URL API/worker и `pg_service.conf`.
  В URL пароль должен быть percent-encoded. В `pg_service.conf` — исходный пароль.
- API: `FITCHECK_AUTH_SECRET` — 64 случайных hex-символа, `FITCHECK_OPS_TOKEN` —
  отдельный случайный секрет от 32 символов. В `ops/secrets/ops_token` записать
  тот же ops-токен без префикса Bearer. Каталог secrets — 0700; файл токена — 0644,
  чтобы непривилегированный Prometheus мог читать примонтированный файл.
- Только worker получает `OPEN_AI_KEY`; API и сайт работают без ключа провайдера.
- В API указать точные HTTPS origins и URL сайта, в сайте — URL внутреннего API
  и тот же публичный origin. Cookie/bearer передаёт серверный relay `/api/backend`.
  Настроить SMTP по `backend/.env.example`; ключи не передавать build arguments.
- `FITCHECK_RELEASE` — уникальный тег релиза (например, полный git SHA).
  Один тег не переиспользовать. Сохранить предыдущий тег для отката.

```sh
docker compose --env-file .env.compose -f compose.yaml -f compose.prod.yaml build
docker compose --env-file .env.compose -f compose.yaml -f compose.prod.yaml --profile operations up -d --no-build --wait
```

Миграция обязана завершиться с кодом 0; API/worker стартуют после неё. Проверка
готовности API проверяет БД и ревизию, worker — свежесть heartbeat. PostgreSQL
и worker не публикуют порты хоста. Сайт и Prometheus слушают только loopback.
Для изолированной проверки без рабочих секретов: `python3 ops/smoke.py`.
Она собирает все образы, проверяет readiness, сайт, метрики, правила Prometheus,
копию/восстановленные строки, отказ на повреждённом архиве, dry-run и рестарт worker.
Удаляются только случайно названный тестовый проект и его тома.

## Dokploy, TLS и прокси

Подключить домен к порту сайта 3000 через HTTPS Traefik/Dokploy, HTTP перенаправлять
на HTTPS. Для раздельного API-приложения использовать HTTPS и точные allowed origins.
На внешнем ingress закрыть `/internal/` и не публиковать worker:9109, Prometheus:9090
и PostgreSQL:5432. Prometheus обращается к API по внутренней сети с bearer-токеном.
Прокси должен сохранять Host/Origin и forwarding headers, отключать кеширование
`/api/backend/`, `/v1/` и `/internal/`, ограничивать тело запроса (импорт до 5 MiB)
и давать приложению завершить запросы. Не включать логирование Authorization,
cookies, query string, тел запросов/ответов и переменных окружения.

В существующих отдельных приложениях Dokploy: сначала однократный migration job
тем же образом/ревизией и с той же БД, затем API и worker, затем сайт. Worker stop
timeout должен быть не меньше 140 секунд (drain 130, lease минимум 150). API и
сайту дать 30 секунд. Нельзя запускать миграции одновременно в каждом процессе.
Тома PostgreSQL, бэкапов и состояния операций должны быть постоянными; API получает
состояние операций read-only. Для отдельных хостов потребуется общая доставка
метрик состояния копий, локальный Docker volume между хостами не разделяется.

## Выпуск и откат

1. CI должен пройти: unit/contract, PostgreSQL ownership/concurrency/recovery,
   schema/OpenAPI/TS drift, frontend tests/types/lint/build, browser E2E и ops smoke.
   Сборка использует `uv.lock`/`pnpm-lock.yaml`. Отсутствующая тестовая БД — ошибка.
2. Собрать новый уникальный тег; сохранить предыдущие образы и настройки.
   Сделать свежую копию и выполнить `restore-check` до изменения схемы.
3. Кратковременно закрыть новый приём задач на ingress. Остановить сайт/API/worker
   с указанными таймаутами. Принятые задания остаются в PostgreSQL.
4. Запустить миграцию отдельно: `docker compose ... run --rm --no-deps migrate`.
   Здесь и ниже `...` означает те же `--env-file` и `-f`, что при первом запуске.
   Не продолжать после ненулевого кода. Не удалять том PostgreSQL.
5. `docker compose ... up -d --no-build --force-recreate --wait api worker website`.
   Проверить readiness, открыть приём, выполнить release smoke ниже.

Новые миграции сначала должны расширять схему и поддерживать текущий и предыдущий
API/worker; переименования/удаления — отдельным последующим релизом. Клиент API
обновляется после API, новые поля должны быть совместимы с предыдущим клиентом.
Если новая схема не поддерживается предыдущим кодом, обычный откат запрещён:
требуется исправление вперёд или отдельное восстановление данных с согласованным RPO.
При совместимом откате закрыть приём, остановить приложения, вернуть предыдущий
тег и пересоздать их. Автоматический downgrade схемы не выполнять. Проверка схемы
fail-closed: старый образ с неизвестной новой ревизией может не стать ready;
проверять эту комбинацию на staging до релиза, иначе использовать исправление вперёд.

## Копии и восстановление

```sh
docker compose ... exec -T backup sh /ops/backup.sh backup
docker compose ... exec -T backup sh /ops/backup.sh restore-check fitcheck-YYYYMMDDTHHMMSSZ-PID.dump
```

`backup` делает consistent custom-format pg_dump, проверяет читаемость и SHA-256,
только затем обновляет timestamp успеха. `restore-check` проверяет checksum и
восстанавливает в **новую** БД `fitcheck_restore_check_*`: проверяет Alembic,
валидность constraints, trigger удаления владельца и доступность основных таблиц.
Тестовая БД удаляется после проверки. Рабочая БД не перезаписывается. Restore-роль
нуждается в CREATEDB и правах удаления собственных тестовых БД. После аварийного
SIGKILL проверить и вручную удалить только оставшиеся `fitcheck_restore_check_*`.
Локальная проверка подтверждает восстановление схемы; smoke дополнительно проверяет
сохранение конкретной строки. Для реальных данных периодически сверять агрегаты
и выборочные обезличенные контрольные суммы на изолированном сервере.

Хранение: 14 дней, минимум 7 (`FITCHECK_BACKUP_RETENTION_DAYS`); удаление старых
копий разрешено только после успешной копии за последние 24 часа. Цель локального
RPO — 24 часа, еженедельная проверка восстановления; время восстановления измерить
на объёме production. Время не проверялось на рабочем объёме.

Для восстановления сервиса после потери данных: закрыть приём/остановить worker,
проверить checksum, восстановить архив в новую БД на отдельном сервере, запустить
проверку SQL, сверить ревизию с образом, переключить DATABASE_URL и лишь затем
прогнать smoke. Старую БД оставить для разбора; не накатывать pg_restore поверх неё.

После выдачи S3: отдельная роль только на префикс бэкапов, TLS, шифрование на стороне
хранилища, versioning и lifecycle не короче локального retention; upload только
завершённых `.dump` + `.sha256`. Проверять восстановление **скачанной** копии на
отдельном сервере. Секреты/endpoint и автоматическую отправку ещё предстоит настроить.
Удалённые персональные данные могут оставаться в зашифрованных копиях до окончания
retention; доступ ограничить, перед открытием восстановленной БД повторить удаления
за период после снимка, используя отдельный защищённый журнал удаления.

## Метрики и alerts

Prometheus: `http://127.0.0.1:9090` через SSH tunnel. API `/internal/operations/metrics`
по умолчанию закрыт и без правильного токена возвращает 404. Метрики агрегатные:
очередь/lag, failed jobs за час, просроченные leases, дневные UTC provider p95/cost и
unknown cost, отказы admission, HTTP counters и timestamps копий/восстановления.
HTTP counters обнуляются при рестарте, несколько API-реплик нужно scrape отдельно.
Worker предоставляет приватный `/metrics` с heartbeat health.

Пороги в `ops/monitoring/alerts.yml`: недоступность 2 минуты, lag 180 секунд,
просроченные leases 5 минут, 5 failed jobs/час, дневной p95 >60 секунд,
>10 отказов/10 минут, записанные расходы >10 USD/сутки, unknown cost,
нет копии 26 часов или restore-check 8 суток. Пороги расходов адаптировать к бюджету;
стоимость с unknown calls неполна и требует сверки с биллингом провайдера.

Подготовлен `alertmanager.yml.example`. После выбора канала заменить URL, подключить
Alertmanager в приватной сети и добавить в Prometheus:

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]
```

Проверить конфиг `promtool check config`, правила `promtool check rules`, затем
тестовый alert и resolved до реального получателя. Секрет webhook хранить вне git.
Без этой проверки доставка оповещений не считается подключённой.

При alert: API/БД — readiness, место на диске и подключения; worker/lease/lag —
heartbeat, JSON job logs, доступность провайдера. Не удалять принятые jobs и
reservations вручную. Ошибки/расходы — сверить ledger и биллинг; не повышать лимиты
автоматически. Stale backup/restore — проверить доступ к БД, место и роль CREATEDB,
выполнить ручной backup/restore-check, убедиться в обновлении timestamp.

## Логи, retention и release smoke

JSON-логи допускают только технические поля: event, request_id, job_id,
псевдоним owner_ref, шаблон маршрута, статус, длительность и исход worker.
Произвольные сообщения/исключения не выводятся. API связывает request и job;
worker связывается через job_id. owner_ref имеет область своего процесса/компонента.
Тела, prompts, профили, email, пароли, cookies и токены не логируются. Docker логи
ограничены 5×10 MiB на сервис, Prometheus хранит 30 дней. Централизованное хранилище
логов пока не подключено.

```sh
docker compose ... --profile maintenance run --rm maintenance
docker compose ... --profile maintenance run --rm maintenance /app/.venv/bin/python -m fitcheck_backend.operations cleanup --execute --limit 100
```

По умолчанию dry-run. После проверки копии и dry-run можно настроить отдельное
ежедневное задание Dokploy с `--execute --limit 100`; повторять ограниченными пачками
до опустошения backlog. Автоматическое удаление в рабочем окружении не включено.
Удаляются: непривязанные гости через 30 дней после expiry (со связанными данными),
expired/revoked sessions и consumed/expired tokens старше 7 дней, terminal jobs
старше 30 дней, анонимный завершённый provider ledger старше 90 дней. История
аккаунта сохраняется после удаления terminal jobs. Активные jobs, незавершённые
резервы/вызовы провайдера и claimed guests защищены. Один запуск ограничен 100
строками каждой категории; блокировки сериализуют операции с claim/admission.

Release smoke на staging с тестовыми аккаунтами: demo анализ → регистрация/verify →
claim результата → перезагрузка → второй браузер видит историю/статус; чужой аккаунт
получает 404. Принять job, перезапустить worker, дождаться завершения/lease recovery
без потери принятого задания или двойной публикации. Автоматические browser E2E
используют настоящую БД/API и детерминированный executor без платного LLM;
PostgreSQL recovery/concurrency тесты проверяют рестарт и fencing. После выпуска
нужен короткий ручной smoke с реальным провайдером и SMTP.


## Проверка доставки продуктовой аналитики (ANY-735)

Целевое окружение этой задачи — **development в Dokploy**. Статус deployment,
зелёный healthcheck и HTTP 202 сами по себе не подтверждают запись аналитики.
Сначала проверьте process env сайта, API, worker и процесса отчёта. Выводите только
наличие секретов и булевы результаты сравнения, никогда `env`, значения ключей,
cookie, пароль БД или тела событий. Сайт: HTTPS `METRICS_BACKEND_URL`, непустые
`METRICS_BRIDGE_KEY` и отдельный `METRICS_COOKIE_SECRET`, точный публичный origin
в `ALLOWED_ORIGINS`, `METRICS_ENVIRONMENT=development`. API: совпадающий ingest key,
включённый сбор и то же metrics environment. Worker: включённый сбор и то же
metrics environment. API/worker/report: независимый
`FITCHECK_METRICS_DATABASE_ENVIRONMENT=development`; это область исторических
доменов, а не переключатель среды событий. Проверяйте схему packaged migrations.

Приватный `/internal/operations/metrics` с существующим Bearer ops token показывает:

- `fitcheck_metrics_enabled`, `fitcheck_metrics_collector_configured`,
  `fitcheck_metrics_lifecycle_configured`, `fitcheck_metrics_database_scope_configured`:
  настройки, а не обещание доступности сети/БД. Lifecycle не требует bridge key.
- `fitcheck_metrics_collector_requests_total{operation,status}`: `events`, `attempts`,
  `delete`; 400/413 — контракт/размер, 401 — ключ, 403 — Origin, 429 — лимит,
  503 — отключённый/неготовый collector или БД. Дедупликацию проверять в БД,
  число HTTP-запросов не равно числу сохранённых событий.
- `fitcheck_metrics_journal_events{source,environment}`: текущие сохранённые строки,
  уменьшаются при retention/удалении. `journal_observed=0` означает отсутствие
  сохранённых наблюдений, а не доказанный нулевой продуктовый трафик.
  `journal_latest_received_timestamp_seconds` существует только при наличии строк.
  `website_server` здесь означает journal-факты, а не число provider attempts.

Счётчики process-local: после restart сбрасываются, реплики scrape отдельно.
При ошибке БД endpoint сохраняет конфигурационные gauges и counters в ответе 200
вместе с `fitcheck_database_up 0`, не выдавая недоступные DB-измерения за ноль.
Prometheus продолжает собирать независимые от БД показатели. Alert недоступности
API проверяет как `up`, так и `fitcheck_database_up`; это exporter, не readiness.

Website server logs: `fitcheck_metrics_bridge` с фиксированными operation/outcome
и HTTP status. Причины: `missing_configuration`, `invalid_destination`,
`body_too_large`, `collector_rejected`, `unconfirmed`, `timeout`, `network_error`;
`delivered` требует HTTP 200 и JSON receipt коллектора: accepted + duplicates
равно размеру batch либо неотрицательный deleted для удаления. HTML, пустой 204,
некорректный receipt и ответ collector 202 считаются неподтверждёнными. Нет URL, ключей, текстов исключений или идентификаторов
посетителей. `fitcheck_metrics_relay` / `cookie_unconfigured` означает отсутствие
cookie secret. Проверяйте фактическую запись в отдельной транзакции даже при
`delivered:true`.

В DevTools Console браузера фильтруйте `fitcheck_metrics_client_loss`. После drain
там доступны накопленные `failed` (исчерпаны три попытки) и `dropped` (переполнение
очереди/размера). Это локальные счётчики вкладки, они не передаются автоматически
на сервер и не дают глобального процента потерь. Закрытие вкладки до drain,
блокировщик и отключённая телеметрия могут оставить потери ненаблюдаемыми. Ошибки
диагностики не прерывают продуктовые операции. Постоянной outbox нет.

Smoke-проверка без платных LLM-вызовов:

1. Запишите commit/image сайта/API/worker, UTC начало и обезличенные результаты
   проверки конфигурации. Откройте сайт новым тестовым браузером, выполните обычное
   неплатное действие. В Network выберите POST `/api/metrics`, запишите только
   контрольный eventId и occurredAt. Сохраните состояние `delivered`, не cookie.
2. Через доступный оператору SQL runner выполните запрос ниже **в отдельной
   read-only транзакции**. Подставляйте только контрольный UUID; ожидается одна
   строка нужных source/environment/subject_kind после commit. Не выводите
   `properties`, cookie или пользовательские тексты.
3. Повторите тот же POST с теми же eventId/временем и той же cookie в этом браузере.
   Collector при прямой проверке отвечает accepted=0, duplicates=1; relay —
   delivered=true. SQL count должен остаться 1. Смена visitor между повторами
   меняет payload и должна дать conflict, это другой сценарий.
4. Выполните штатную неплатную серверную операцию тестового аккаунта (например,
   сохранение профиля), сверив соответствующий backend_server domain key и время.
   Worker проверяйте на существующей job или с заглушкой LLM в изолированной
   тестовой среде; не создавайте job с платным provider ради smoke.
5. Проверки неверного ключа, collector outage и отключения выполняйте на
   изолированной копии; не выключайте используемый development для теста.
   Убедитесь, что основной продукт продолжает работать, а failed растёт после
   исчерпания повторов, и что queue overflow увеличивает dropped.
6. Запустите существующий CLI report с явными start/end/environment/population
   после commit. Сверяйте coverage/data start, а не только значения. Отсутствие
   источника, неполную историю и период простоя фиксируйте как неизвестное покрытие.
   Ретроспективные просмотры не создавать; backfill — только восстанавливаемые
   серверные факты с явным происхождением. Исправление формул относится к ANY-738.

```sql
BEGIN READ ONLY;
SELECT event_id, name, source, environment, subject_kind, occurred_at, received_at
FROM metric_journal
WHERE event_id = '73500000-0000-4000-8000-000000000001';
SELECT count(*) AS persisted_once
FROM metric_journal
WHERE event_id = '73500000-0000-4000-8000-000000000001';
SELECT source, environment, started_at, available_from, retention_floor
FROM metric_collections WHERE environment = 'development';
COMMIT;
```

Контрольные UUID в примере — шаблон; используйте фактически отправленный eventId.
Не удаляйте чужие события для очистки smoke. Синтетические действия явно укажите
в evidence, чтобы не считать их реальным пользовательским спросом.
