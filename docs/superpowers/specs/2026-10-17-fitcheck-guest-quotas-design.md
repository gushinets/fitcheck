# ANY-651 — гостевой демо-анализ, квоты и перенос в аккаунт

Дата: 2026-10-17. База: `c4d5d80` (`ANY-650`).

## Согласованная цель

Посетитель сайта может выполнить один демо-анализ до регистрации. Гостевая
сессия действует 24 часа; после расходования демо нужен вход в аккаунт.
Оба значения конфигурируются на сервере и доступны клиенту через API.
После входа результат переносится в аккаунт; существующий профиль аккаунта
не перезаписывается, пустой заполняется гостевым профилем.

Пользователь согласовал использование текущего backend и PostgreSQL,
атомарное резервирование, возврат продуктовой квоты при ошибке, независимый
учёт технических расходов и безопасный перенос при владении обеими сессиями.
Эта спецификация уточняет техническую реализацию и предлагаемые начальные
лимиты; перед реализацией требуется её отдельное согласование.

UI демо и интеграция сайта остаются в ANY-579/653. Работа не включает платежи,
подписки, Redis/Celery, CAPTCHA, изменение модели OpenAI или устранение
неисправного TLS общей панели Dokploy. Изменения не затрагивают файлы `.env`
с реальными секретами и не запускают платные canary-запросы.

## Текущее состояние и выбранный подход

В БД уже есть `Owner`, `Guest`, `QuotaBucket`, `QuotaReservation`, immutable
профили/ревизии, durable jobs и provider ledger. HTTP-сессии, admission и
чтение jobs сейчас работают только для verified account. `CallBudget` ограничивает
вызовы в памяти одного запуска, но не расходы и суммарные попытки после
восстановления worker. Гостевые endpoints в OpenAPI пока planned.

Расширяем эти механизмы, сохраняя PostgreSQL единственным координатором.
Отдельный параллельный pipeline демо дублировал бы worker и публикацию;
Redis добавил бы инфраструктуру и вторую транзакционную границу.

Application services отвечают за identity, политики и единицы работы;
repositories выполняют SQL в переданной транзакции. HTTP handlers не принимают
ownerId/guestId как доказательство владения и не содержат доменные правила.

## Сессия и выбор identity

Добавить таблицу гостевых сессий с owner FK, уникальным digest случайного
256-битного токена, сроком действия и временем отзыва. Исходный токен хранится
только в HttpOnly cookie `__Host-fitcheck_guest` для production HTTPS;
для локального HTTP используется отдельное имя без `__Host-`.
Параметры: Secure в production, SameSite=Lax, Path=/, без Domain.

`POST /v1/guest-sessions` требует trusted Origin и существующий auth bootstrap
CSRF. Валидная неприсвоенная сессия переиспользуется без продления абсолютного
TTL и без новой квоты. Создание новой сессии ограничено по HMAC IP digest в БД.
Ответ содержит guest CSRF token, expiresAt и видимую политику демо.

Guest CSRF выводится HMAC из токена с отдельным scope. В мутациях гость передаёт
его в `X-CSRF-Token`. Токены не попадают в URL, логи или JSON storage payload.
Просроченная/отозванная сессия не разрешает чтение результатов и новые операции.

Для анализа identity выбирается явно по `mode=account|guest`; наличие обеих
cookie не позволяет перейти на другую identity после ошибки авторизации.
Для extraction/suggestions/quota и чтения job/detail добавить явный необязательный
selector `mode=account|guest`: по умолчанию account при наличии account cookie,
иначе guest. Невалидная выбранная cookie не даёт fallback на другую сессию.
Account по-прежнему требует подтверждённый email. Bearer-токены не поддерживаются.
Гость читает только свои jobs и детали результата; history/feedback/status/reanalysis
остаются account-only.

Очистка cookie не даёт строгую идентификацию человека: независимые IP/session
rate limits и технические бюджеты ограничивают злоупотребления, но не обещают
один бесплатный анализ на физического человека.

## Продуктовые квоты и предлагаемые значения

Начальные значения ниже — конфигурируемые defaults, не тарифные обязательства:

| Операция | Гость за срок сессии | Verified account за сутки UTC |
| --- | --- | --- |
| Analysis, включая account reanalysis | 1 успешный результат | 20 |
| Skill suggestions | 5 успешных результатов | 50 |
| Extraction URL/text | 10 успешных ответов | 100 |
| Одновременно queued/running jobs | 1 | 2 |

Гостевые лимиты истекают вместе с сессией и не обновляются внутри неё.
Account-окна фиксированы по UTC, прежняя reservation сохраняет своё окно даже
после наступления следующих суток. Claim не добавляет account credits и не
переносит guest quota buckets в account.

Начальные rate limits: создание гостя 3/IP/час и 10/IP/сутки; guest jobs
5/guest/минуту и 30/IP/15 минут; guest extraction 10/guest/минуту и
60/IP/15 минут. Для account сохраняются существующие jobs/extraction limits.
Лимиты создания сессий и значимые продуктовые лимиты задаются Settings и
валидируются положительными ограниченными числами. IP определяется только
через существующую конфигурацию trusted proxies, без доверия произвольному XFF.
Общий proxy IP может объединять посетителей: это документируется, прокси-доверие
на сервере не расширяется автоматически.

`GET /v1/quota` сохраняет existing remaining/resetsAt для анализа и дополнительно
возвращает mode, expiresAt, registrationRequired, лимиты/remaining/reserved для
analysis/extraction/suggestions и activeJobs/maxActiveJobs. Для гостя
registrationRequired=true при отсутствии свободного analysis slot, включая
reservation; клиент различает reservation и окончательное исчерпание.

## Admission, settlement и восстановление

В одной транзакции проверить активную выбранную сессию, owner и состояние claim,
найти идемпотентный повтор, проверить active jobs, зарезервировать продуктовую
квоту и создать job с frozen input. Тот же ключ и нормализованный запрос
возвращают существующий job до повторного списания. Другой запрос конфликтует.

Успех job переводит reservation в consumed в одной транзакции с публикацией
результата; terminal failure переводит в released. Lease recovery, технический
retry и повтор HTTP не создают новую продуктовую reservation. Все terminal paths,
включая исчерпание worker attempts и отмену при истёкшей сессии, используют общий
идемпотентный settlement. Старый lease не может опубликовать результат или
повторно списать/вернуть квоту.

Для синхронной extraction добавить reservation операции с TTL и атомарными
счётчиками: reserve до сетевого запроса, consume при успехе, release при ошибке.
Зависшие extraction reservations освобождаются ограниченными идемпотентными
пакетами при последующих admission/quota запросах. Rate-limit попытки сохраняются
независимо от rollback бизнес-транзакции, как в текущем auth limiter.

Гостевой профиль из analysis request сохраняется отдельной immutable revision.
Worker получает server-owned frozen revision/profile/vacancy/locale, пустую guest
calibration memory и закреплённые версии. Public guest DTO не требует revision.
Ввести versioned envelope v2 с отдельной frozen profileRevision, не удаляя чтение
v1 для уже существующих account jobs. Snapshot использует серверную revision;
владение профилем/результатом проверяется composite FK.

При истёкшем TTL worker не начинает новые физические LLM-вызовы гостя.
Уже отправленный запрос учитывается; публикация результата остаётся атомарной,
но гостевой доступ после expiry не восстанавливается. Данные удаляются отдельной
retention-политикой; ANY-651 не создаёт новый глобальный scheduler.

## Ограничения технических расходов

Отдельные persisted reservations бюджетов ограничивают физические обращения
перед отправкой провайдеру, включая generation, audit, transport retries и
повторный запуск после утраты lease. Счётчики не сбрасываются при terminal failure
или возврате продуктовой квоты. Это отличает бесплатный результат от расходов.

Предлагаемые default ceilings:

| Scope | Analysis | Suggestions |
| --- | --- | --- |
| Physical calls на job, суммарно по всем worker attempts | 8 | 4 |
| Суммарный input+output token ceiling на job | 40 000 | 10 000 |
| USD ceiling на job | 0.02 | 0.005 |

Дополнительно: guest session USD ceiling 0.05, account/day 0.50,
общий backend/day 10.00 USD. Все ceilings настраиваются и фиксируются для
operation/job; последующее изменение настроек не расширяет уже принятый бюджет.
Имеющиеся per-call output caps и deadlines остаются верхними пределами.

Перед каждым платным вызовом под row locks резервировать верхнюю границу токенов
и стоимости одновременно для job, owner window и deployment window. Для input
использовать поддерживаемый server-side tokenizer для закреплённой модели,
учитывая system/user/schema/framing, с консервативным запасом. Если надёжная
верхняя граница неизвестна, запрос отклоняется до отправки; не считать неизвестные
токены/цену нулём. Верхняя стоимость вычисляется текущим backend pricing module
для поддерживаемого Standard/global text режима, без скидки за предполагаемый cache.
После ответа известное фактическое использование освобождает только доказанно
неиспользованный резерв; unknown/cancelled/process_lost удерживают верхнюю оценку
до конца окна. Accounting ledger сохраняет actual/unknown отдельно от admission
резерва и не выдаёт ceiling за измеренный расход.

Ledger admission проверяет live lease и общий call cap в той же транзакции.
Reconciliation и завершение вызова используют единый порядок блокировок бюджетов.
При crash после reservation, но до отправки, резерв сохраняется консервативно.
Отсутствие поддерживаемой ценовой политики/usage не открывает обход лимитов.
Ошибка превышения — стабильный `budget_exceeded`; исчерпание продукта —
`quota_exceeded`, оба с HTTP 429 при admission. В terminal job — тот же typed code.
Никаких новых реальных платных вызовов в тестах или rollout smoke.

## Безопасный claim

`POST /v1/guest-claims` требует одновременно verified account session и валидную
непросроченную guest session, trusted Origin, account `X-CSRF-Token`,
guest `X-Guest-CSRF-Token` и `Idempotency-Key`. Добавить отдельный CORS header.
Повтор того же ключа/гостя в том же аккаунте воспроизводит сохранённый результат;
другой guest с тем же ключом даёт 409. Claim другим аккаунтом запрещён.

Owners блокируются в стабильном UUID-порядке, затем account user, guest/session,
jobs и quota rows по согласованному порядку. Pending guest jobs или незавершённая
extraction дают 409, позволяя повтор после завершения. Claim не прерывает работу
worker и не меняет ownership активного lease.

В caller UoW использовать существующий transfer_guest_analyses для terminal jobs,
результатов, вакансий, аннотаций и provider accounting. Если у аккаунта нет профиля,
создать его первую revision из последнего сохранённого гостевого профиля.
Существующий профиль, preferences/draft аккаунта не менять. Перенесённые результаты
сохраняют исходный snapshot; их comparison остаётся unknown при отсутствии
account revision FK, как предусмотрено ANY-650.

Сохранить claim receipt и запретить дальнейший guest admission. Guest session
после claim разрешает только идемпотентное воспроизведение claim для того же
account; результаты доступны уже через account identity. TTL остаётся абсолютным,
повтор claim не продлевает доступ. Конфликт idempotency keys существующих account
и guest jobs откатывает весь перенос с 409 ownership_conflict, без переименования
immutable job keys. Конфликт явно возвращается клиенту; повтор того же конфликтующего запроса
не считается способом его исправления. Автоматическое слияние несовместимых
ключей в эту задачу не входит.

## Хранение, контракты и совместимость

Добавить additive migration `0008_guest_quotas`: guest sessions, claim receipts,
extraction reservations, persisted budget windows/reservations/call links и
необходимые bounded checks/indexes. Existing `0001`–`0007` не изменять.
Использовать существующие quota tables для job product reservations. Новые FK
и cleanup согласовать с account deletion, guest transfer и anonymous ledger
retention. В migration tests проверить upgrade, metadata drift и wheel packaging.

Реальные routes заменяют planned OpenAPI operations; поддержать существующие
account запросы без изменения их mode по умолчанию. Сгенерировать OpenAPI и
TypeScript заново. Гость получает доступ к extraction, suggestions, job polling,
analysis detail и quota, но не к account history/profile mutation/annotations.
API DTO не раскрывают provider keys, prompts, budget ledger internals или raw IP.

Старые account jobs без новых budget envelopes worker исполняет с безопасной
server default budget, создаваемой атомарно до первого физического вызова.
Старые продуктовые квоты задним числом не списываются. Новые guest envelopes
и migration требуют совместимого worker: rollout предусматривает паузу admission,
миграцию, API/worker, проверку готовности и затем включение guest admission.
Проверка схемы exact-head не допускает rollback на backend image с head 0007
после применения 0008; восстановление — совместимым образом либо repair forward.
Автодеплой и неполная TLS-цепочка панели не считаются доказательством rollout.

## Обязательные проверки

- Guest bootstrap/CSRF, expiry/reuse, forged/revoked cookie, отсутствие fallback,
  обе cookie одновременно, account email verification, Origin и CORS.
- Одна свободная квота и два параллельных admission: один job/reservation;
  idem replay не списывает квоту, другой payload конфликтует.
- Success consume, terminal failure release, повтор settlement, UTC rollover,
  lease recovery и старый worker не меняют reservation дважды.
- Extraction concurrency, timeout/crash cleanup, ограничение по IP/session,
  недоступная БД не разрешает запрос.
- Persisted call/token/USD limits на generation/audit/retries/recovery;
  параллельные calls не превышают окно, unknown usage удерживает резерв,
  rejected admission не отправляет запрос провайдеру.
- Два аккаунта и два гостя: чужие jobs/detail недоступны; claim требует обе
  сессии; параллельные claims имеют одного владельца и один receipt.
- Claim переносит результат/profile в пустой account, сохраняет заполненный
  account profile и immutable snapshots; pending jobs/idem collisions дают
  полный rollback; guest не получает новую квоту после claim.
- Account deletion и history clear совместимы с новыми FK, reservations и receipt;
  не остаётся персональных ссылок в retained accounting.
- Полный backend suite с disposable PostgreSQL, OpenAPI validation/drift,
  generated TypeScript check/typecheck, client tests и обе container builds.

## Последовательность реализации после согласования

1. Additive storage/contracts и проверяемые settings/defaults.
2. Guest identity/CSRF и identity-aware reads без изменения account-only history.
3. Product quota service, atomic admission, extraction и все settlement paths.
4. Persisted technical budgets в ledger/gateway, включая worker recovery.
5. Claim orchestration с копированием профиля в пустой account.
6. Полная проверка совместимости, review, документация и отдельное подтверждение
   фактического dev rollout, если он будет выполнен.

Следующий артефакт — подробный implementation plan после одобрения этой
спецификации. Продуктовый код до этого не меняется.
