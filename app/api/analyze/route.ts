// Retired: all product requests must use authenticated backend admission.
export function POST() {
  return Response.json({ error: "endpoint_retired" }, { status: 410, headers: { "Cache-Control": "no-store" } })
}
export const OPTIONS = POST
