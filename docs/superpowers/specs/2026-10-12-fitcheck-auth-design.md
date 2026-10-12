# FitCheck: серверная авторизация и изоляция аккаунтов

Дата: 2026-10-12. Задача: ANY-645, родитель ANY-531. Статус: дизайн в чате согласован; письменная спецификация ожидает проверки пользователя.

## Цель и согласованные ограничения

FitCheck получает собственную серверную identity вместо доверия email, userId или digest пароля из IndexedDB. Пользователь регистрируется, входит, подтверждает email, восстанавливает доступ и удаляет аккаунт; web и расширение используют разные серверные сессии. Чужие данные недоступны даже при известном идентификаторе ресурса. Backend, БД и секреты принадлежат только FitCheck; anytoolai-platform остаётся архитектурным ориентиром.

Пользователь согласовал собственную password auth с Argon2id, cookie/CSRF для web, одноразовые токены и PKCE для расширения. SMTP-настройки будут предоставлены позже: сейчас реализуем настоящий SMTP-adapter и проверяем его изолированно, без фиктивной отправки писем на сервере. Постоянная PostgreSQL 17 уже создана в Dokploy development, storage schema находится на ревизии 0002.

ANY-645 реализует backend и экспортированные контракты. Переключение существующих web/extension UI и локальных репозиториев принадлежит ANY-653; импорт локальных данных — ANY-652. Не добавляем OAuth-провайдера, MFA, social login, смену email, JWT или Redis. Гостевые сессии и claim HTTP принадлежат ANY-651. Реальные profile/job/history/import endpoints останутся своим задачам: здесь создаём общие зависимости доступа и проверяем их на существующих storage-графах, без успешных заглушек маршрутов.

## Компоненты и границы

`auth/` содержит password hashing, генерацию и digest токенов, CSRF, rate limiter, SMTP-adapter и прикладной AuthService. `storage/auth_repository.py` выполняет параметризованные запросы и блокировки. `api/auth.py` и `api/dependencies.py` преобразуют HTTP в команды сервиса и возвращают существующие DTO/error envelope. Handler не принимает caller-supplied owner_id как identity.

App factory создаёт runtime-ресурсы через lifespan: один storage engine и один ограничитель hashing concurrency на процесс; shutdown освобождает их. Unit/OpenAPI import остаётся возможным без БД и SMTP. `FITCHECK_AUTH_ENABLED` по умолчанию false: auth-маршруты существуют, но возвращают 503 при выключенной подсистеме. Включение требует валидных DB settings и auth secret; readiness при включении проверяет подключение и текущий migration head. Liveness не зависит от БД. SMTP readiness отображается отдельно и не маскируется как успешная готовность почтовых операций.

## Пользователи и пароли

Сервер нормализует email: удаляет наружные пробелы, приводит к нижнему регистру, проверяет синтаксис и длину до 254 символов. Не выполняет provider-specific преобразования точек/`+suffix`, не проверяет DNS во время входа. Используем одну валидирующую функцию для регистрации, входа, resend и reset.

Новые пароли и reset: 15–128 Unicode code points, без trim, принудительного изменения регистра, обязательных наборов символов и молчаливого усечения. Login/delete принимают 1–128 символов и проверяют ровно переданное значение. Это уточняет пока не реализованный контракт с общим минимумом 8: RegistrationCredentials и LoginCredentials разделяются, password везде writeOnly и не попадает в validation error values. Старые локальные credentials не импортируются и не доказывают владение email.

`argon2-cffi` использует явный Argon2id-профиль: memory_cost=65536 KiB, time_cost=3, parallelism=4, salt_len=16, hash_len=32. Hash включает случайную соль. Успешный вход обновляет устаревшие параметры через check_needs_rehash. Для отсутствующего пользователя проверяется заранее подготовленный dummy hash; неверный пароль и неизвестный email дают одинаковые 401 `invalid_credentials`. Не заявляем строгую константность времени всего HTTP-запроса. Одновременно исполняются максимум две hash/verify операции на процесс; hashing не удерживает открытый DB transaction.

Регистрация создаёт Owner/User, verify token и web session одной транзакцией. UserResource возвращает `emailVerified=false`. Повторный email даёт безопасный 409 `registration_conflict`, без возврата профиля/identity существующего пользователя. Ограничение раскрытия существования email: reset/resend одинаковы для известного и неизвестного email, но регистрационный контракт с 201/session сохраняет различимый duplicate 409; это явно принимаемый trade-off, а не обещание полной защиты от enumeration.

## Сессии и разрешения

Session token — случайные 32 байта, base64url без padding. БД хранит только SHA-256 digest и kind; произвольный JWT, userId, guestId, password digest и session id из тела не принимаются. Web session имеет абсолютный срок 7 дней, extension session — 1 час; автоматического продления GET-запросом нет. Повторный login выдаёт новый token и отзывает текущую web session браузера, сохраняя независимые сессии других устройств. Logout отзывает только текущую web session; extension revoke — текущую extension session. Reset пароля отзывает все сессии и extension authorization codes, не выполняет автоматический login.

Principal содержит проверенные user_id, owner_id, session_id, kind и email_verified. Разрешаем одновременно ровно один способ account authentication: cookie либо bearer; при наличии обоих запрос отклоняется, чтобы не выбрать другой аккаунт неявно. Bearer валиден только для extension-kind, cookie только для web-kind. Expiry/revocation проверяются на каждом запросе по серверному UTC и DB state, без долгоживущего кеша.

Неподтверждённый аккаунт может читать me/session, отправлять подтверждение, выйти и удалить себя. Выдача extension code и будущие profile/jobs/history/import account operations требуют verified-email principal; иначе 403 `email_not_verified`. Guest flow отдельно реализует ANY-651.

Общая функция загрузки owned resource фильтрует одновременно resource id и Principal.owner_id; отсутствующий и чужой ресурс дают одинаковые 404. Owner context нельзя создать из request DTO. Для хранения Profile/Job/Analysis/Annotation/ImportEntry тестируем корректного и чужого владельца; FK остаётся вторым уровнем защиты. Следующие сервисы обязаны использовать эту зависимость; наличие resolver в ANY-645 само по себе не реализует их HTTP-маршруты.

## Cookie, Origin и CSRF

Production cookie `__Host-fitcheck_session`: Secure, HttpOnly, SameSite=Lax, Path=/, без Domain. HTTP dev использует отдельное имя `fitcheck_session`; режим production никогда не отключает Secure. Ответы auth/session/token имеют Cache-Control: no-store. Raw session token не возвращается в web JSON.

После входа CSRF token вычисляется как HMAC-SHA256(auth_secret, отдельный namespace + raw session token), base64url; его digest соответствует сохранённому csrf_digest. Это позволяет `GET /v1/auth/session` вернуть SessionResource после перезагрузки страницы без хранения открытого CSRF token в БД. `GET /v1/me` сохраняет UserResource. У каждой новой сессии другой CSRF token. Сравнение digest выполняется constant-time.

`GET /v1/auth/csrf` — pre-login bootstrap: требует точного разрешённого web Origin, ставит подписанную HttpOnly cookie с random nonce и временем истечения через 15 минут; возвращает csrfToken. POST register/login требуют этот cookie и соответствующий X-CSRF-Token, включая проверку срока/signature. Ключ и namespace bootstrap отделены логически от session CSRF через HMAC derivation. Cookie имеет те же Secure/Path/SameSite правила и отдельное имя, после login/register очищается. Получить/подделать bootstrap другого браузера недостаточно для входа жертвы.

Все browser mutations проверяют обязательный Origin по точному allowlist. Authenticated web mutations дополнительно проверяют session CSRF. Reset/verify с bearer-like одноразовым токеном всё равно требуют разрешённый web Origin; GET по ссылке не потребляет token. Extension bearer mutations требуют разрешённый extension Origin, не требуют web cookie/CSRF. Отсутствующий, null, wildcard, несколько Origin, чужой Origin и Referer-only запрос отклоняются. CORS дополняет эти проверки, но не заменяет их.

## Письма и одноразовые токены

Verify email: 24 часа; reset password: 30 минут; extension code: 2 минуты. Токены — независимые случайные 32 байта; в auth_tokens хранится только digest. Purpose, expiry, consumed_at и соответствующий user проверяются сервером. Потребление и изменение пользователя атомарны: два одновременных confirm не могут успешно использовать один token. Новый reset/resend инвалидирует предыдущие токены того же purpose. Verify требует web session того же пользователя и session CSRF, включая неподтверждённый аккаунт; одна ссылка без входа не подтверждает предварительно зарегистрированный злоумышленником аккаунт. На другом устройстве пользователь сначала входит своим паролем. Verify не выдаёт новую сессию; после успеха существующий principal при следующем запросе видит обновлённое verification state. Reset остаётся public token flow: владелец почты может заменить пароль даже у неподтверждённого аккаунта, отозвав все чужие сессии.

MailSender — dependency с явными результатами sent/failed; production SMTP через standard-library smtplib, TLS certificate verification, timeout 10 секунд. Разрешены SMTPS либо обязательный STARTTLS, без plaintext fallback. Host/port/username/password/from берутся только из настроек; password SecretStr. Sender/from/header значения проверяются против CR/LF injection. Получатель — нормализованный email аккаунта, не произвольный адрес из токена. Ссылки строятся только из настроенного точного web base URL; Host/X-Forwarded-Host не используются. Token находится в URL fragment, дальнейшее UI потребление принадлежит ANY-653; логирование ссылок запрещено.

При отсутствии SMTP config регистрация, verify-email/request и password-reset/request возвращают одинаковый 503 `email_unavailable` до создания аккаунта или токенов, в том числе для неизвестного email. Login ранее созданных пользователей, session/me, logout, token confirm и deletion остаются доступны при auth enabled с обычной проверкой credential/Origin/CSRF. Production не включает console/fake mailer. Test MailSender доступен только через dependency injection из тестов и не выбирается environment flag.

Регистрация после настройки SMTP сначала фиксирует аккаунт/token, затем отправляет письмо вне DB transaction. При сбое доставки возвращает 503 без session cookie, созданная pending identity остаётся; пользователь повторяет вход и resend. Это явно документированный recoverable partial success. Не возвращаем 201 до успешной отправки. Sender не может атомарно участвовать в PostgreSQL transaction; SMTP acceptance не гарантирует доставку во входящие.

Для reset/resend при настроенном SMTP 204 означает принятие запроса без раскрытия существования email; это не подтверждение доставки. Для отсутствующего/уже подтверждённого email verify request остаётся no-op. Ошибки доставки не меняют внешний 204 на различимый ответ для существующего аккаунта, но регистрируют безопасный failure event без email/token/SMTP response; resend доступен после cooldown. Durable mail queue/автоматические delivery retries не входят в эту задачу и не имитируются. Reset с неверным/expired/consumed token даёт одинаковую 400 `invalid_token`.

## Вход расширения

POST authorize требует verified web session, Origin и CSRF, принимает exact redirectUri, codeChallenge S256 и state. Redirect URI должен полностью совпадать с настроенным HTTPS callback `https://<extension-id>.chromiumapp.org/<configured-path>`; без credentials/query/fragment, wildcard и автоматических редиректов. Пустой allowlist означает 403, не разрешение всем расширениям. Backend не делает HTTP redirect: возвращает code/state/expiresIn доверенному клиенту для запуска browser flow.

POST token проверяет extension Origin, digest code, exact сохранённый redirect, срок и SHA-256 verifier; потребление code и создание extension session атомарны. Code дополнительно связан с выдававшей web session: её revoke/expiry делает code недействительным. Для этого migration добавляет auth_tokens.issued_session_id, unique auth_sessions(id,user_id) и composite FK (issued_session_id,user_id) к auth_sessions(id,user_id) с CASCADE. Действующий extension-purpose требует non-null issued_session_id; остальные purpose требуют null. State возвращается ровно переданным; клиент обязан сравнить его перед обменом. Wrong verifier/redirect не потребляет code; лимит попыток ограничивает перебор. Одновременные успешные обмены невозможны.

Bearer предназначен только для account operations и не даёт доступ к web-only authorize/logout. Refresh token не выдаётся; повторный browser authorization создаёт новую часовую сессию. Token/request code never входит в path/query API-запроса или request log. Получение extension ID/настройка UI flow принадлежит интеграции; неизвестные origins не добавляются в allowlist автоматически.

## Rate limiting, транзакции и удаление

Новая auth_rate_buckets таблица хранит scope, HMAC subject digest, window_start, attempts и expires_at; уникальный composite key делает increment/check атомарными между процессами. Digest namespace зависит от route/scope и auth secret; raw IP/email не сохраняются. Лимиты fixed-window: login 10/email/15 минут и 60/IP/15 минут; register 5/IP/час; resend/reset request 3/email/час и 20/IP/час; verify/reset confirm/extension exchange 30/IP/15 минут; bootstrap 60/IP/15 минут; delete 5/user/15 минут. Превышение даёт 429 и Retry-After. Лимит учитывает попытку до hashing, сохраняется отдельной транзакцией независимо от rollback основной операции. Неизвестные email учитываются точно так же. При недоступности limiter/БД auth mutation возвращает 503, не обходит лимит.

Храним expiry лимитирующих buckets, удаляем ограниченными batches до 100 устаревших строк при новых попытках; это не заменяет будущий retention scheduler. Client IP берётся из ASGI peer; forwarded headers используются только при явной конфигурации доверенных proxy адресов на Uvicorn. Production запрещает доверие `*`; deployment runbook проверяет соответствие сети Dokploy. Если proxy trust не настроен, действуют общий proxy-IP лимит и отдельный email лимит, а не произвольный X-Forwarded-For.

Создание/отзыв сессии и потребление токенов используют consistent locking: owner до user, затем session/token rows. Hashing выполняется до блокировок; под блокировкой повторно проверяются наличие пользователя и неизменность проверенного password_hash, expiry/revocation/verification. Password reset, login, extension exchange и deletion не могут выдать новую действующую сессию на удалённую identity или по уже заменённому паролю. Никакого доверия stale ORM объекту.

DELETE /v1/me дополнительно требует текущий пароль в новом PasswordConfirmation DTO; для web также Origin/CSRF, для extension — exact Origin. После re-auth использует delete_owner, отзывает/каскадно удаляет все auth records и приватный account/claimed-guest graph, обезличивает provider ledger, очищает web cookie. 204 только после commit. Concurrent guest claim допускает безопасный rollback; service повторно перечисляет graph и повторяет операцию максимум три раза в новых transactions, после этого 409 `ownership_conflict`. Остальные integrity errors не трактуются автоматически как retry. Удаление чужого owner_id через JSON невозможно: extra fields отклоняются.

## Контракты и настройки

Реализуются все 11 ANY-645 operations из contracts/operations.py. Добавляются GET /v1/auth/csrf, GET /v1/auth/session и POST /v1/auth/verify-email/request. DELETE /v1/me получает обязательный PasswordConfirmation body; register получает RegistrationCredentials, login — LoginCredentials, reset новый password минимум 15. Verify-email меняет пока planned access public на web: принимает TokenRequest только с подходящей pending/verified session и CSRF. SessionResource/UserResource и error envelope сохраняют camelCase. Planned операции остальных задач остаются planned и отсутствуют в live runtime.

OpenAPI exporter должен распознавать фактически зарегистрированные операции, сохранять их реальный schema/response и правильный owning issue; больше не помечать все live routes ANY-643 и не перезаписывать реализованные auth routes planned описаниями. Экспортированные JSON и generated TypeScript регенерируются вместе. Добавляются нужные auth error codes и семантика 429 Retry-After без раскрытия деталей.

Настройки: AUTH_ENABLED, AUTH_SECRET (минимум 32 random bytes encoded hex), AUTH_WEB_BASE_URL, AUTH_EXTENSION_REDIRECT_URIS, ALLOWED_ORIGINS, SMTP_HOST/PORT/USERNAME/PASSWORD/FROM/SECURITY. Префикс FITCHECK_ сохраняется. Web base URL — точный origin с HTTPS в production, HTTP только dev. SMTP settings либо отсутствуют целиком, либо валидны целиком; secrets не попадают в repr/errors. Test clock/MailSender/password parameters инжектируются кодом, не production env overrides. TLS/proxy/allowlist конфигурация проверяется до включения auth.

## Миграции, проверки и доставка

Новая revision 0003 расширяет auth_tokens и создаёт auth_rate_buckets; 0001/0002 не редактируются. Сохранение existing users/sessions/verify/reset tokens проверяется при upgrade. Existing extension codes без issued_session_id получают consumed_at перед constraint validation: constraint допускает null issued_session_id только у уже consumed extension code, runtime всегда отклоняет такую запись. Отзыв одноразовых кодов является намеренной частью upgrade, password/users/session records сохраняются; metadata соответствует этому условию.

Unit tests проверяют hash/rehash, validation, purpose separation, crypto/signatures, cookie flags, SMTP STARTTLS/certificate policy и safe logging, email unavailable semantics, OpenAPI ownership/implementation states. SMTP-adapter испытывается fake transport на уровне socket/SMTP boundary; SMTP secrets позже проверяются реальным письмом по отдельному указанию пользователя.

PostgreSQL/HTTP integration tests с disposable *_test DB проверяют register/login/session/me/logout, refresh-page CSRF recovery, verification/resend/reset, two-account isolation, deletion graph/ledger, expiry и wrong-kind sessions, mixed credentials, bootstrap/login CSRF, exact origins, concurrent token consume/reset/login/deletion, PKCE replay/verifier/redirect/session binding и атомарный rate limit между независимыми соединениями. MailSender capture применяется только в тестах. Tests на реальной постоянной БД не запускаются.

Acceptance: новые сценарии и существующий suite проходят; OpenAPI/TypeScript drift и typecheck проходят; wheel/Docker сохраняют migration resources и non-root startup. На сервере explicit upgrade/check выполняются до включения auth. Без SMTP production register/mail requests дают ожидаемый 503; готовность полного email lifecycle не заявляется. Runtime smoke подтверждает реальную БД, безопасные отказы, CORS и отсутствие tokens в логах. Реальное подтверждение/восстановление через почту потребует предоставленных SMTP настроек, а browser UI — ANY-653.

## Источники решений

- [argon2-cffi: API и rehash](https://argon2-cffi.readthedocs.io/en/stable/api.html), [параметры](https://argon2-cffi.readthedocs.io/en/stable/parameters.html): Argon2id, явный профиль и проверка нагрузки.
- [OWASP Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html): password policy, throttling, re-authentication, одинаковые ошибки входа.
- [OWASP Forgot Password](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html): одноразовые expiring tokens и одинаковый внешний ответ request.
- [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html), [CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html): cookie attributes, session lifecycle и защита browser mutations.

Локальные основания: ADR 001; backend foundation/storage specs; ANY-645; runtime models/contracts; backend deployment record от 2026-10-12. Решения о TTL, лимитах и SMTP partial success являются проектными выборами FitCheck, а не нормативными сроками из источников.
