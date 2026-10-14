import { NextRequest, NextResponse } from 'next/server'
import { requestVisitor, setVisitorCookie, telemetryIdentityEnabled } from './lib/metrics/operations'
export function proxy(request:NextRequest) {
  const response=NextResponse.next()
  if(request.method !== 'GET' || request.nextUrl.pathname !== '/' || !request.headers.get('accept')?.includes('text/html') || request.headers.has('rsc') || request.headers.has('next-router-prefetch') || !telemetryIdentityEnabled()) return response
  const visitor=requestVisitor(request)
  if(visitor?.isNew) setVisitorCookie(response,visitor)
  return response
}
export const config={matcher:'/'}
