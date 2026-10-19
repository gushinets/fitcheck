/** Same-origin cookie relay. No service credentials or provider access here. */
export async function relayBackend(request: Request, backendUrl = process.env.FITCHECK_BACKEND_URL, transport = fetch) {
  const url = new URL(request.url)
  const prefix = "/api/backend/"
  const path = url.pathname.slice(prefix.length)
  const fail = (status: number, code: string) => Response.json({ error: { code, message: code, details: [] } }, { status, headers: { "Cache-Control": "no-store" } })
  if (!url.pathname.startsWith(prefix) || !/^v1\/[a-z0-9/-]+$/.test(path) || path.includes("//")) return fail(400, "invalid_request")
  if (!backendUrl) return fail(503, "service_unavailable")
  const origin = request.headers.get("origin")
  const publicOrigin = process.env.FITCHECK_WEBSITE_ORIGIN ?? url.origin
  if ((origin && origin !== publicOrigin) || request.headers.get("sec-fetch-site") === "cross-site") return fail(403, "forbidden")
  if (!["GET", "HEAD"].includes(request.method) && origin !== publicOrigin) return fail(403, "forbidden")
  const headers = new Headers({ Accept: "application/json", Origin: publicOrigin })
  for (const name of ["content-type", "x-csrf-token", "x-guest-csrf-token", "idempotency-key"]) {
    const value = request.headers.get(name)
    if (value) headers.set(name, value)
  }
  const cookies = (request.headers.get("cookie") ?? "").split(";").map(v => v.trim()).filter(v => /^(?:__Host-)?fitcheck_(?:session|auth_csrf|guest)=/.test(v))
  if (cookies.length) headers.set("cookie", cookies.join("; "))
  try {
    const response = await transport(`${backendUrl.replace(/\/+$/, "")}/${path}${url.search}`, {
      method: request.method, headers, redirect: "error", cache: "no-store",
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.text(),
      signal: AbortSignal.timeout(30_000),
    })
    const outgoing = new Headers({ "Cache-Control": "no-store" })
    for (const name of ["content-type", "retry-after", "x-request-id"]) {
      const value = response.headers.get(name)
      if (value) outgoing.set(name, value)
    }
    for (const cookie of response.headers.getSetCookie()) outgoing.append("set-cookie", cookie)
    return new Response(response.body, { status: response.status, headers: outgoing })
  } catch { return fail(503, "service_unavailable") }
}
