# FitCheck Backend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Завершить ANY-643: запускаемый самостоятельный API FitCheck, проверяемый OpenAPI и клиент без переключения существующего UI.

**Architecture:** Python-пакет `fitcheck_backend` в `backend/` содержит app factory и строгие DTO. Полный экспорт объединяет работающие health routes с запланированными бизнес-операциями; последние не регистрируются в runtime. TypeScript transport использует сгенерированные типы.

**Tech Stack:** Python 3.12+, uv, FastAPI, Pydantic 2, uvicorn, pytest/httpx; TypeScript, openapi-typescript, Vitest, pnpm, GitHub Actions. Версии зависимостей фиксируются lockfiles при реализации.

**Spec:** `docs/superpowers/specs/2026-10-11-fitcheck-backend-foundation-design.md` (одобрено пользователем 2026-10-11).

## Global Constraints

- FitCheck — отдельный сервис в текущем репозитории; никаких импортов, БД, identity или runtime `anytoolai-platform`.
- Python 3.12+, uv и зафиксированный lockfile; БД/SQLAlchemy/Alembic — ANY-644, worker — ANY-649.
- Бизнес-маршруты `/v1`, camelCase JSON, locale `en`/`ru`; `desiredMonthlyIncome` отсутствует.
- Live OpenAPI содержит только реализованные routes; полный контракт отмечает будущие операции `x-fitcheck-implementation: planned` с задачей-владельцем.
- Ошибки содержат только безопасные code/message/requestId/details; сервер генерирует `X-Request-ID`.
- CORS разрешает точные настроенные origins; wildcard запрещён. Auth/CSRF описываются в контракте, реализуются в ANY-645.
- Health возвращает `stage: foundation`; запуск и генерация не требуют БД, provider keys или чтения `.env.local`.
- WebsiteRepository, ExtensionRuntime, Next.js `/api/*` и действующий Dokploy не переключаются в ANY-643.
- До кода прочитать применимые локальные Next.js guides согласно AGENTS.md; использовать isolated workspace по using-git-worktrees при исполнении.

## Review Focus

- Потоковое тело без Content-Length или с ложным значением: фактический лимит применяется до передачи body handler (Task 2).
- NaN/Infinity, bool вместо числа, неизвестные поля и null вместо optional: публичные DTO отклоняют их (Task 3).
- Разрешённый extension origin и чужой origin, в том числе preflight: точное сравнение без wildcard (Task 2).
- Ошибка handler с секретом и клиентский X-Request-ID: наружу выходит безопасная ошибка с новым серверным ID (Task 2).
- AbortSignal, malformed JSON и ошибочный success payload: клиент сохраняет отмену и выдаёт предсказуемую transport error (Task 4).

---

## Карта файлов

`backend/src/fitcheck_backend/config.py` — настройки; `__main__.py` — CLI; `api/app.py` — сборка приложения; `api/health.py` — health; `api/errors.py` — DTO/handlers ошибок; `api/middleware.py` — request ID и лимит тела. `contracts/domain.py` — текущие domain DTO; `contracts/resources.py` — новые resources; `contracts/jobs.py` — discriminated unions; `contracts/operations.py` — декларативный каталог planned routes; `contracts/openapi.py` — полный экспорт. `backend/scripts/export_openapi.py` — CLI экспорта/check. Каждый пакет получает `__init__.py`.

`contracts/fitcheck.openapi.json` — committed artifact; `lib/backend/generated/schema.ts` — generated artifact; `lib/backend/client.ts` — transport; `scripts/generate-backend-types.mjs` — generation/check. Тесты рядом с TS-клиентом и в `backend/tests/`. `backend/README.md`, `backend/.env.example`, `docs/architecture/adr-001-standalone-backend.md` объясняют запуск, архитектуру и миграцию. `package.json`, `pnpm-lock.yaml`, `.github/workflows/ci.yml`, `.gitignore` изменяются только для инструментов и проверок foundation.

### Task 1: Самостоятельное приложение и настройки

**Files:** Create `backend/pyproject.toml`, `backend/uv.lock`, `backend/src/fitcheck_backend/{__init__.py,__main__.py,config.py}`, `backend/src/fitcheck_backend/api/{__init__.py,app.py,health.py}`, `backend/tests/test_foundation.py`, `backend/.env.example`, `backend/README.md`, `docs/architecture/adr-001-standalone-backend.md`; modify `.gitignore`.

**Interfaces:** Produces `Settings` (Pydantic settings, env prefix `FITCHECK_`), `create_app(settings: Settings | None = None) -> FastAPI`, `main() -> None`; `/health/live` и `/health/ready` возвращают `{status: "ok", stage: "foundation"}`.

- [x] **Step 1: Написать failing tests запуска и настроек.** `test_health_without_database_or_provider_secrets` проверяет 200 и точный health JSON, `test_invalid_settings` параметризует port 0/65536, body limit 0, неизвестные ENV/LOG_LEVEL и wildcard origins. `test_defaults` проверяет env dev, host 127.0.0.1, port 8000, log info, body limit 1_048_576 и пустой список origins. `test_explicit_settings_override_environment` проверяет app factory с переданным Settings. Настроить только test harness/pyproject, необходимые для запуска этих тестов.
- [x] **Step 2: Запустить `cd backend && uv run pytest tests/test_foundation.py -q`.** Ожидается ошибка отсутствующего package/app, а не проблемы установки test runner.
- [x] **Step 3: Реализовать интерфейсы.** ENV `dev/test/production`, LOG_LEVEL `debug/info/warning/error/critical`, port 1–65535, body limit 1–16_777_216; origins — JSON array точных http(s)/chrome-extension origins без path/query/userinfo/wildcard. Settings не загружает dotenv автоматически. CLI вызывает uvicorn с указанными host/port/log level. README показывает `uv sync --locked`, `uv run python -m fitcheck_backend` и передачу env; ADR переносит утверждённые границы и порядок ANY-644–654. Игнорировать `.venv`, `__pycache__`, `.pytest_cache`.
- [x] **Step 4: Повторить тесты и smoke CLI.** `uv run python -m fitcheck_backend` + отдельный HTTP GET обоих health подтверждают запуск; остановить свой процесс. Проверить отсутствие зависимости от эталонного проекта.
- [x] **Step 5: Commit** `feat(backend): add standalone FitCheck API foundation` (только файлы Task 1).

### Task 2: HTTP boundary, CORS и безопасные ошибки

**Files:** Create `backend/src/fitcheck_backend/api/errors.py`, `backend/src/fitcheck_backend/api/middleware.py`, `backend/tests/test_http_boundary.py`; modify `api/app.py`, README.

**Interfaces:** Consumes Task 1 `Settings/create_app`; produces `ErrorDetail(location: list[str | int], code: str)`, `ErrorEnvelope`, `ApiError(status_code: int, code: str, message: str)`, `install_error_handlers(app: FastAPI) -> None`, `RequestBoundaryMiddleware(app, max_body_bytes: int)`.

- [x] **Step 1: Написать failing tests границы HTTP.** Тестовые handlers добавляются только в тестах: `test_validation_is_400_and_redacted` посылает пароль в невалидном DTO и проверяет отсутствие input/пароля; `test_unhandled_error_is_safe` бросает exception с секретом и проверяет 500 `internal_error`, без traceback/секрета. `test_404_405_share_envelope` проверяет codes `not_found`/`method_not_allowed`, requestId совпадает с header; Allow сохраняется при 405. `test_request_id_cannot_be_spoofed` передаёт свой ID и получает другой валидный UUID. Проверить точный approved/foreign origin для обычного запроса и OPTIONS, extension origin, allow-headers Content-Type/Authorization/X-CSRF-Token/Idempotency-Key, exposed X-Request-ID. `test_actual_body_limit` через ASGI receive проверяет 413 на превышении, включая несколько chunks без Content-Length и ложный Content-Length; ровно limit разрешён. Неподдерживаемый content type JSON endpoint → 415, malformed JSON → 400.
- [x] **Step 2: Запустить `cd backend && uv run pytest tests/test_http_boundary.py -q`.** Убедиться в красных assertions конкретных HTTP требований.
- [x] **Step 3: Реализовать handlers/middleware.** Envelope `{error:{code,message,requestId,details:[]}}`; validation details только location/code. Лимит проверять по фактическим bytes, не полагаться на Content-Length. Request ID доступен в request state и логах, включая 500. CORS — явные methods GET/POST/PUT/DELETE/OPTIONS и headers из теста; credentials только для настроенных http(s) web origins, extension bearer flow без credentials. Логировать requestId/method/path/status без body, query, tokens или exception text. Не добавлять runtime auth или CSRF-заглушки.
- [x] **Step 4: Запустить `cd backend && uv run pytest tests/test_foundation.py tests/test_http_boundary.py -q`.** Все pass; проверить CORS headers также на безопасном 500.
- [x] **Step 5: Commit** `feat(backend): enforce safe HTTP boundaries`.

### Task 3: DTO и полный OpenAPI-контракт

**Files:** Create `backend/src/fitcheck_backend/contracts/{__init__.py,domain.py,resources.py,jobs.py,operations.py,openapi.py}`, `backend/scripts/export_openapi.py`, `backend/tests/test_contracts.py`, `backend/tests/test_openapi.py`, `backend/tests/fixtures/domain.json`, `contracts/fitcheck.openapi.json`; modify README.

**Interfaces:** Produces `FreelancerProfile`, `Vacancy`, `FitAnalysis`, `ProfileResource`, `Preferences`, `DraftResource`, `AnalysisResource`, `HistoryPage`, `JobReference`, `JobState`, `ImportState`, `OperationSpec`, `PLANNED_OPERATIONS`, `export_openapi(app: FastAPI) -> dict`. DTO use Python snake_case names with camelCase aliases, JSON serialization by alias. Error models берутся из Task 2. Export CLI: `uv run python scripts/export_openapi.py [--check]`, artifact path разрешается от script location.

- [x] **Step 1: Написать failing DTO tests.** Fixtures из текущих `lib/analysis/schema.ts`, `lib/types.ts`, `lib/skill-suggestions/schema.ts` принимаются без income; boundary tests сверяют точные min/max, enum и optional поля из этих файлов. Проверить unknown fields, NaN/Infinity/bool, null optional fields, score fractional, duplicate workFormats, foreign/mixed-case skillLevels keys. Для jobs проверить четыре состояния отдельно для analysis/suggestions, analysis success только analysisId, suggestions success только skills ≤10, failure только безопасный error. Profile resource `{revision,profile}`, PUT `{expectedRevision,profile}`; authenticated analysis `{vacancy,profileRevision,locale}` и guest `{vacancy,profile,locale}` разделены discriminator `mode: account|guest`, account не принимает profile/userId/memory.
- [x] **Step 2: Запустить `cd backend && uv run pytest tests/test_contracts.py -q`.** Подтвердить ожидаемый red.
- [x] **Step 3: Реализовать domain/resources/jobs DTO.** Строгие числа, finite floats, trimmed strings, extra forbid, optional отсутствуют при сериализации; явно очищаемые draft/feedback nullable. History хранит snapshot profile/revision/vacancy/locale плюс версии prompt/schema/policy; immutable metadata объявлена readOnly. Курсорная выдача `{items,nextCursor,hasMore}`, limit 1–100. Application status `not_applied/applied/replied/interview/rejected/hired`, default `not_applied`; feedback correctedScore 0–100, note ≤500. Draft — vacancy + locale. Preferences — locale; credentials/email/PKCE поля ограничить и описать без хранения/проверки аккаунтов. Import принимает versioned legacy payload, где income допустим только как игнорируемое legacy поле, без passwords/tokens.
- [x] **Step 4: Написать failing OpenAPI tests.** Все строки таблицы операций spec (все методы, включая GET/PUT/DELETE) присутствуют с уникальными operationId, request/response DTO и ссылкой `x-fitcheck-owner-task`. Health implemented, остальные planned. Live app не содержит `/v1/*`: GET →404, прочие отсутствующие paths не дают успешный ответ. Полный artifact валиден OpenAPI 3.1, refs разрешаются, errors на всех предусмотренных statuses; runtime health schema совпадает с exported health. Export не читает `.env.local`, детерминирован и `--check` отклоняет изменённый artifact.
- [x] **Step 5: Реализовать каталог и exporter.** Каталог строго соответствует таблице spec; бизнес handlers не создаются. Auth cookie/CSRF, bearer extension, guest cookie описать security schemes и extensions требований Origin/CSRF/PKCE, не делать bearer обязательным для web cookie flow. 202 JobReference для starts, 204 для удаления/выхода, 200 для чтения/обновления, 201 регистрации/guest session. Idempotency-Key для starts/reanalysis/claim/import; history filter enum и nullable nextCursor. POST extraction разделяет URL/text input. Include все error codes/statuses spec и existing service errors через каталог mapping в contracts (runtime adapters — владельцам переноса). Экспорт соединяет live schema и DTO/catalog, stable sorted JSON с trailing newline; CI check не перезаписывает artifact.
- [x] **Step 6: Запустить `cd backend && uv run pytest tests/test_contracts.py tests/test_openapi.py -q` и export + check.** Убедиться, что нет secret values и income в новых DTO (только legacy import).
- [x] **Step 7: Commit** `feat(backend): publish versioned FitCheck API contracts`.

### Task 4: Generated TypeScript и transport

**Files:** Create `scripts/generate-backend-types.mjs`, `lib/backend/generated/schema.ts`, `lib/backend/client.ts`, `lib/backend/client.test.ts`; modify `package.json`, `pnpm-lock.yaml`, README.

**Interfaces:** Consumes artifact Task 3. Produces generated `paths/components/operations`; `createBackendClient({baseUrl,fetch?,credentials?})` returning `request<T>(path: string, options: {method?: string; body?: unknown; signal?: AbortSignal; headers?: HeadersInit; validate: (value: unknown) => T}): Promise<T>`; `BackendApiError` carries status/code/requestId, `BackendTransportError` carries stable reason. No arbitrary generic cast replaces success validation.

- [x] **Step 1: Написать failing Vitest tests.** `test_json_success_is_validated`, `test_204`, `test_api_error`, `test_malformed_error_is_transport_failure`, `test_malformed_success_json`, `test_invalid_success_payload`, `test_abort_is_preserved`, `test_base_url_join`, `test_credentials_and_headers`. Проверять exact JSON envelope из Task 2, header fallback requestId, пустой body 204 передаётся validator как undefined, AbortError сохраняется; caller JSON headers не теряются, body JSON.stringify. Cookies по умолчанию same-origin; extension caller задаёт omit и Authorization. Клиент не повторяет mutations автоматически.
- [x] **Step 2: Запустить `pnpm exec vitest run lib/backend/client.test.ts`.** Убедиться в ожидаемом red.
- [x] **Step 3: Добавить pinned openapi-typescript dev dependency и generator.** Scripts `backend:types` и `backend:types:check`; check генерирует в памяти и сравнивает с artifact без перезаписи. Реализовать transport согласно интерфейсу; baseUrl включает `/backend/v1` либо origin + `/v1`, route path относительный, чужой абсолютный URL запрещён. Не импортировать клиент в текущие UI/adapters.
- [x] **Step 4: Запустить generation/check, targeted tests и `pnpm typecheck`.** Добавить type-only compile assertions, что profile optional currency не становится nullable, income отсутствует, JobState — tagged union. Это тест generation, без handwritten copies DTO.
- [x] **Step 5: Commit** `feat(backend): add generated TypeScript API transport`.

### Task 5: CI и итоговая проверка foundation

**Files:** Modify `.github/workflows/ci.yml`, `backend/README.md`, ADR; tests предыдущих tasks.

**Interfaces:** CI backend job uses Python 3.12 + pinned setup-uv action/version, `uv sync --locked`, `uv run pytest`, export `--check`; web verify job adds `pnpm backend:types:check` after frozen install. Existing test/typecheck/lint/Webpack web build/extension build сохранены.

- [x] **Step 1: Добавить CI jobs/checks и закончить runbook.** Runbook фиксирует env format/defaults, startup, health смысл, regeneration commands, implemented/planned отличие, будущую ownership/auth и задачи-владельцы, отсутствие подключения Dokploy. ADR перечисляет принятые решения и этапы переноса без обещания работающего auth/storage.
- [x] **Step 2: Запустить `cd backend && uv sync --locked && uv run pytest -q && uv run python scripts/export_openapi.py --check`.** Все backend tests pass, artifact unchanged.
- [x] **Step 3: Запустить `pnpm backend:types:check`, `pnpm test`, `pnpm typecheck`, `pnpm lint`, `pnpm exec next build --webpack`, `pnpm build:extension`, `git diff --check`.** Все команды успешны; optional live provider skips допустимы с явным указанием. При network/sandbox failure запросить нужную escalation, не считать проверку пройденной.
- [x] **Step 4: Проверить итоговый diff и независимую review по execution skill.** Нет platform dependencies, переключения UI/старых routes, credentials или успешных planned handlers; unresolved review findings исправить и перепроверить затронутое.
- [x] **Step 5: Commit** `ci(backend): verify API contract and generated client drift`; обновить ANY-643 результатом/проверками, state Done только после выполнения критериев. Интеграцию branch выбирать через finishing-a-development-branch; deploy не входит в эту задачу.

## Самопроверка плана

Требования spec покрыты: standalone/ADR/settings/health — Task 1; HTTP/errors/CORS/limits — Task 2; DTO, operations, security documentation, jobs/idempotency/history/import contract — Task 3; generation/transport — Task 4; drift/CI/runbook/verification — Task 5. Runtime auth, DB, jobs и миграция клиентов остаются владельцам ANY-644–654. Пять Review Focus условий закреплены тестами Task 2–4. Общие интерфейсы и названия экспортов согласованы между задачами.


## Результат исполнения

Реализовано в ветке `feat/any-643-backend` от `dev` (base e22a31a). Независимый review gpt-6-astra нашёл default-null сериализацию и отсутствие CLI request logging; четыре регрессионных теста сначала воспроизвели ошибки, затем прошли после исправления. Добавлено отображение legacy `fetch_failed` → 502. Остальных отложенных замечаний нет.

Проверки: backend 99 passed; frontend 316 passed, 3 optional live provider skipped; OpenAPI/TypeScript drift, typecheck, ESLint, Next.js Webpack и WXT production builds — успешны. Git integration выбирает пользователь; удалённая публикация/deploy не выполнялись.

Решения при исполнении:
- Baseline проверялся через npm с установленными зависимостями; после добавления генератора pnpm установил отдельные зависимости рабочей копии. Цена ошибочного решения — повторная установка перед generation; итоговая установка выполнена.
- `fetch_failed` переклассифицирован из Minor в Important: без него критерий совместимости ошибок оставался неполным. Цена ошибки — один документированный HTTP status; mapping исправлен.
- Runtime auth/ownership/CSRF/quota/jobs/storage/providers оставлены ANY-644–652: foundation содержит только контракты. Цена ошибки — нельзя переключать UI до выполнения этих задач.
- DNS/private-address проверки оставлены ANY-647: foundation не выполняет fetch. Цена ошибки — извлечение должно проверить destination security до подключения.
- UI/proxy/Dokploy readiness оставлены ANY-653/654. Цена ошибки — deployment ждёт integration checks.
- Upload timeouts и общий memory budget оставлены server/deployment policy ANY-654; здесь работает per-request byte limit. Цена ошибки — operational limits нужны до публичного запуска API.
