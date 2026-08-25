// @vitest-environment node

import { describe, expect, it, vi } from "vitest"
import {
  createPinnedLookup,
  fetchPublicPage,
  isPublicAddress,
  type NetworkDependencies,
} from "./network"

describe("public address policy", () => {
  it.each([
    "0.0.0.0",
    "10.0.0.1",
    "100.64.0.1",
    "127.0.0.1",
    "169.254.169.254",
    "172.16.0.1",
    "192.0.2.1",
    "192.168.1.1",
    "198.51.100.1",
    "203.0.113.1",
    "224.0.0.1",
    "::",
    "::1",
    "::ffff:127.0.0.1",
    "::ffff:7f00:1",
    "::ffff:a00:1",
    "2001:db8::1",
    "fc00::1",
    "fe80::1",
    "ff00::1",
  ])("blocks %s", (address) => {
    expect(isPublicAddress(address)).toBe(false)
  })

  it.each([
    "8.8.8.8",
    "93.184.216.34",
    "2001:4860:4860::8888",
    "2606:2800:220:1:248:1893:25c8:1946",
  ])("allows %s", (address) => {
    expect(isPublicAddress(address)).toBe(true)
  })
})

describe("fetchPublicPage", () => {
  it("returns an address array when Node requests all pinned DNS results", async () => {
    const lookup = createPinnedLookup({ address: "93.184.216.34", family: 4 })

    const result = await new Promise<unknown>((resolve, reject) => {
      lookup("jobs.example", { all: true }, (error, addresses) => {
        if (error) reject(error)
        else resolve(addresses)
      })
    })

    expect(result).toEqual([{ address: "93.184.216.34", family: 4 }])
  })

  it("rejects non-HTTP URLs and embedded credentials", async () => {
    await expect(fetchPublicPage("file:///etc/passwd", dependencies())).rejects
      .toMatchObject({ code: "invalid_url" })
    await expect(
      fetchPublicPage("https://user:password@example.com/job", dependencies()),
    ).rejects.toMatchObject({ code: "invalid_url" })
  })

  it("passes only validated DNS results to the pinned request", async () => {
    const request = vi.fn(async () => ({
      status: 200,
      headers: { "content-type": "text/html; charset=utf-8" },
      body: "<h1>Public role</h1>",
    }))

    const result = await fetchPublicPage(
      "https://jobs.example/role",
      dependencies({ request }),
    )

    expect(request).toHaveBeenCalledWith(
      new URL("https://jobs.example/role"),
      [{ address: "93.184.216.34", family: 4 }],
      expect.objectContaining({ maxBytes: 1_000_000 }),
    )
    expect(result.finalUrl).toBe("https://jobs.example/role")
    expect(result.body).toContain("Public role")
  })

  it("rejects a hostname when DNS includes a private address", async () => {
    await expect(
      fetchPublicPage(
        "https://jobs.example/role",
        dependencies({
          resolve: async () => [
            { address: "93.184.216.34", family: 4 },
            { address: "127.0.0.1", family: 4 },
          ],
        }),
      ),
    ).rejects.toMatchObject({ code: "blocked_address" })
  })

  it("revalidates every redirect target", async () => {
    const request = vi.fn(async () => ({
      status: 302,
      headers: { location: "http://127.0.0.1/private" },
      body: "",
    }))

    await expect(
      fetchPublicPage(
        "https://jobs.example/start",
        dependencies({ request }),
      ),
    ).rejects.toMatchObject({ code: "blocked_address" })
  })

  it("limits redirects, content types, and response bytes", async () => {
    const redirect = vi.fn(async (url: URL) => ({
      status: 302,
      headers: { location: `${url.origin}${url.pathname}/next` },
      body: "",
    }))
    await expect(
      fetchPublicPage("https://jobs.example/start", dependencies({ request: redirect })),
    ).rejects.toMatchObject({ code: "redirect_limit" })

    await expect(
      fetchPublicPage(
        "https://jobs.example/file",
        dependencies({
          request: async () => ({
            status: 200,
            headers: { "content-type": "application/octet-stream" },
            body: "binary",
          }),
        }),
      ),
    ).rejects.toMatchObject({ code: "unsupported_content" })

    await expect(
      fetchPublicPage(
        "https://jobs.example/huge",
        dependencies({
          request: async () => ({
            status: 200,
            headers: { "content-type": "text/plain" },
            body: "x".repeat(1_000_001),
          }),
        }),
      ),
    ).rejects.toMatchObject({ code: "response_too_large" })
  })
})

function dependencies(
  overrides: Partial<NetworkDependencies> = {},
): NetworkDependencies {
  return {
    resolve: async () => [{ address: "93.184.216.34", family: 4 }],
    request: async () => ({
      status: 200,
      headers: { "content-type": "text/html" },
      body: "<h1>Role</h1>",
    }),
    ...overrides,
  }
}
