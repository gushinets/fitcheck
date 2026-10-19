import { BackendApiError, BackendTransportError } from "@/lib/backend/client"
import { WebsiteServerError } from "./server"
import type { Locale } from "@/lib/types"

const messages: Record<string, [string, string]> = {
  unauthenticated: ["Your session expired. Sign in again.", "Сессия истекла. Войдите снова."],
  session_changed: ["The account changed. Reload the page.", "Аккаунт изменился. Обновите страницу."],
  invalid_credentials: ["Incorrect email or password.", "Неверный email или пароль."],
  registration_conflict: ["This email is already registered. Sign in.", "Этот email уже зарегистрирован. Войдите в аккаунт."],
  email_not_verified: ["Verify your email to continue.", "Подтвердите email, чтобы продолжить."],
  invalid_token: ["This code is invalid or expired. Request a new email.", "Код неверен или истёк. Запросите новое письмо."],
  quota_exceeded: ["Your analysis limit is reached. Try later or sign in after a demo.", "Лимит анализов исчерпан. Попробуйте позже или войдите после демо."],
  budget_exceeded: ["The service limit is reached. Try later.", "Лимит сервиса исчерпан. Попробуйте позже."],
  rate_limited: ["Too many requests. Try again shortly.", "Слишком много запросов. Попробуйте чуть позже."],
  profile_revision_conflict: ["Your profile changed on another device. Reload before saving again.", "Профиль изменён на другом устройстве. Обновите страницу перед сохранением."],
  conflict: ["The data changed. Reload and try again.", "Данные изменились. Обновите страницу и повторите попытку."],
  not_found: ["This job or result is no longer available. Start a new analysis.", "Задача или результат больше недоступны. Начните новый анализ."],
  poll_timeout: ["The job is still pending. Use Retry to continue waiting without starting another analysis.", "Ожидание затянулось. Нажмите «Попробовать снова», чтобы продолжить без нового анализа."],
  timeout: ["Processing timed out. Try again.", "Время обработки истекло. Попробуйте снова."],
  invalid_request: ["Check your input. New passwords need at least 15 characters.", "Проверьте данные. Новый пароль должен содержать не менее 15 символов."],
  forbidden: ["The request could not be authorized. Reload the page.", "Запрос не авторизован. Обновите страницу."],
  invalid_output: ["The service returned an invalid result. Try again.", "Сервис вернул некорректный результат. Попробуйте снова."],
}
export function serverErrorMessage(error: unknown, locale: Locale): string {
  if (error instanceof BackendTransportError && error.reason === "network") return locale === "ru" ? "Не удалось связаться с сервером. Попробуйте снова." : "Could not reach the server. Try again."
  const code = error instanceof BackendApiError || error instanceof WebsiteServerError ? error.code : ""
  return messages[code]?.[locale === "ru" ? 1 : 0] ?? (locale === "ru" ? "Не удалось выполнить запрос. Попробуйте снова." : "Could not complete the request. Try again.")
}
