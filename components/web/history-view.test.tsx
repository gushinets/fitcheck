import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import { webMessages } from "@/lib/i18n/web-messages"
import type { WebHistoryEntry } from "@/lib/web/types"
import { HistoryView } from "./history-view"

const entry: WebHistoryEntry = {
  id: "entry-1",
  userId: "user-1",
  profile: defaultProfile,
  job: detectedJob,
  analysis: goAnalysis,
  createdAt: "2026-08-25T12:00:00.000Z",
}

describe("HistoryView", () => {
  it("opens a completed analysis and can request history clearing", async () => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    const onClear = vi.fn()
    render(
      <HistoryView
        entries={[entry]}
        locale="en"
        copy={webMessages.en}
        onOpen={onOpen}
        onClear={onClear}
      />,
    )

    await user.click(
      screen.getByRole("button", { name: /Senior Python Backend Developer/ }),
    )
    expect(onOpen).toHaveBeenCalledWith(entry)
    await user.click(screen.getByRole("button", { name: "Clear history" }))
    expect(onClear).toHaveBeenCalledOnce()
  })
})
