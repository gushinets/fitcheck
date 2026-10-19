import { describe, expect, it, vi } from "vitest"
import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ServerWebsite } from "@/lib/web/server"
import { ServerAccountTools } from "./server-account"

describe("account data refresh", () => {
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
