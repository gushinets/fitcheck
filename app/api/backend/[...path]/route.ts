import { relayBackend } from "@/lib/backend/relay"

export const runtime = "nodejs"
export function GET(request: Request) { return relayBackend(request) }
export function POST(request: Request) { return relayBackend(request) }
export function PUT(request: Request) { return relayBackend(request) }
export function DELETE(request: Request) { return relayBackend(request) }
