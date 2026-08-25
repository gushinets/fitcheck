import { lookup as dnsLookup } from "node:dns/promises"
import { request as httpRequest } from "node:http"
import { request as httpsRequest } from "node:https"
import { isIP, type LookupFunction } from "node:net"

const MAX_REDIRECTS = 3
const MAX_BYTES = 1_000_000
const TIMEOUT_MS = 8_000

export type ExtractionNetworkErrorCode =
  | "invalid_url"
  | "blocked_address"
  | "redirect_limit"
  | "unsupported_content"
  | "response_too_large"
  | "timeout"
  | "fetch_failed"

export interface ResolvedAddress {
  address: string
  family: 4 | 6
}

export interface RawPageResponse {
  status: number
  headers: Record<string, string | undefined>
  body: string
}

export interface PublicPageResponse {
  finalUrl: string
  contentType: string
  body: string
}

interface RequestLimits {
  maxBytes: number
  timeoutMs: number
}

export interface NetworkDependencies {
  resolve(hostname: string): Promise<ResolvedAddress[]>
  request(
    url: URL,
    addresses: ResolvedAddress[],
    limits: RequestLimits,
  ): Promise<RawPageResponse>
}

export class ExtractionNetworkError extends Error {
  constructor(public readonly code: ExtractionNetworkErrorCode) {
    super(code)
    this.name = "ExtractionNetworkError"
  }
}

const blockedV4: Array<[string, number]> = [
  ["0.0.0.0", 8],
  ["10.0.0.0", 8],
  ["100.64.0.0", 10],
  ["127.0.0.0", 8],
  ["169.254.0.0", 16],
  ["172.16.0.0", 12],
  ["192.0.0.0", 24],
  ["192.0.2.0", 24],
  ["192.88.99.0", 24],
  ["192.168.0.0", 16],
  ["198.18.0.0", 15],
  ["198.51.100.0", 24],
  ["203.0.113.0", 24],
  ["224.0.0.0", 4],
  ["240.0.0.0", 4],
]

const blockedV6: Array<[string, number]> = [
  ["::", 128],
  ["::1", 128],
  ["2001:db8::", 32],
  ["fc00::", 7],
  ["fe80::", 10],
  ["ff00::", 8],
]

function ipv4Number(address: string) {
  return address
    .split(".")
    .reduce((result, part) => result * 256 + Number(part), 0)
}

function expandEmbeddedIpv4(address: string) {
  if (!address.includes(".")) return address
  const separator = address.lastIndexOf(":")
  const ipv4 = ipv4Number(address.slice(separator + 1))
  const high = Math.floor(ipv4 / 65_536).toString(16)
  const low = (ipv4 % 65_536).toString(16)
  return `${address.slice(0, separator)}:${high}:${low}`
}

function ipv6Bytes(rawAddress: string) {
  const address = expandEmbeddedIpv4(rawAddress.toLowerCase())
  const halves = address.split("::")
  if (halves.length > 2) throw new Error("invalid IPv6 address")
  const left = halves[0] ? halves[0].split(":") : []
  const right = halves[1] ? halves[1].split(":") : []
  const missing = 8 - left.length - right.length
  if (missing < 0 || (halves.length === 1 && missing !== 0)) {
    throw new Error("invalid IPv6 address")
  }
  const groups = [
    ...left,
    ...Array.from({ length: missing }, () => "0"),
    ...right,
  ]
  return Uint8Array.from(
    groups.flatMap((group) => {
      const value = Number.parseInt(group || "0", 16)
      return [Math.floor(value / 256), value % 256]
    }),
  )
}

function inIpv4Cidr(value: number, network: number, prefix: number) {
  if (prefix === 0) return true
  const divisor = 2 ** (32 - prefix)
  return Math.floor(value / divisor) === Math.floor(network / divisor)
}

function inIpv6Cidr(value: Uint8Array, network: Uint8Array, prefix: number) {
  const fullBytes = Math.floor(prefix / 8)
  for (let index = 0; index < fullBytes; index += 1) {
    if (value[index] !== network[index]) return false
  }
  const remainingBits = prefix % 8
  if (!remainingBits) return true
  const mask = 0xff << (8 - remainingBits)
  return (value[fullBytes] & mask) === (network[fullBytes] & mask)
}

export function isPublicAddress(address: string) {
  const family = isIP(address)
  if (family === 4) {
    const value = ipv4Number(address)
    return !blockedV4.some(([network, prefix]) =>
      inIpv4Cidr(value, ipv4Number(network), prefix),
    )
  }
  if (family === 6) {
    const normalized = address.toLowerCase()
    if (normalized.startsWith("::ffff:")) {
      const embedded = normalized.slice("::ffff:".length)
      if (isIP(embedded) === 4) return isPublicAddress(embedded)
    }
    const value = ipv6Bytes(address)
    return !blockedV6.some(([network, prefix]) =>
      inIpv6Cidr(value, ipv6Bytes(network), prefix),
    )
  }
  return false
}

function nodeRequest(
  url: URL,
  addresses: ResolvedAddress[],
  limits: RequestLimits,
): Promise<RawPageResponse> {
  return new Promise((resolve, reject) => {
    const pinned = addresses[0]
    const lookup: LookupFunction = (_hostname, _options, callback) => {
      callback(null, pinned.address, pinned.family)
    }
    const transport = url.protocol === "https:" ? httpsRequest : httpRequest
    const request = transport(
      url,
      {
        method: "GET",
        headers: {
          accept: "text/html,text/plain;q=0.9",
          "user-agent": "FitCheck Vacancy Extractor/1.0",
        },
        lookup,
        signal: AbortSignal.timeout(limits.timeoutMs),
      },
      (response) => {
        const chunks: Buffer[] = []
        let byteLength = 0
        response.on("data", (chunk: Buffer) => {
          byteLength += chunk.length
          if (byteLength > limits.maxBytes) {
            request.destroy(
              new ExtractionNetworkError("response_too_large"),
            )
            return
          }
          chunks.push(chunk)
        })
        response.on("end", () => {
          resolve({
            status: response.statusCode ?? 0,
            headers: {
              "content-type": response.headers["content-type"],
              location: response.headers.location,
            },
            body: Buffer.concat(chunks).toString("utf8"),
          })
        })
      },
    )
    request.on("error", (error) => {
      if (error instanceof ExtractionNetworkError) return reject(error)
      if (error.name === "AbortError" || "code" in error && error.code === "ETIMEDOUT") {
        return reject(new ExtractionNetworkError("timeout"))
      }
      reject(new ExtractionNetworkError("fetch_failed"))
    })
    request.end()
  })
}

const nodeDependencies: NetworkDependencies = {
  async resolve(hostname) {
    const addresses = await dnsLookup(hostname, { all: true, verbatim: true })
    return addresses.map(({ address, family }) => ({
      address,
      family: family as 4 | 6,
    }))
  },
  request: nodeRequest,
}

function parsePublicUrl(rawUrl: string) {
  let url: URL
  try {
    url = new URL(rawUrl)
  } catch {
    throw new ExtractionNetworkError("invalid_url")
  }
  if (
    (url.protocol !== "http:" && url.protocol !== "https:") ||
    url.username ||
    url.password
  ) {
    throw new ExtractionNetworkError("invalid_url")
  }
  return url
}

async function validatedAddresses(
  url: URL,
  dependencies: NetworkDependencies,
) {
  if (isIP(url.hostname)) {
    if (!isPublicAddress(url.hostname)) {
      throw new ExtractionNetworkError("blocked_address")
    }
    return [{ address: url.hostname, family: isIP(url.hostname) as 4 | 6 }]
  }

  let addresses: ResolvedAddress[]
  try {
    addresses = await dependencies.resolve(url.hostname)
  } catch {
    throw new ExtractionNetworkError("fetch_failed")
  }
  if (!addresses.length || addresses.some(({ address }) => !isPublicAddress(address))) {
    throw new ExtractionNetworkError("blocked_address")
  }
  return addresses
}

export async function fetchPublicPage(
  rawUrl: string,
  dependencies: NetworkDependencies = nodeDependencies,
): Promise<PublicPageResponse> {
  let url = parsePublicUrl(rawUrl)

  for (let redirects = 0; redirects <= MAX_REDIRECTS; redirects += 1) {
    const addresses = await validatedAddresses(url, dependencies)
    let response: RawPageResponse
    try {
      response = await dependencies.request(url, addresses, {
        maxBytes: MAX_BYTES,
        timeoutMs: TIMEOUT_MS,
      })
    } catch (error) {
      if (error instanceof ExtractionNetworkError) throw error
      throw new ExtractionNetworkError("fetch_failed")
    }

    if (response.status >= 300 && response.status < 400) {
      const location = response.headers.location
      if (!location) throw new ExtractionNetworkError("fetch_failed")
      if (redirects === MAX_REDIRECTS) {
        throw new ExtractionNetworkError("redirect_limit")
      }
      url = parsePublicUrl(new URL(location, url).toString())
      continue
    }
    if (response.status < 200 || response.status >= 300) {
      throw new ExtractionNetworkError("fetch_failed")
    }
    if (Buffer.byteLength(response.body) > MAX_BYTES) {
      throw new ExtractionNetworkError("response_too_large")
    }
    const contentType = response.headers["content-type"]
      ?.split(";", 1)[0]
      .trim()
      .toLowerCase()
    if (contentType !== "text/html" && contentType !== "text/plain") {
      throw new ExtractionNetworkError("unsupported_content")
    }
    return { finalUrl: url.toString(), contentType, body: response.body }
  }

  throw new ExtractionNetworkError("redirect_limit")
}
