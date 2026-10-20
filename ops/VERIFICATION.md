# ANY-654: локальная проверка, 2026-10-19

Проверено на macOS с Docker Desktop/PostgreSQL 17 и Python 3.12.
Docker-сайт собран на Node.js 22; локальные frontend-проверки — на Node.js 26.7.0.
Рабочая база и приложения Dokploy не изменялись.

| Проверка | Результат |
| --- | --- |
| Backend unit/contract и установка wheel | 550 passed, 2 skipped |
| Полный PostgreSQL integration, включая ownership/concurrency/recovery | 323 passed, 3 skipped |
| Дополнительный новый тест защиты нерассчитанного provider reserve и остальные ops-тесты | 5 passed |
| Повторная проверка HTTP jobs/import после корреляции логов | 22 passed |
| Frontend Vitest | 410 passed, 3 существующих skipped |
| Playwright: demo→verify→claim→reload→второй браузер→изоляция; повтор импорта | 2 passed |
| Production Next.js build, TypeScript, ESLint | passed |
| OpenAPI и сгенерированный TypeScript drift | passed |
| Alembic schema drift на тестовой БД | No new upgrade operations detected |
| `python3 ops/smoke.py` | passed |
| `git diff --check` | passed |

Docker smoke собрал API, worker и standalone-сайт, запустил однократную миграцию,
проверил готовность и HTTP сайта, приватные API/worker metrics, конфиг и правила
Prometheus. Затем создал тестовую строку, сделал pg_dump, восстановил архив в новую
БД, проверил строку и схему, удалил проверочную БД. Повреждённый архив отклонён по
checksum без обновления restore timestamp. Проверены dry-run очистки, health после
рестарта worker и сохранность исходной строки. Все тестовые контейнеры/тома удалены.

Backend skips: native Windows mutex timeout (запускается отдельной Windows CI job)
и платные live LLM canary, требующие явного `FITCHECK_RUN_LLM_CANARY=1` и ключа.
Browser E2E использует настоящий API/PostgreSQL и детерминированный executor.
Реальный SMTP, платный провайдер, S3 upload/download и доставка оповещения до
получателя этим прогоном не проверялись. Нагрузочный RTO на production-объёме не измерен.

В CI добавлены jobs `operations` и `website-e2e`. Workflow подготовлен локально;
результаты выше относятся к локальным запускам, запуск GitHub Actions не заявляется.
Для первого удалённого push workflow нужен GitHub credential с правом `workflow`
(использовавшийся ранее OAuth-токен отклонял изменения `.github/workflows/ci.yml`).
