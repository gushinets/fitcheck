# ANY-644: отдельное хранилище FitCheck

Дата: 2026-10-11. Статус: согласовано пользователем, включая сроки хранения.

## Цель и границы

FitCheck получает собственное долговечное хранилище PostgreSQL для следующих backend-задач. ANY-643 уже предоставляет самостоятельный FastAPI-пакет и контракты; ANY-644 добавляет модели, миграции, транзакционный слой и PostgreSQL integration tests. Успех: пустая БД воспроизводимо поднимается миграциями, ограничения исключают неверные связи и повторную запись, данные существующих DTO сохраняются без потерь, конкурентные операции имеют проверенное поведение.

`anytoolai-platform` служит только локальным архитектурным эталоном. Нет его импортов, общей БД, схемы `platform` или runtime-зависимости. UI, действующие Next.js endpoints и опубликованный API не переключаются в рамках этой задачи. Создание облачной БД и деплой требуют отдельного шага после реализации.

## Выбранный подход

SQLAlchemy 2, синхронный драйвер psycopg 3, Alembic и отдельная PostgreSQL БД. Синхронные операции выполняются в синхронных сервисах; будущие async handlers не должны блокировать event loop непосредственным вызовом такого сервиса. На этой стадии ORM не используется из HTTP обработчиков.

Связи, владельцы, состояния, даты, ключи идемпотентности и поля фильтрации представлены обычными столбцами. Профили, вакансии, входные снимки и результаты — JSONB с проверкой через существующие Pydantic DTO на границе записи. Полностью JSONB-хранилище затрудняет ограничения и конкурентные обновления; полностью разложенные доменные DTO увеличивают стоимость эволюции и риск потери вложенных полей.

Модели разделяются на identity, profiles, analyses/jobs и accounting; общий модуль содержит metadata, UUID и UTC типы. Не создаём универсальный repository framework или workflow engine.

## Подключение и транзакции

`FITCHECK_DATABASE_URL` — секрет PostgreSQL DSN, необязательный для запуска существующего foundation API, обязательный для миграций и работы storage. Допускается только PostgreSQL через psycopg. DSN не попадает в логи или публичные ошибки. Настройки соединений имеют явные ограниченные значения: pool size, overflow, timeout и statement timeout; значения и способ установки фиксируются в плане.

Engine создаётся явно фабрикой и закрывается владельцем жизненного цикла, без соединения при импорте. Используется pool pre-ping. Unit of work предоставляет Session внутри контекстного менеджера: commit на успешном выходе, rollback при исключении, close всегда. Вложенный неявный commit запрещён. Внешние provider calls не выполняются внутри транзакций.

Существующие health endpoints сохраняют semantics foundation. Добавление проверки БД в readiness произойдёт при подключении runtime-сервисов: ANY-644 не объявляет бизнес-готовность по одному успешному соединению.

## Владение и идентификаторы

Внутренние идентификаторы — UUID, создаваемые сервером. Все временные поля — timezone-aware UTC (`timestamptz`), передача naive datetime отклоняется. Идентификаторы из импортируемой истории становятся внешними ключами дедупликации, а не серверными primary keys.

Таблица `owners` задаёт общий корень владения с `kind=user|guest`. `users` и `guests` ссылаются на него, имеют unique owner_id и фиксированный owner_kind; composite FK на `(owners.id, owners.kind)` не позволяет связать user с guest owner. Профили, jobs, вакансии и результаты всегда имеют non-null owner_id. Создание корня и соответствующей identity выполняется одной транзакцией.

Composite FK `(resource_id, owner_id)` между принадлежащими владельцу объектами запрещают, например, связать результат пользователя A с job пользователя B. Для каждого такого FK существует соответствующий unique constraint. Проверка HTTP identity и доступа появится в ANY-645; storage не принимает client-supplied ownership за подтверждённую identity.

Guest claim требует переноса принадлежащих гостю объектов к user owner одной транзакцией в ANY-651. Связи владения, которым необходим такой перенос, DEFERRABLE INITIALLY IMMEDIATE; операция явно откладывает их проверку до commit. Она не изменяет snapshot или результат. ANY-644 проверяет атомарность такого переноса на уровне БД, но не реализует claim endpoint или его авторизацию.

## Сущности

| Группа / таблица | Содержимое и ограничения |
| --- | --- |
| `owners` | UUID, kind, created_at; unique `(id, kind)` |
| `users` | owner, normalized email unique, password_hash, email_verified_at, created_at, updated_at; сырой пароль не хранится |
| `guests` | owner, created_at, expires_at, claimed_by_user_id nullable, claimed_at; поля claim либо оба пустые, либо оба заполнены |
| `auth_sessions` | user, kind web/extension, token_digest unique, csrf_digest nullable, expires_at, revoked_at; только digest секретов |
| `auth_tokens` | user, purpose verify_email/reset_password/extension_code, token_digest unique, expires_at, consumed_at; PKCE challenge/redirect_uri для extension code |
| `profiles` | owner unique, current_revision >= 1; отсутствие профиля означает отсутствие строки, не revision 0 |
| `profile_revisions` | owner, revision >= 1, profile JSONB, created_at; unique `(owner_id, revision)`, append-only |
| `preferences` | owner unique, locale ru/en, updated_at |
| `drafts` | owner unique, vacancy JSONB, locale, updated_at; отсутствие строки соответствует null DTO |
| `vacancies` | owner, vacancy JSONB, source_url nullable, created_at; неизменяемая версия входа |
| `jobs` | owner, type analysis/skill_suggestions/import, status queued/running/succeeded/failed, input JSONB, idempotency_key, request_hash, attempts, available_at, lease_token/lease_expires_at nullable, timestamps, safe error JSONB nullable, suggestion/import output nullable |
| `analyses` | owner, job nullable для legacy import, vacancy, profile_revision nullable для guest/import, snapshot JSONB, analysis JSONB, created_at; одна analysis на job, неизменяемый результат |
| `analysis_annotations` | analysis и owner, corrected_score nullable 0..100, note nullable, feedback_created_at nullable, application_status enum контрактов, updated_at; mutable дополнение к результату |
| `quota_buckets` | owner, policy_key, window_start, resets_at nullable, limit, reserved, consumed; unique owner/policy/window, все счётчики неотрицательны и reserved+consumed <= limit |
| `quota_reservations` | owner, job, bucket, units > 0, status reserved/consumed/released, timestamps; unique job/bucket |
| `provider_calls` | owner, job nullable, provider, operation, model, attempt, request_key unique, state started/succeeded/failed/unknown, token counters, cost numeric nullable, currency nullable, safe error code, timestamps |
| `import_entries` | owner, source local_v1, external_id, content_hash, analysis, created_at; unique owner/source/external_id |

Это минимальный долговечный фундамент критериев ANY-644. Алгоритмы авторизации, резервирования квот, leasing/retry, отправки писем и вызовов provider остаются в своих задачах. Не сохраняются сырой provider request/response, пароли, bearer tokens или содержимое вакансий в техническом ledger.

## Инварианты и совместимость

Profile update использует optimistic concurrency: ожидаемая revision проверяется атомарно, следующая revision добавляется вместе с изменением current_revision в одной транзакции. FK current profile на существующую revision проверяется на commit. Две записи с одинаковым expectedRevision не могут обе завершиться успешно. Исторические revisions не переписываются.

Snapshot полностью содержит профиль, вакансию, locale, profileRevision и версии prompt/schema/policy по контракту ANY-643. Даже при наличии FK snapshot самодостаточен. Guest snapshot получает положительную revision 1 для одноразового входа; это не создаёт account profile. Импорт нормализует профиль перед сохранением. `desiredMonthlyIncome` игнорируется и исключается из JSONB; бюджет, валюта, skillLevels и strengthEvidence сохраняются. Денежные числа не преобразуются в строки и не округляются дополнительным storage-кодом; техническая стоимость provider хранится в NUMERIC.

Приложение валидирует JSONB при записи и чтении через конкретный DTO. DB CHECK требует JSON object для object payloads. Versioned snapshot читается по schema_version; текущая задача поддерживает существующую версию и явно отклоняет неизвестную. Versioning не означает применение будущего валидатора к старым данным без миграции.

DB triggers запрещают изменение содержимого profile revisions, вакансий, job input/request_hash и analysis snapshot/result/created_at. Разрешено атомарное изменение owner_id при claim и удаление при очистке. При reanalysis появляется новый job и analysis. Feedback/status хранятся отдельно и не изменяют исходный отчёт.

Idempotency unique `(owner_id, type, idempotency_key)` для jobs. Один ключ с тем же request_hash возвращает существующий job; несовпадающий hash — конфликт. Idempotency key ограничен по длине. Проверка конкурентной вставки опирается на unique constraint, а не на предварительный SELECT. Payload сохраняется после нормализации DTO; hash вычисляется по детерминированному JSON и включает все параметры операции.

CHECK constraints ограничивают состояния и связанные поля: lease только у running; terminal timestamp только у terminal; безопасная ошибка обязательна у failed; success output соответствует типу job. Analysis/job связь допускает только analysis job с тем же владельцем, обеспечивается composite FK с фиксированным discriminator. Переходы состояний проверяет будущий job service; произвольные SQL UPDATE не считаются публичным API.

История индексируется `(owner_id, created_at DESC, id DESC)` и `(owner_id, application_status)` в annotations. Jobs имеют индексы для queued scheduling и истекающих leases, sessions/tokens/guests — по expiry, provider_calls — owner/job/created_at. Дополнительные индексы добавляются по реальному запросу, не на каждый JSONB ключ.

## Миграции

Alembic живёт в `backend/migrations`, version table принадлежит только FitCheck. Initial migration создаёт таблицы, constraints, индексы и immutable triggers; модельная metadata согласуется с ней. Runtime не вызывает create_all и не запускает Alembic автоматически.

Одна команда migration runner получает DSN из настроек, берёт PostgreSQL advisory lock и выполняет upgrade head. Конкурентный runner ждёт ограниченное время, затем завершается с понятной ошибкой. Lock удерживается тем же соединением до завершения миграции и освобождается даже при ошибке. Миграции transactional; технические ошибки не раскрывают credentials.

Проверяем bootstrap на пустой БД, повторный upgrade head с существующими данными, Alembic drift и rollback initial migration только на одноразовой тестовой БД. Downgrade initial migration уничтожает данные и документируется как тестовый rollback, не production recovery. Будущие миграции обязаны иметь отдельные тесты сохранения данных. Восстановление backup и orchestration деплоя относятся к ANY-654.

## Retention и удаление

Согласованная политика: account profiles/history сохраняются до удаления аккаунта; guest данные — 30 дней после expires_at, неприсвоенные аккаунту; expired/revoked sessions и consumed/expired auth tokens — 7 дней после срока действия/отзыва; terminal jobs и idempotency записи — не менее 30 дней после завершения; обезличенный технический provider ledger — 90 дней.

Удаление аккаунта/неприсвоенного гостя удаляет identity и все личные данные транзакционно через owners и согласованные cascades. Claimed guest не очищается как неприсвоенный. Analyses, snapshot и revisions не сохраняются бесконечно после удаления владельца. Ledger при удалении очищает owner/job ссылки и сохраняет только технические метрики без текста, токенов доступа или request identifiers, связывающих запись с пользователем. FK ledger используют SET NULL; состав nullable ссылок и CHECK явно допускает обезличенное состояние.

Успешный analysis job нельзя удалить, пока на него ссылается отчёт: очистка сначала отвязывает optional job reference, сохраняя immutable snapshot. Квоты и import dedupe сохраняются, пока нужны соответствующей политике/аккаунту. Scheduler, автоматическая очистка и account deletion endpoint не входят в ANY-644; политика и проверенные операции удаления формируют контракт для их реализации. Финальные значения TTL конфигурируются в задачах соответствующих сервисов.

## Проверки

Настоящий PostgreSQL в одноразовом Docker Compose окружении, без SQLite substitute. Integration suite в CI поднимает отдельный PostgreSQL service и запускает миграции; без доступной тестовой БД явно запрошенный integration run завершается ошибкой, не молча пропускается.

Обязательны: bootstrap/re-upgrade/schema drift; round-trip полных DTO и legacy income normalization; owner/type FKs; immutable trigger rejection; rollback без частичных записей; параллельный profile update; параллельная idempotent job creation; несовпадающий hash; конкурентная quota reservation на уровне атомарного UPDATE; claim-like ownership transfer с commit/rollback; identity deletion и обезличивание ledger; UTC и safe settings errors. Два конкурентных соединения синхронизируются барьерами, без flaky sleeps.

Существующие backend unit tests и OpenAPI drift check должны продолжать проходить; публичные DTO не меняются. Frontend type/schema check подтверждает отсутствие изменения контракта. Документация содержит локальные команды, migration ordering и явное предупреждение об уничтожении тестовых данных при downgrade.

## Последовательность продолжения

После согласования этой спецификации подготовить план реализации с файлами, миграционными инвариантами и командами проверки. План должен определить isolated worktree, отдельные проверяемые этапы и финальный code review. Реализация начинается после согласования плана и способа выполнения.
