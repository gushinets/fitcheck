# ANY-648: серверный LLM gateway FitCheck

Дата: 2026-10-12. Статус: письменная спецификация согласована пользователем.

## Цель и границы

Перенести существующие `lib/analysis/*` и `lib/skill-suggestions/*` в самостоятельный
Python backend без потери правил навыков, валют, grounding и нормализации результата.
FitCheck работает только как сайт. Backend владеет prompts, model policy, ключами,
калибровочной памятью и учётом каждого физического вызова провайдера.

ANY-648 предоставляет прикладные сервисы для будущего worker. Durable jobs,
leasing, admission/quota и публикация analysis/history — ANY-649/650/651.
Подключение сайта и отключение старых Next.js LLM routes — ANY-653.
В этой задаче не добавляются синхронные публичные LLM endpoints в обход будущих jobs.
Нынешние job endpoints остаются planned, а website flow продолжает работать до интеграции.

## Выбранный подход

Использовать LiteLLM SDK внутри собственного `ProviderGateway`, PydanticAI — внутри
собственного structured executor. Это соответствует принятому ADR и локальному
эталону `anytoolai-platform/docs/architecture/llm-runtime.md`.
FitCheck не импортирует platform packages и не зависит от platform runtime/БД.

Прямой OpenAI SDK потребовал бы отклонения от критерия задачи. Отдельный LiteLLM Proxy
добавил бы сервис без текущей необходимости. Поэтому обе библиотеки остаются
внутри процесса и за собственными интерфейсами.

Поток: application service → structured executor/PydanticAI → ProviderGateway →
LiteLLM → DeepSeek. На возврате выполняются schema validation, domain grounding,
нормализация и финальная проверка DTO. Успешный provider response сам по себе
не является успешным Fit-анализом.

## Модули и интерфейсы

- `llm/policy.py`: неизменяемые server-owned версии policy, provider/model,
  лимиты токенов/времени/повторов. Model string используется только здесь.
- `llm/gateway.py` и provider adapter: транспорт, safe errors, физические попытки,
  ledger и явные transport retries; SDK imports ограничены этой границей.
- `llm/structured.py`: PydanticAI model adapter через gateway, typed output и
  semantic correction. Не вызывает провайдера вне gateway.
- `analysis/`: порт prompts, currency comparison, strength evidence, report audit,
  normalization и application service.
- `skill_suggestions/`: prompt и нормализация до десяти уникальных навыков.
- Storage repositories: owner-scoped calibration memory и provider-call ledger.

Вход анализа — доверенный owner context, выбранная immutable profile revision,
валидированная отредактированная Vacancy и locale. Сервис читает профиль и memory
по этому owner; не принимает пользовательский memory, provider, model или prompt.
Внутренние контексты вызовов допускают `job_id=None` для тестирования сервиса;
будущий worker передаёт принадлежащий тому же owner job. Проверка ownership
выполняется до вызова провайдера.

Результат сервиса содержит FitAnalysis и AnalysisSnapshot с фактически использованными
profile/revision/vacancy/locale и prompt/schema/policy versions. Публикация результата
в analyses выполняется будущим worker; ANY-648 не помечает jobs успешными самостоятельно.
Suggestions используют specialization/locale и возвращают нормализованные skills.

## Сохранение продуктовой логики

Переносятся текущие deterministic regression cases ANY-567/568/571/572:

- Basic skills не становятся доказанными профессиональными сильными сторонами.
  Unspecified proficiency остаётся неизвестной.
- Strengths выбираются моделью только как уникальные IDs разрешённых фактов.
  Пользовательский текст и `strengthEvidence` строятся сервером по выбранным IDs.
- Общий стаж не доказывает опыт с конкретной технологией. Технологии задачи
  не являются навыками пользователя. Язык генерируемого контента не означает
  требование владеть этим языком.
- Hourly rate сравнивается только при известных одинаковых валютах и известном
  hourly maximum. Fixed budget без оценки трудозатрат несопоставим с hourly rate.
  Неизвестная валюта и отсутствующий бюджет не считаются несовпадением.
- Отдельный grounding audit проверяет label/summary/risks по исходным profile/task.
  Неподдержанные утверждения требуют коррекции; неустранённые — invalid_output.
- Verdict вычисляется сервером: score ≥ 70 → GO, иначе NO_GO.
  Новые результаты содержат `verdictThreshold: 70`; поле optional для старых записей.
- Monthly income не входит в prompts, memory или вычисления.

Vacancy уже допускает nullable competition fields и provenance после ANY-647.
Они сохраняются в snapshot; расчёт влияния конкуренции остаётся ANY-575.
FitAnalysis допускает nullable `fitCondition` (текст до 300 символов), но ANY-648
его не генерирует: подтверждение и продуктовая логика условия остаются ANY-576.
Отсутствие новых полей в старых JSON payloads остаётся допустимым.
Текущая storage schema version `fitcheck.analysis.v1` сохраняется для этих
обратно совместимых добавлений; prompt/policy имеют собственные версии.

Memory читается из последних десяти анализов owner, отсортированных по created_at
и id по убыванию, с LEFT JOIN его annotation. В prompt передаются title,
predicted/corrected score и ограниченный note; чужая история и произвольный
client memory исключены. Memory не доказывает факты о текущей вакансии.
Все строки profile/task/memory/validation feedback трактуются как недоверенные данные.

## Provider policy, повторы и пределы

Начальная server policy использует DeepSeek и текущую модель сайта
`deepseek-v4-flash`. Ключ — SecretStr в backend settings; никакого ключа в DTO,
OpenAPI, browser bundle, exceptions или логах. Отсутствие ключа не мешает
foundation/API startup; LLM service возвращает safe unavailable до сетевого вызова.
Нужные adapters/clients переиспользуются и закрываются через lifecycle.

Для каждой structured operation: до двух semantic attempts и до двух transport
attempts на semantic attempt. LiteLLM `num_retries=0`; retries вложенного provider
SDK также выключены. Автоматические fallback models, external tracing и SDK
телеметрия с содержимым отключены.

Анализ содержит generation и grounding audit: общий hard cap — восемь физических
вызовов, включая correction и audit retries. Suggestions — четыре вызова.
Лимит проверяется до каждого вызова и общий для всей application operation.
Одна физическая попытка — максимум 45 секунд; общий deadline анализа — 120 секунд,
suggestions — 60 секунд. Каждый timeout и retry backoff ограничен остатком общего
deadline; при исчерпании времени следующая попытка не начинается.
Generation max output tokens — 1200, audit — 1000, suggestions — 500.

Transport retries относятся к timeout/network/429/5xx, с ограниченной задержкой и
учётом Retry-After в пределах deadline. Невосстановимые 4xx не повторяются.
Semantic retries относятся к JSON/schema/domain validation и неподдержанному report.
PydanticAI владеет structured validation/correction; доменные validators подают
обратную связь в этот механизм. Gateway не пытается исправлять JSON.

## Учёт и сохранение версий

Перед каждой физической попыткой отдельно коммитится `provider_calls.state=started`.
Если ledger не записан, provider не вызывается. После вызова отдельно сохраняются
tokens/cost/latency/status и safe error code. Эти транзакции не откатываются вместе
с неудачным анализом. На время сетевого вызова DB transaction/connection не удерживается.

Ledger получает additive migration `0002`: prompt/schema/policy versions,
semantic/transport attempt indices и latency_ms. Старые строки допускают отсутствие
этих metadata. `attempt` остаётся физическим порядковым номером operation.
Уникальный request_key включает server-generated operation UUID и attempt;
owner/job ссылки сохраняют текущие ownership/delete правила.

Tokens и cost неизвестной попытки остаются null, а не нулём. Cost берётся из
доступной проверенной provider/SDK usage pricing metadata; если невозможно получить
надёжную стоимость, cost/currency остаются null. Latency измеряется monotonic clock.
Транспортный успех с invalid output учитывает фактическую usage, но отмечается failed
с validation error; итоговый результат не создаётся. Ошибка завершения ledger после
вызова прекращает operation, повтор автоматически не запускается; started остаётся
сигналом неопределённого исхода для будущего reconciliation в ANY-649/654.
Сырой request/response, profile, vacancy, memory и provider exception messages
не записываются в технический ledger/логи.

## Проверка и доставка

Обязательны pure regression tests prompts/currency/grounding/skill normalization,
mock provider tests malformed JSON/schema/audit/retries/deadlines/call caps,
hidden-retry guards, отсутствия утечки ключей и import boundaries.
PostgreSQL integration проверяет owner-scoped memory, каждый ledger attempt,
сохранение failed attempts при rollback, bootstrap/upgrade/schema drift и
совместимость старых snapshots/analyses с optional новыми полями.

Live canary отдельный opt-in: запускается только с явно доступным ключом и
маленьким набором обезличенных fixtures; deterministic suite не зависит от DeepSeek.
Без ключа canary считается skipped, а не passed. CI проверяет экспорт OpenAPI,
generated TypeScript и весь backend/site набор. Миграция применяется перед рестартом
dev API; reset БД для этой additive migration не нужен. Функциональные вызовы сайта
переключаются только после ANY-649/653.
