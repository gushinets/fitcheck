# ANY-649: durable jobs и отдельный worker

## Цель и границы

Сайт отправляет анализ или запрос подсказок навыков в standalone backend,
получает job ID и читает состояние без ожидания LLM в HTTP-запросе.
Задание переживает рестарт API/worker. Один job публикует максимум один
результат; повтор HTTP с тем же ключом не создаёт новое платное задание.

Пользователь согласовал PostgreSQL queue, отдельный worker, frozen inputs,
lease/heartbeat и одно автоматическое восстановление после падения процесса.
Расширение исключено из проекта. Здесь реализуются account admission,
job status/result и публикация результата worker. History/feedback/reanalysis
API остаются ANY-650, guest identity/quota — ANY-651, import — ANY-652,
подключение сайта — ANY-653. Existing import jobs worker не захватывает.

## Архитектура и выбранный вариант

API и worker используют одну PostgreSQL БД и пакет backend, но запускаются
разными процессами/контейнерами. API валидирует identity, admission и DTO;
worker вызывает готовый ANY-648 LLM runtime. Redis/Celery не нужны.

Ориентир — `anytoolai-platform/apps/platform-worker`: отдельный process,
короткие claim transactions, bounded reconciliation и drain при shutdown.
Эталон сейчас удерживает session advisory lock для определения живости.
FitCheck не импортирует его код и выбирает существующие поля lease в jobs:
это освобождает DB connection на время HTTP и позволяет fencing при commit.
Advisory lock потребовал бы отдельного долгоживущего connection на job;
вариант только с ручным повтором снизил бы автоматическую доступность.

Компоненты: admission service, queue repository, owner-scoped status reader,
frozen-input executor adapter, fenced publication repository и worker loop.
Storage отвечает за транзакции; executor не меняет состояния jobs.

## HTTP контракт и доступ

- `POST /v1/analysis-jobs`: текущий account AnalysisStart; 202 с
  `jobId`, `type`, `status`. Повтор возвращает фактическое текущее состояние
  существующего job, включая terminal status, без нового исполнения.
- `POST /v1/skill-suggestion-jobs`: SkillSuggestionStart; такой же admission
  response с type `skill_suggestions`.
- `GET /v1/jobs/{jobId}`: существующий tagged JobState. Analysis success
  содержит `analysisId` и `result: AnalysisResource`, suggestions success —
  `skills`; failed содержит только безопасный ErrorBody.

Новый минимальный admission DTO не раскрывает input, lease или provider metadata.
Дополнительное поле result позволяет получить результат через job endpoint
до реализации отдельного analysis/history API. AnalysisResource собирается
из сохранённого analysis/snapshot; annotation fields читаются owner-scoped.
OpenAPI и generated TypeScript обновляются вместе с реализацией.

Доступ — verified account session, существующие CSRF/Origin правила для POST,
owner-scoped GET. Чужой/несуществующий job даёт одинаковый 404. Import jobs
не доступны через этот endpoint. Guest DTO остаётся в roadmap contract,
но admission guest не включается до ANY-651. Профиль выбирается только по
revision владельца; revision проверяется в диапазоне storage integer.

Idempotency-Key обязателен, 1..200 символов. Ключ уникален по owner/type/key.
Тот же ключ с другим нормализованным client request даёт 409. Новый ключ
является явным новым запуском, даже при идентичных входах. Никакого скрытого
повтора failed job HTTP-запросом с прежним ключом нет.

## Admission и неизменяемые входы

В одной короткой транзакции admission блокирует owner для сериализации
лимита, проверяет existing idempotency record, затем для нового задания
читает профиль выбранной версии и последние calibration entries.
Сохраняются client request hash, frozen execution envelope и queued job.
Rollback не оставляет частичного задания. Existing duplicate возвращается
до проверки текущего профиля, memory или новой policy: исходное задание
сохраняет семантику после изменения настроек и деплоя.

Envelope имеет собственную версию формата и содержит нормализованный client
request, копию profile, revision, отредактированную vacancy, locale, memory,
server-owned provider/model и prompt/schema/policy versions. Suggestions
сохраняют specialization, locale и собственные версии. Клиент не может
назначить model, policy, память или server versions.

`request_hash` вычисляется исключительно по нормализованному клиентскому
DTO и job type. Server envelope не входит в idempotency hash. Existing
storage helper разделяется на request validation/hash и создание job с
execution payload, сохраняя поведение legacy import callers.

Worker валидирует envelope и поддерживаемую комбинацию версий до provider
call. Неизвестная версия завершается safe failure без HTTP. Worker не
перечитывает актуальный профиль/calibration и не заменяет версии молча.
AnalysisService получает общий путь исполнения подготовленного AnalysisInput;
текущий direct service остаётся внутренним и не получает публичного route.

Для новых account jobs: не более двух queued/running jobs на owner суммарно
для analysis и suggestions, плюс существующая user/IP rate limit защита.
Duplicate не занимает новый слот. Owner lock делает лимит корректным при
конкурентном admission. Paid quota/billing здесь не вводятся.

## Queue, lease и fencing

Состояния: queued → running → succeeded/failed. Recovery заменяет lease
истёкшего running job; cancelled state/endpoint не добавляется.

Worker обрабатывает по одному job одновременно; масштабирование — несколькими
процессами. Claim выбирает due queued или expired running supported types
через `FOR UPDATE SKIP LOCKED`, с детерминированным порядком scheduling/id.
В этой же транзакции устанавливает новый случайный lease_token,
lease_expires_at, started_at и увеличивает attempts. DB clock определяет
истечение lease; сравнения не используют часы worker host.

Defaults: poll interval 1 секунда, lease 150 секунд, heartbeat 20 секунд.
Настройки finite/positive; heartbeat меньше lease, lease покрывает максимальный
120-секундный executor deadline и запас для публикации. Per-job executor
deadline начинается перед исполнением frozen context. DB операции имеют
bounded connection/statement/lock timeout; synchronous storage calls не
блокируют event loop heartbeat, выполняясь через отдельный bounded adapter.

Heartbeat продлевает только running job с совпадающим token и ещё действующим
lease. Истёкший lease не воскресает. При отрицательном результате, DB ошибке
или недоказанной успешности heartbeat worker прекращает исполнение, отменяет
LLM task best effort и не публикует результат.

Каждый terminal commit требует owner, running status, текущий lease_token
и unexpired lease, проверенные под row lock. На момент публикации используется
актуальное DB время после получения lock. Stale worker не может ни записать
результат, ни затереть ошибку нового исполнения. Claim не держит connection
на время LLM. Heartbeat и finish сериализуются через row lock.

## Публикация и чтение

Success analysis в одной транзакции проверяет fencing, создаёт VacancyRecord
из frozen vacancy и AnalysisRecord с job_id, owner, profile revision,
immutable snapshot и validated analysis, затем выставляет job succeeded,
finished_at и очищает lease. Unique AnalysisRecord.job_id — дополнительная
защита от двойной публикации. Analysis job.output остаётся null по CHECK.

Success suggestions сохраняет validated `{skills: [...]}` в job.output в
той же fenced terminal transaction. Failure сохраняет safe ErrorBody,
finished_at, очищает lease/output и не создаёт analysis/vacancy record.
Никаких raw exception/provider response/request secrets в job.error.

GET job читает состояние и связанный результат в одной согласованной read
transaction/query; невозможно вернуть succeeded без committed analysis.
Неизменяемые payloads не переписываются повторным исполнением. Profile FK
и owner checks сохраняют существующие ограничения ownership transfer.

## Падения, повторная стоимость и лимиты

Максимум два worker исполнения job: исходное и одно recovery после утраты
lease. Gateway transport/semantic retries остаются в существующих пределах
ANY-648. Обычный итоговый provider timeout/invalid output/upstream failure
делает job failed; worker не запускает дополнительно новый semantic cycle.
Expired job с исчерпанными attempts завершается safe failure без provider.
Ошибки infrastructure/падение до terminal commit восстанавливаются по lease;
вторая потеря lease заканчивает job. Recovery bounded и работает при startup
и в обычном polling, в том числе при постоянно непустой очереди.

Если процесс умер после provider response, но до publication commit,
response мог быть оплачен, а результата в БД нет. Recovery вычисляет результат
заново, поэтому внешние вызовы не имеют exactly-once гарантии. Каждый новый
executor operation имеет новый UUID; все физические попытки остаются в
provider_calls с owner/job, token/cost/latency и versions. Неизвестные usage
не превращаются в нули и не выдаются за бесплатные вызовы.

Для корректного reconciliation provider_calls связываются с worker execution
через nullable execution lease token (аддитивная migration 0003; старые rows
допустимы). При recovery started calls старого lease помечаются unknown с
safe process_lost code; succeeded calls сохраняют usage и стоимость. Ledger
completion не переписывает уже reconciled unknown outcome. Новое исполнение
не меняет rows другого token. Содержимое провайдерного ответа не сохраняется
как средство восстановления. Автоматически повторная стоимость допускается
только в пределах двух executions, ручной новый job может вызвать новую оплату.

## Runtime и deployment

Отдельный worker entrypoint, контейнерная команда и local compose service.
Worker владеет DB engine и LlmRuntime, проверяет schema до polling. Provider
key обязателен worker, публичный API для jobs не создаёт LLM runtime и не
требует provider key. Shutdown SIGTERM прекращает claim, продолжает heartbeat
и даёт текущей задаче bounded drain до 130 секунд, после чего отменяет task;
неуспевший job остаётся для lease recovery. Container stop grace согласован
с drain. Cancellation не превращается в success.

Worker health проверяет свежесть локального heartbeat worker loop, включая
busy job, и готовность startup/schema; secrets/payloads не выводятся. Process
без ключа/с неподдерживаемой schema не объявляется healthy. Отсутствие свежей
DB heartbeat останавливает выполнение. API readiness не выдаёт своё наличие
за доказательство живости worker.

Admission feature flag по умолчанию выключен до rollout worker. При выключении
новые POST получают safe service_unavailable; existing GET продолжает работать.
При включённом admission и недоступном worker jobs остаются queued: durable
queue не обещает немедленного исполнения. Dev rollout: additive migration,
API/worker deploy, schema/health smoke, затем включение admission. Reset БД не
нужен. Проверка LLM с платным реальным вызовом остаётся отдельным opt-in;
обычные тесты и deployment smoke используют fake provider/неплатные проверки.

## Проверки и критерии завершения

Unit/API tests проверяют safe DTO/errors, auth/CSRF/owner isolation, disabled
admission, idempotency conflict и неизменяемые input snapshots. Реальные
PostgreSQL integration tests проверяют конкурентные double-click/claim,
owner admission cap, SKIP LOCKED, heartbeat/expiry, two-worker races, stale
success/failure, rollback publication и согласованность чтения.

Crash tests моделируют остановку после claim, после provider success и перед
commit, второй process loss, reconciliation ledger и повторную стоимость.
Фальшивый provider считает физические HTTP попытки; barriers/events задают
порядок гонок без произвольного ожидания. Отдельные проверки worker shutdown,
heartbeat во время долгого async HTTP, missing key, invalid versions, bounded
timeouts и отсутствие DB connection на время LLM.

Обязательны migration upgrade/schema drift, contract/TypeScript drift,
backend suite, релевантные frontend checks, worker container boot/health.
После реализации — независимое code review и фиксация deployment evidence.
Успех задачи: durable account analysis/suggestion jobs с наблюдаемым состоянием
и результатом, максимум одна публикация, ограниченное recovery с прозрачным
ledger; website UI переключается отдельно в ANY-653.
