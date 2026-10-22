import { describe, expect, it, vi } from "vitest"
import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ServerWebsite } from "@/lib/web/server"
import { createServerWebsite } from "@/lib/web/server"
import { ServerAccountTools } from "./server-account"

describe("account data refresh", () => {
  it.each([
    { locale: "en" as const, claim: "Save demo to account", retry: "Reload account data", success: "Demo saved to your account." },
    { locale: "ru" as const, claim: "Сохранить демо в аккаунт", retry: "Обновить данные аккаунта", success: "Демо перенесено в аккаунт." },
  ])("can reload after a completed claim's refresh fails in $locale without submitting another claim", async copy => {
    let claims = 0
    const server = createServerWebsite({ fetch: async url => {
      const path = String(url)
      if (path.endsWith("auth/csrf")) return Response.json({ csrfToken: "bootstrap" })
      if (path.endsWith("guest-sessions")) return Response.json({ csrfToken: "guest-proof" })
      if (path.endsWith("auth/login")) return Response.json({ user: { id: "user", email: "test@example.com", emailVerified: true }, csrfToken: "account-proof" })
      if (path.endsWith("guest-claims")) { claims++; return Response.json({ claimedCount: 1, profileImported: true }) }
      throw new Error(`Unexpected request: ${path}`)
    } })
    await server.createGuest()
    await server.repository.authenticate("test@example.com", "test-password")
    const refresh = vi.fn().mockRejectedValueOnce(new Error("Connection lost")).mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<ServerAccountTools server={server} locale={copy.locale} refresh={refresh} />)
    await user.click(screen.getByRole("button", { name: copy.claim }))
    expect(await screen.findByRole("status")).not.toHaveTextContent(copy.success)
    expect(server.hasGuestClaim()).toBe(false)
    await user.click(screen.getByRole("button", { name: copy.retry }))
    expect(await screen.findByRole("status")).toHaveTextContent(copy.success)
    expect(screen.queryByRole("button", { name: copy.retry })).not.toBeInTheDocument()
    expect(claims).toBe(1)
    expect(refresh).toHaveBeenCalledTimes(2)
  })
  it.each(["claim", "import"] as const)("confirms %s only after the refreshed account is ready", async operation => {
    let finishRefresh!: () => void
    const refreshed = new Promise<void>(resolve => { finishRefresh = resolve })
    const refresh = vi.fn(() => refreshed)
    const server = {
      hasGuestClaim: () => operation === "claim",
      claimGuest: vi.fn().mockResolvedValue(undefined),
      importLocal: vi.fn().mockResolvedValue({ importedCount: 1, skippedCount: 0, conflictCount: 0, invalidCount: 0 }),
    } as unknown as ServerWebsite
    const user = userEvent.setup()
    render(<ServerAccountTools server={server} locale="en" refresh={refresh} />)
    if (operation === "import") {
      await user.type(screen.getByLabelText("Local account email"), "legacy@example.com")
      await user.type(screen.getByLabelText("Local account password"), "test-password")
    }
    await user.click(screen.getByRole("button", { name: operation === "claim" ? "Save demo to account" : "Import / retry" }))
    await waitFor(() => expect(refresh).toHaveBeenCalledOnce())
    expect(screen.queryByRole("status")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Importing…" })).toBeDisabled()
    await act(async () => { finishRefresh(); await refreshed })
    expect(await screen.findByRole("status")).toHaveTextContent(operation === "claim" ? "Demo saved to your account." : "Imported: 1;")
  })
})
