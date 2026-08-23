import { browser } from "wxt/browser"
import { parseUpworkJob, scrollToApplyAction } from "@/lib/upwork/parser"
import type { UpworkContentMessage } from "@/lib/upwork/messages"

export default defineContentScript({
  matches: [
    "https://www.upwork.com/jobs/*",
    "https://www.upwork.com/ab/proposals/job/*",
  ],
  runAt: "document_idle",
  main() {
    browser.runtime.onMessage.addListener((message: unknown) => {
      const contentMessage = message as UpworkContentMessage
      if (contentMessage.type === "GET_CURRENT_JOB") {
        return Promise.resolve(parseUpworkJob(document, location.href))
      }
      if (contentMessage.type === "SCROLL_TO_APPLY") {
        return Promise.resolve(scrollToApplyAction(document))
      }
      return undefined
    })
  },
})
