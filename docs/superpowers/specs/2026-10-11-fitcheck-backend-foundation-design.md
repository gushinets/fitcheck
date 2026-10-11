# ANY-643: отдельный backend FitCheck

Дата: 2026-10-11. Статус: одобрено пользователем и реализовано в ветке feat/any-643-backend.

## Назначение и принятое направление

FitCheck получает собственный backend в текущем репозитории. Пользователь явно исключил подключение к `anytoolai-platform`; этот проект служит архитектурным эталоном. Backend не импортирует его пакеты, не использует его БД, identity, quota или runtime и не требует его запуска.

Цель ANY-643 — создать запускаемый каркас API и единые проверяемые контракты для последующих backend-задач. Это не реализация всех операций, перечисленных в контракте. Существующие web, расширение и Next.js API продолжают работать до интеграции ANY-653.

## Выбор устройства сервиса

Выбран модульный Python backend в `backend/`: один пакет `fitcheck_backend`, два будущих процесса API и worker. API принимает и валидирует запросы, проверяет доступ и предоставляет данные. Worker выполняет платные LLM-вызовы и публикует результаты. Оба используют собственный PostgreSQL FitCheck через слой repositories/services.

Альтернативы: отдельный репозиторий усложняет согласованные изменения контрактов и клиентов; набор микросервисов добавляет сетевые зависимости и эксплуатационные расходы до появления такой необходимости. Общая платформа исключена решением пользователя.

Ориентиры эталона: app factory FastAPI, разделение routers/services/storage/providers, Alembic, отдельный migration process, durable jobs с lease, OpenAPI export и проверка drift. Универсальный workflow kernel, product registry и DSL FitCheck не нужны.

## Размещение и границы

```text
backend/
  pyproject.toml
  uv.lock
  src/fitcheck_backend/
    api/             # create_app, routers, request context, errors
    config.py        # настройки процесса и проверка окружения
    contracts/       # Pydantic DTO и описание публичных операций
  tests/
  scripts/           # экспорт OpenAPI
contracts/
  fitcheck.openapi.json
lib/backend/
  generated/         # TypeScript-типы из OpenAPI, без ручных изменений
  client.ts          # transport, credentials, errors, AbortSignal
docs/architecture/
  adr-001-standalone-backend.md
```

Последующие задачи добавляют `storage`, `identity`, `profiles`, `extraction`, `analysis`, `jobs`, `history`, `quotas`, `imports` и entrypoint worker по мере реальной реализации. Зависимости идут от API/worker к application services, далее к repositories и provider gateway. Доменные правила не размещаются в HTTP handlers. Клиент не выбирает provider/model и не содержит prompts или секретов.

Backend: Python 3.12+, uv и зафиксированный lockfile, FastAPI/Pydantic. SQLAlchemy/PostgreSQL/Alembic добавляются в ANY-644; worker и очередь PostgreSQL — ANY-649. Подключение к реальной БД не требуется для запуска каркаса ANY-643.

## Результат именно ANY-643

1. ADR с отдельным сервисом, структурой, границами и этапами переноса.
2. FastAPI app factory и CLI/uvicorn entrypoint, локальный запуск и документированные настройки.
3. Рабочие `/health/live` и `/health/ready`, единый формат ошибок и серверный request ID.
4. Версионированный OpenAPI-контракт всех операций ниже, Pydantic DTO, экспорт без зависимости от БД и provider credentials.
5. Сгенерированные TypeScript-типы и небольшой HTTP-клиент с проверкой ошибок/ответов и отменой запросов.
6. Backend tests, CI проверки экспорта OpenAPI и TypeScript generation drift, инструкции запуска.

Будущие операции описываются в экспортируемом контракте с `x-fitcheck-implementation: planned` и ссылкой на владеющую задачу. Рабочие операции помечаются `implemented`. Live FastAPI OpenAPI описывает только зарегистрированные работающие маршруты; экспортированный полный контракт объединяет их с запланированными операциями. Планируемые операции не регистрируются как успешные заглушки, не создают данные в памяти и не выполняют фиктивный login. Клиент не подключается к ним из текущего UI до реализации.

## Контракты

Публичные бизнес-маршруты имеют префикс `/v1`. Web использует same-origin `/backend/v1`, который при интеграции проксируется на API `/v1`. Существующие `/api/extract`, `/api/analyze` и `/api/skill-suggestions` в ANY-643 не переключаются.

JSON сохраняет camelCase текущего frontend: `experienceYears`, `preferredRate`, `rateCurrency`, `skillLevels`, `fixedBudgetMax`, `strengthEvidence`. `desiredMonthlyIncome` отсутствует. Legacy-совместимость обеспечивается явно при импорте, а новые публичные запросы не принимают произвольные неизвестные поля.

Суммы: конечные неотрицательные числа с верхними пределами текущих Zod-схем; валюты USD/EUR/RUB, неизвестная валюта остаётся отсутствующей. Уровни primary/confident/basic; `skillLevels` ссылается только на нормализованные навыки профиля. Ограничения строк, массивов, URL, locale en/ru и score 0–100 соответствуют существующим контрактам. Для полей со значением «не указано» используется optional, для явно очищаемых ресурсов — null; они не взаимозаменяемы.

| Операция | Контракт | Владелец реализации |
|---|---|---|
| Регистрация/вход/выход | `POST /v1/auth/register`, `/login`, `/logout` | ANY-645 |
| Подтверждение/восстановление | `POST /v1/auth/verify-email`, `/password-reset/request`, `/password-reset/confirm` | ANY-645 |
| Текущий пользователь/удаление | `GET /v1/me`, `DELETE /v1/me` | ANY-645 |
| Вход расширения | `POST /v1/auth/extension/authorize`, `/token`, `/revoke` | ANY-645 |
| Профиль | `GET /v1/profile`, `PUT /v1/profile` с revision/expectedRevision | ANY-646 |
| Настройки | `GET /v1/preferences`, `PUT /v1/preferences` | ANY-646 |
| Черновик | `GET /v1/draft`, `PUT /v1/draft`, `DELETE /v1/draft` | ANY-646 |
| Извлечение URL/текста | `POST /v1/extractions` → редактируемые поля вакансии | ANY-647 |
| Подсказки навыков | `POST /v1/skill-suggestion-jobs` → 202 и job reference | ANY-648/649 |
| Запуск анализа | `POST /v1/analysis-jobs` → 202 и job reference | ANY-649 |
| Состояние job | `GET /v1/jobs/{jobId}` → tagged union состояния/типа | ANY-649 |
| Результат анализа | `GET /v1/analyses/{analysisId}` | ANY-650 |
| История | `GET /v1/history` с cursor/limit/verdict/applicationStatus | ANY-650 |
| Коррекция и статус отклика | `PUT /v1/analyses/{analysisId}/feedback`, `/application-status` | ANY-650 |
| Пересчёт | `POST /v1/analyses/{analysisId}/reanalyses` → новый job | ANY-650 |
| Удаление истории | `DELETE /v1/history` | ANY-650 |
| Гостевая сессия | `POST /v1/guest-sessions` | ANY-651 |
| Квоты | `GET /v1/quota` для текущей проверенной identity | ANY-651 |
| Перенос демо | `POST /v1/guest-claims` | ANY-651 |
| Импорт | `POST /v1/import-jobs`, `GET /v1/import-jobs/{importId}` | ANY-652 |

Профиль возвращает revision и profile; анализ сохраняет immutable snapshot этой revision, вакансии, locale и версий prompt/schema/policy. Authenticated analysis request содержит vacancy и profileRevision, а память калибровки и профиль читает сервер. Guest request может содержать временный профиль. Клиентское `userId` не является средством авторизации. Suggestions возвращаются через job как отдельный тип результата, не как FitAnalysis.

Jobs имеют `queued`, `running`, `succeeded`, `failed`; успешный analysis job содержит analysisId, успешный suggestions job — skills. Ошибки терминального job используют безопасный error DTO. `Idempotency-Key` предусмотрен для запуска jobs, reanalysis, claim и import; атомарная реализация принадлежит соответствующим задачам. Cursor pagination задаёт nextCursor и hasMore; неподтверждённые данные пользователя не подменяются guessed snapshots.

## Авторизация, CORS и CSRF

Web: серверная cookie-сессия, в production `__Host-fitcheck_session`, Secure, HttpOnly, Path=/ и SameSite=Lax, без Domain. Все изменения с cookie требуют проверенного Origin и CSRF token. HTTPS same-origin proxy сохраняет эти свойства. Local development использует отдельное имя cookie без `__Host-` и допускает HTTP только в dev.

Расширение: вход через браузерный web login и одноразовый code с PKCE S256; redirect разрешается только для настроенного extension ID. `authorize` требует web session, CSRF и явного действия пользователя. `token` проверяет code, verifier и redirect, выдаёт ограниченный по времени bearer token; lifecycle/rotation/revocation реализуются в ANY-645. Chrome storage не получает HttpOnly cookie или provider keys.

CORS: точный список web и extension origins из настроек, без wildcard и разрешения всех `chrome-extension://` origins. Credentials включаются только для cookie-flow; разрешённые методы и заголовки задаются явно. CORS не заменяет проверку identity/ownership. Protected endpoint не принимает guestId или userId как доказательство владения.

Guest cookie устанавливается сервером; успешный claim требует одновременно подтверждённую guest session и account session. Численные demo quotas, атомарное admission и rate limits реализуются в ANY-651.

## Ошибки и настройки

Форма ошибки: `{"error":{"code":"invalid_request","message":"Invalid request","requestId":"…","details":[]}}`. Details содержит только расположение поля и стабильный код, без rejected input, паролей, tokens, prompts и provider body. Сервер создаёт request ID сам, возвращает `X-Request-ID` и использует его в логах. Ответы 404/405 и ошибки валидации используют тот же формат.

HTTP семантика: 400 invalid request, 401 unauthenticated, 403 forbidden/CSRF/origin, 404 missing resource, 409 revision/idempotency conflict, 413 body too large, 415 unsupported content, 429 quota/rate limit, 502 upstream failure, 503 service unavailable, 504 timeout. Набор кодов переносит существующие extraction/analysis/suggestions errors через адаптер без потери локализованных сообщений. В исключениях наружу не попадают stack traces.

Настройки ANY-643: `FITCHECK_ENV`, `FITCHECK_HOST`, `FITCHECK_PORT`, `FITCHECK_ALLOWED_ORIGINS`, `FITCHECK_LOG_LEVEL`, `FITCHECK_API_BODY_MAX_BYTES`. Они имеют проверяемые пределы и безопасные dev defaults. Production не допускает wildcard origins. Database/session/provider secrets вводятся вместе с задачами-владельцами, не как неиспользуемые обязательные переменные. Provider credentials принадлежат worker; OpenAPI и TS generation не читают `.env.local` автоматически.

Liveness подтверждает работающий API процесс; readiness ANY-643 подтверждает загрузку settings/routes. Response явно содержит `stage: foundation`; он не утверждает готовность будущих auth/storage/LLM. ANY-644/649 расширяют readiness реальными зависимостями.

## Перенос и размещение в Dokploy

Порядок: ANY-643 contracts/API → ANY-644 schema → ANY-645 auth → ANY-646 profile; ANY-647 extraction и ANY-648 LLM могут идти после foundation; ANY-649 jobs зависит от DB/auth/profile/LLM; затем history/demo/import, ANY-653 clients и ANY-654 production validation.

API, worker, PostgreSQL и одноразовый migration process размещаются отдельно от Next.js. Dokploy application `fitcheck-dev` и его действующие ключи/домены в ANY-643 не изменяются. Общий proxy route `/backend/*` появляется вместе с подключением реального backend. При переключении существующих Next.js LLM routes их нужно отключить либо обеспечить ту же identity/quota policy, чтобы не сохранить обход новых ограничений.

В ANY-643 создаётся клиент, но текущие WebsiteRepository/ExtensionRuntime остаются на действующих adapters. Offline draft/cache, перенос IndexedDB/chrome.storage, account claim и восстановление данных на другом устройстве выполняются в ANY-652/653. Локальный пароль или email не подтверждают владение серверным аккаунтом.

## Проверка и завершение ANY-643

Обязательные проверки: settings valid/invalid, startup без БД/LLM credentials, health, CORS для разрешённого/чужого origin, единые безопасные validation/404/405/errors, отсутствие unimplemented routes в live API, полнота planned operations в exported contract, согласованность DTO ограничений с текущими fixtures, TS client cancellation/error parsing и regeneration drift.

CI запускает backend tests и export check, TS generation check, существующие npm test/typecheck/lint, web build через Webpack и extension build. Live provider calls для foundation не требуются. Success ANY-643 не означает завершение ANY-644–654.

Перед реализацией требуется проверка этого документа пользователем, затем отдельный план реализации. Сроки и дополнительные product features документ не добавляет.
