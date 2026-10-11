# FitCheck PostgreSQL Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Добавить собственное транзакционное хранилище FitCheck с воспроизводимыми Alembic-миграциями и проверенными PostgreSQL ограничениями.

**Architecture:** Синхронный SQLAlchemy/psycopg, отдельный engine и unit of work. Relational columns отвечают за владение, связи и конкуренцию; JSONB хранит валидированные DTO. API и UI пока используют существующее поведение.

**Tech Stack:** Python 3.12, SQLAlchemy >=2.0,<2.1, psycopg[binary] >=3.2,<4, Alembic >=1.13,<2, PostgreSQL 17, pytest, uv; версии зависимостей фиксируются uv.lock.

**Spec:** `docs/superpowers/specs/2026-10-11-fitcheck-storage-design.md` — прочитать целиком до выполнения.

## Global Constraints

- FitCheck имеет отдельную БД; нет импортов, общей БД или runtime-зависимости от anytoolai-platform.
- Runtime не вызывает create_all и не запускает Alembic автоматически; миграции — отдельный процесс до API/worker.
- UUID генерирует сервер; все timestamps timezone-aware UTC; naive datetime отклоняется.
- Все личные ресурсы имеют non-null owner_id; composite FK защищают принадлежность связанного объекта.
- Profile revisions, vacancy versions, job inputs и analysis snapshots/results неизменяемы; feedback/status отдельно.
- `desiredMonthlyIncome` не сохраняется; валюты, бюджеты, skillLevels, strengthEvidence сохраняются без потерь.
- Retention: аккаунт до удаления; неприсвоенный guest 30 дней после expiry; auth записи 7 дней после expiry/revocation; terminal jobs/idempotency минимум 30 дней; обезличенный provider ledger 90 дней.
- Нет бизнес-endpoints, worker scheduler, provider calls, автоматической очистки, production БД или деплоя в этой задаче.
- Test run PostgreSQL не заменяется SQLite и не пропускается при явно запрошенном integration запуске.

## Review Focus

1. DSN с паролем и нестандартными символами либо ошибкой: credentials не появляются в repr, ошибке CLI или логах — Task 1.
2. Nullable composite FK: отсутствие optional link допустимо, частичная/чужая ссылка запрещена — Tasks 2/4.
3. Guest claim при существующей истории аккаунта: перенос не перезаписывает account profile и не смешивает revision keys — Task 5.
4. Удаление identity с circular/composite FK и provider ledger: личные данные исчезают, метрики сохраняются без идентификаторов — Task 5.
5. Убийство migration runner/ошибка DDL: lock освобождается, следующий runner может повторить upgrade — Task 4.

## Файлы и границы

`backend/src/fitcheck_backend/storage/`:
- `database.py`: engine, обязательный DSN, UoW и безопасная ошибка конфигурации.
- `base.py`: Base/metadata naming conventions, UUID и UTCDateTime.
- `identity.py`, `profiles.py`, `work.py`, `accounting.py`: только декларации моделей групп из spec.
- `models.py`: импорт всех моделей для Alembic, без подключения.
- `payloads.py`: конкретные DTO codecs, canonical JSON/hash, версия snapshot.
- `profile_repository.py`, `job_repository.py`: минимальные транзакционные операции, без auth/worker алгоритмов.
- `ownership.py`: атомарный перенос analysis graph и удаление owner для будущих сервисов.
- `migrate.py`: CLI upgrade/check, advisory lock и Alembic connection sharing.

`backend/migrations/`: env.py, script.py.mako, versions/0001_initial_storage.py, versions/0002_immutable_payloads.py. Первая миграция — самостоятельная relational schema; вторая добавляет immutable triggers и служит реальным upgrade существующей БД для теста.

Дополнительно: `backend/alembic.ini`, `backend/compose.test.yaml`, `backend/tests/integration/`, focused unit tests; изменения config.py, pyproject.toml/uv.lock, README.md, .env.example, Dockerfile, CI. OpenAPI/клиенты не меняются.

## Выполнение и окружение

После согласования плана создать `.worktrees/any-644` / `feat/any-644-storage` через using-git-worktrees. Сначала baseline backend tests и OpenAPI check. Каждый task выполняется RED → GREEN → commit, ledger ведётся средствами выбранного execution skill.

Все команды ниже из `backend/` рабочего дерева. Использовать Python 3.12: `uv sync --python /opt/homebrew/bin/python3.12`; затем `uv run --locked ...`. Разрешения сети/Docker/.git запрашивать через штатный escalation, не обходить sandbox.

Compose service `postgres` использует `postgres:17`, database/user/password `fitcheck_test`, порт `127.0.0.1:55464:5432`, healthcheck pg_isready. Для тестов задаётся `FITCHECK_TEST_DATABASE_URL=postgresql+psycopg://fitcheck_test:fitcheck_test@127.0.0.1:55464/fitcheck_test`; это одноразовая тестовая БД, не production DSN.

## Task 1: Безопасное подключение и unit of work

**Files:** config.py, pyproject.toml, uv.lock; create storage/{__init__,base,database}.py; tests/test_database.py.

**Interfaces:** `create_engine(settings: Settings) -> Engine`; `unit_of_work(engine: Engine) -> AbstractContextManager[Session]`; `UTCDateTime(TypeDecorator[datetime])`; `StorageConfigurationError(RuntimeError)`.

- [x] Написать tests `test_database_url_is_secret_and_postgres_only`, `test_import_does_not_connect`, `test_naive_datetime_rejected`, `test_unit_of_work_rolls_back_and_closes`. Assert: no DSN/password in repr/safe CLI error, SQLite URL rejected, no DB connection at import, naive bind raises ValueError, exception causes rollback/close without commit. Для lifecycle test использовать маленький spy Session, реальные транзакции проверяются Task 5.
- [x] Запустить `uv run pytest tests/test_database.py -q`; увидеть FAIL из-за отсутствующего storage API.
- [x] Добавить runtime зависимости и Settings: optional SecretStr database_url; pool_size=2 (1..20), max_overflow=3 (0..20), pool_timeout_seconds=5 (1..60), statement_timeout_ms=15000 (1..300000). Нормализовать postgres/postgresql URL к postgresql+psycopg через SQLAlchemy URL parser, отклонять другой driver, пустые host/database и небезопасные ошибочные значения. Установить hide_input_in_errors; не логировать ValidationError payload/input. Engine echo=False, hide_parameters=True, pool_pre_ping=True, timeout через psycopg connection options. UoW использует sessionmaker expire_on_commit=False и единственный commit на выходе.
- [x] Запустить `uv run pytest tests/test_database.py tests/test_foundation.py -q`; PASS. Проверить существующий API без DSN.
- [x] Commit: `feat: add safe PostgreSQL connection and unit of work`.

## Task 2: Relational модели и ownership constraints

**Files:** create storage/{identity,profiles,work,accounting,models}.py; tests/test_storage_metadata.py.

**Interfaces:** `Base.metadata`; модели `Owner, User, Guest, AuthSession, AuthToken, Profile, ProfileRevision, Preference, Draft, VacancyRecord, Job, AnalysisRecord, AnalysisAnnotation, QuotaBucket, QuotaReservation, ProviderCall, ImportEntry`. Имена таблиц/поля/состояния берутся из spec без переименования публичных DTO.

- [x] Написать `test_metadata_contains_all_storage_tables`, `test_owner_links_are_composite`, `test_nullable_links_have_explicit_rules`; assert полный список 17 таблиц из spec, PostgreSQL DDL compiles, unique targets есть для каждого composite FK, FK ownership переноса deferrable, enum values равны контрактам.
- [x] Запустить `uv run pytest tests/test_storage_metadata.py -q`; FAIL: моделей нет.
- [x] Реализовать модели. JSON object CHECK; named constraints, VARCHAR+CHECK для состояний без глобальных PostgreSQL ENUM. UUID defaults/UTC fields; количества integer неотрицательные, provider cost NUMERIC(20,8). Email normalized column unique; secrets только hashes/digests. Idempotency key длина 1..200, SHA-256 hash длина 64. Jobs/analyses unique `(id, owner_id)` и discriminator FK analysis-job. Job terminal/lease/output CHECK по spec. Feedback note max 500, corrected score 0..100.
- [x] Решить nullable связи явно: analysis→job содержит nullable job_id, owner_id всегда задан; nullable job discriminator пуст только вместе с job_id. profile revision link optional, profile revision FK `(owner_id, revision)`. Ledger owner/job ссылки optional после обезличивания: при owner delete удалить owner_id/job_id/request_key, request_key nullable unique; сохранить отдельный внутренний UUID и технические метрики. DB trigger очистки ledger до owner cascade реализуется Task 4. Ledger с job требует owner и composite FK; отдельный owner FK защищает вызов без job. Current profile→revision FK deferrable; обратный revision→owner FK CASCADE. Удаление account выполняется от root Owner.
- [x] Запустить `uv run pytest tests/test_storage_metadata.py -q`; PASS. Проверить indexes history/scheduler/lease/expiry и constraints против spec.
- [x] Commit: `feat: define FitCheck relational storage models`.

## Task 3: Валидированные JSONB и неизменяемые входы

**Files:** create storage/payloads.py; tests/test_storage_payloads.py; use tests/fixtures/domain.json.

**Interfaces:** `encode_profile(value: FreelancerProfile | LegacyProfile) -> dict`; `decode_profile(value: dict) -> FreelancerProfile`; `encode_vacancy(value: Vacancy) -> dict`; `decode_vacancy(value: dict) -> Vacancy`; `encode_snapshot(value: AnalysisSnapshot) -> dict`; `decode_snapshot(value: dict) -> AnalysisSnapshot`; `encode_analysis(value: FitAnalysis) -> dict`; `decode_analysis(value: dict) -> FitAnalysis`; `canonical_hash(value: dict) -> str`. `CURRENT_SCHEMA_VERSION = "fitcheck.analysis.v1"`; неизвестная версия вызывает `UnsupportedSnapshotVersion(ValueError)`.

- [x] Написать `test_complete_dto_round_trip`, `test_legacy_income_is_never_encoded`, `test_snapshot_version_rejected`, `test_hash_is_order_independent_and_input_sensitive`. Assert исходный model_dump(mode=json, by_alias=True) совпадает после decode; nested skillLevels/strengthEvidence/currencies/budget присутствуют; income отсутствует; смена locale/profile/prompt version меняет hash, перестановка dict keys не меняет; explicit invalid/null payload отвергается текущими DTO.
- [x] Запустить `uv run pytest tests/test_storage_payloads.py -q`; FAIL: codecs отсутствуют.
- [x] Реализовать конкретные codecs через DTO validation/dump; normalization legacy через LegacyProfile с excluded income. Canonical hash — UTF-8 JSON sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, SHA-256. Не добавлять generic serializer/не округлять money.
- [x] Запустить `uv run pytest tests/test_storage_payloads.py tests/test_contracts.py -q`; PASS.
- [x] Commit: `feat: validate versioned storage payloads`.

## Task 4: Alembic и настоящая PostgreSQL проверка схемы

**Files:** create migrations files listed above, alembic.ini, storage/migrate.py, compose.test.yaml, tests/integration/{conftest,test_migrations,test_constraints}.py; pytest marker/config.

**Interfaces:** `run_migrations(settings: Settings, *, revision: str = "head") -> None`; `check_schema(settings: Settings) -> None`; CLI `python -m fitcheck_backend.storage.migrate upgrade` / `check`; integration fixtures `engine`, `db_session`, `storage_factory` (minimal valid owner/job/analysis graph).

- [x] Написать migration/constraint tests: bootstrap head contains tables/triggers; 0001 data survives upgrade 0002; repeated head preserves row count; check reports no drift; downgrade base removes only disposable schema; wrong-owner/type links raise IntegrityError; partial nullable links fail; payload mutations fail but annotations update succeeds. `test_explicit_integration_requires_database` доказывает отсутствие молчаливого skip. При collection без integration marker не подключаться к БД.
- [x] Запустить unit suite и explicit integration suite; первые новые тесты должны FAIL по отсутствующим migration modules/fixtures. Integration помечены marker; default pytest addopts исключает integration, explicit `-m integration` включает их и требует тестовый DSN. Никогда не брать обычный FITCHECK_DATABASE_URL как test fallback.
- [x] Реализовать миграции явными Alembic op, не импортировать изменяемую model metadata в revision. 0001 таблицы/constraints/indexes; 0002 immutable payload triggers и ledger anonymization. Запрет изменения input/snapshot/version/created_at; owner_id и optional job reference разрешены только с выполненными FK. Ledger BEFORE owner DELETE очищает ссылки и request_key. Immutable triggers не блокируют DELETE.
- [x] Реализовать env.py connection sharing через Config.attributes["connection"], без credentials в ini. Runner lock key `0x464954434845434B`, pg_try_advisory_lock до 10 секунд, poll 0.1 секунды, finally unlock на том же connection; migration statement timeout 120000 ms. Upgrade выполняется transactional после lock acquisition, используя отдельную transaction от acquisition. CLI возвращает nonzero и безопасное сообщение без сырых исключений/DSN. Alembic check сравнивает metadata, trigger assertions отдельные. Package migration files как wheel resources через hatch force-include; путь env.py вычислять от package resource, без зависимости от cwd.
- [x] Поднять `docker compose -p fitcheck-any644 -f compose.test.yaml up -d --wait`; запустить `uv run pytest -m integration tests/integration/test_migrations.py tests/integration/test_constraints.py -q` с тестовым DSN. Assert PASS. Дополнить `test_concurrent_migration_serialized` и `test_failed_runner_releases_lock`: два connection/processes с barrier, ошибочная DDL откатывается и следующий runner достигает head; forcibly terminated connection не удерживает advisory lock. Повторить suite, PASS.
- [x] Commit: `feat: bootstrap FitCheck database with guarded Alembic migrations`.

## Task 5: Транзакционные операции и конкуренция

**Files:** create storage/{profile_repository,job_repository,ownership}.py; tests/integration/{test_transactions,test_concurrency,test_ownership,test_payload_roundtrip}.py.

**Interfaces:** `create_profile(session: Session, owner_id: UUID, profile: FreelancerProfile) -> ProfileResource`; `update_profile(session: Session, owner_id: UUID, expected_revision: int, profile: FreelancerProfile) -> ProfileResource`; `ProfileRevisionConflict(RuntimeError)`; `get_or_create_job(session: Session, owner_id: UUID, job_type: Literal["analysis", "skill_suggestions", "import"], idempotency_key: str, input_payload: dict) -> Job`; `IdempotencyConflict(RuntimeError)`; `transfer_guest_analyses(session: Session, guest_owner_id: UUID, user_owner_id: UUID) -> int`; `delete_owner(session: Session, owner_id: UUID) -> None`. Все функции участвуют в caller UoW, не commit и не открывают engine.

- [x] Написать tests с двумя independent connections и barriers: `test_profile_compare_and_swap` → одна успешная revision 2, другой ProfileRevisionConflict, история 1 неизменна; `test_job_idempotency_race` → один job ID/одна строка; `test_hash_conflict` → IdempotencyConflict. Rollback на исключении не оставляет partial profile/job/quota rows.
- [x] Запустить `uv run pytest -m integration tests/integration/test_concurrency.py tests/integration/test_transactions.py -q`; FAIL: repository API отсутствует.
- [x] Реализовать profile CAS через conditional UPDATE+append в caller transaction; первая revision создаётся атомарно с deferred FK. Jobs insert ON CONFLICT DO NOTHING с последующим чтением и hash comparison на READ COMMITTED, без catch IntegrityError повреждающего outer transaction. Validate input discriminator через соответствующий DTO (analysis/suggestion/import). Hash включает нормализованный input целиком. Import legacy payload normalization до hashing и storage.
- [x] Написать ownership/roundtrip tests: guest analysis и job transfer commit/rollback; user с revision 1 сохраняет профиль при claim; pending jobs блокируют перенос; raw database read JSONB не содержит income; profile/vacancy/analysis round-trip полных DTO; naive datetime отвергнут; quota conditional UPDATE при двух contenders и limit=1 даёт ровно одну reservation; owner deletion removes personal rows, retains ledger token/cost metrics with owner/job/request_key null; удаление expired job через detach не меняет analysis content.
- [x] Реализовать transfer_guest_analyses: lock owners в стабильном UUID порядке; проверить kind/guest claim и отсутствие nonterminal guest jobs; повторный claim тому же user возвращает 0, другому — конфликт. Перенести terminal jobs, analyses, referenced vacancies, annotations, связанный provider ledger и import dedupe с deferred FK; guest profile/preferences/draft не переносить. Отвязать optional profile revision FK переносимого анализа, сохранив исходный profileRevision внутри immutable snapshot. Не перемещать quota buckets гостя в account quota: удалить законченные guest reservations перед переносом jobs, сохранить гостевой bucket до cleanup. При collision user idempotency/import keys прекращать перенос целиком с `OwnershipConflict(RuntimeError)`, не переписывать данные. Set guest.claimed_by_user_id/claimed_at; guest identity остаётся до отдельной очистки. Вызовы с авторизацией добавит ANY-651; этот helper только storage primitive. delete_owner использует delete root с каскадами/ledger anonymization. Не добавлять quota service; concurrent quota test выполняет атомарный UPDATE напрямую и доказывает DB invariant.
- [x] Запустить все integration tests: `uv run pytest -m integration tests/integration -q`; PASS без flaky sleeps. Убедиться, что безопасные DB ошибки не содержат SQL parameters благодаря hide_parameters.
- [x] Commit: `feat: add atomic profile job and ownership persistence`.

## Task 6: CI, упаковка и документация

**Files:** modify .github/workflows/ci.yml, backend/{Dockerfile,README.md,.env.example}; create tests/test_migration_package.py.

**Interfaces:** установленный wheel содержит migration resources; контейнер может выполнить migration CLI, API запускается без DSN как прежде. CI использует disposable PostgreSQL 17 service, локальный bootstrap — compose.test.yaml.

- [x] Написать `test_installed_package_has_migrations`: build/install wheel в отдельное временное окружение, invoke CLI с чужого cwd; migration resources найдены, missing DSN даёт безопасную configuration error, а не FileNotFoundError. RED до корректировки Docker/package setup.
- [x] Обновить Dockerfile COPY migrations/alembic.ini перед uv sync; API CMD и health оставить текущими. CI backend service postgres:17 health pg_isready, env FITCHECK_TEST_DATABASE_URL, unit tests отдельно `uv run pytest -m 'not integration' -q`, integration отдельно `uv run pytest -m integration -q`; migration check и OpenAPI check обязательны. Увеличить backend timeout до 15 минут. Никакие production secrets для CI не нужны.
- [x] Обновить README/.env.example: settings defaults, compose start/stop, явные unit/integration команды, bootstrap/upgrade/check, одноразовый destructive downgrade, порядок migrate→API/worker, retention table и отсутствие scheduler. Примеры только test credentials. Не добавлять DSN в git или runtime logs.
- [x] Запустить fresh final verification: все unit/integration tests, `uv run python scripts/export_openapi.py --check`, `npm run backend:types:check`, `npm run typecheck`, `git diff --check`; wheel isolated test. Собрать Docker image и проверить migration CLI/resources/nonroot API health without DSN. PASS по всем обязательным проверкам; frontend build не нужен при неизменном runtime/web code.
- [x] Commit: `ci: verify standalone PostgreSQL storage and migration packaging`.

## Финальный review и передача

- [x] Fresh reviewer по всей ветке, включая spec и реальные результаты тестов; выбранный execution skill определяет dispatch. Отдельно проверить deferred constraints, миграционную блокировку, ownership graph, sensitive errors и wheel resources.
- [x] Исправить Critical/Important findings через regression test RED→GREEN и повторить затронутые проверки; Minor исправить либо явно аргументировать.
- [ ] Сверить spec coverage и git diff, отметить completed steps фактическими commit IDs/командами. Обновить ANY-644 результатом и статусом только после подтверждённых checks.
- [ ] Передать готовую ветку пользователю; merge/push/deploy выполняются по его указанию. PostgreSQL контейнер остановить, одноразовый volume удалять только с соответствующим разрешением.

## Первичные справочники

- [SQLAlchemy constraints](https://docs.sqlalchemy.org/en/20/core/constraints.html): composite ForeignKeyConstraint, naming и deferrable настройки.
- [Alembic commands](https://alembic.sqlalchemy.org/en/latest/api/commands.html): shared connection в Config.attributes, upgrade и check.
- [PostgreSQL advisory locking](https://www.postgresql.org/docs/17/explicit-locking.html): session lock lifecycle и explicit locking.

## Результаты выполнения

Реализация в `feat/any-644-storage`, рабочее дерево `.worktrees/any-644`, база `29c9cd8`. Этапы: `addfe44`, `bfe033c`, `cce272c`, `a5044aa`, `cc6dfb6`, `96bbb52`. Независимый review gpt-6-astra выявил stale ORM claim state и DSN credential representation; исправлены регрессионными тестами. Проверка чужого vacancy FK усилена SQLSTATE 23503/именем constraint. Последний suite: 152 passed (121 unit / 31 PostgreSQL integration), OpenAPI актуален; TypeScript generation/typecheck прошли. Docker build, wheel install из другого cwd, migration upgrade/check и UID 10001 health подтверждены. Production deployment не выполнялся.

Принятые решения и последствия:

- Ruling: migrations split relational bootstrap 0001 and triggers 0002 — initial upgrade head includes both and allows real existing-data upgrade test — cost if wrong: extra migration revision.

- Task 3: Ruling: public Revision DTO is a string, database revision is a positive integer — encode counter as decimal string in ProfileResource/snapshot, retain integer repository expected_revision — cost if wrong: future profile adapter needs explicit revision conversion; public schema unchanged.

- Task 4: Ruling: initial revision uses frozen explicit PostgreSQL DDL via Alembic op.execute instead of many op.create_table expressions — no runtime metadata imports and drift tested; improves parity with compiled named composite constraints — cost if wrong: PostgreSQL-specific migration, already the only supported database.

- Task 5: Ruling: job creation takes owner KEY SHARE and checks claimed guest state — serializes with ownership transfer/delete without serializing two ordinary job inserts — cost if wrong: extra short-lived row lock; prevents jobs created on a claimed guest.

- Task 5: Ruling: defer only transfer graph FKs rather than ALL — avoids changing caller's unrelated deferred profile constraint mode — cost if wrong: constraint list must evolve with ownership graph; metadata-derived list keeps it aligned.

- Task 6: Ruling: wheel resources already implemented in Task 4, so wheel test starts GREEN and Docker build supplies RED evidence (missing migration COPY) — no artificial break of packaged resources — cost if wrong: wheel test characterizes existing Task 4 behavior instead of new Task 6 logic.

- Final: Ruling: wrong-owner FK coverage finding regraded Important — explicit task acceptance requires proving cross-owner constraints, current test passes on unrelated immutable CHECK and would miss a removed isolation FK — cost if wrong: one stronger integration assertion/test, no runtime change.

- Final: Ruling: HTTP auth, worker leasing, quota algorithms and retention scheduling remain later-task workflows — ANY-644 exposes storage primitives only and live API is unchanged — cost if wrong: clients cannot use these workflows until implementing tasks finish.

- Final: Ruling: production provisioning, deployment and backup recovery remain ANY-654 / explicit deployment step — local wheel, image and migrations verified — cost if wrong: deployment still needs own DB and orchestration.

- Final: Ruling: deletion concurrent with a newly claimed guest fails closed through FK — retain atomic rollback, future deletion service must retry/re-enumerate — cost if wrong: rare concurrent deletion returns a retryable failure rather than completing immediately.

- Final: Ruling: low-level ORM/SQL maintenance can bypass codecs and accept arbitrary ledger labels — application services must validate at their boundaries, maintenance interface is trusted/documented — cost if wrong: manual unvalidated writes can create payloads rejected by readers; never expose raw Session writes to clients.

- Final: Ruling: updated_at maintenance and permitted job transitions remain future services — current schema validates row states, not workflow transitions — cost if wrong: a service that omits timestamp/state handling can persist misleading metadata.

Отложенных замечаний review нет. Бизнес-сервисы и orchestration перечислены выше как границы ANY-644, а не незавершённые исправления этой задачи.
