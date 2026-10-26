import type { PasswordDigest } from "./types"

const ITERATIONS = 210_000
const SALT_BYTES = 16
const HASH_BITS = 256

function toBase64(bytes: Uint8Array) {
  let binary = ""
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}

function fromBase64(value: string) {
  const binary = atob(value)
  return Uint8Array.from(binary, (character) => character.charCodeAt(0))
}

async function deriveBytes(password: string, salt: Uint8Array) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"],
  )
  const bits = await crypto.subtle.deriveBits(
    {
      name: "PBKDF2",
      hash: "SHA-256",
      salt,
      iterations: ITERATIONS,
    },
    key,
    HASH_BITS,
  )
  return new Uint8Array(bits)
}

export async function derivePassword(
  password: string,
  encodedSalt?: string,
): Promise<PasswordDigest> {
  const salt = encodedSalt
    ? fromBase64(encodedSalt)
    : crypto.getRandomValues(new Uint8Array(SALT_BYTES))
  const hash = await deriveBytes(password, salt)
  return { salt: toBase64(salt), hash: toBase64(hash) }
}

export async function verifyPassword(
  password: string,
  digest: PasswordDigest,
) {
  const candidate = fromBase64(
    (await derivePassword(password, digest.salt)).hash,
  )
  const expected = fromBase64(digest.hash)
  if (candidate.length !== expected.length) return false

  let difference = 0
  for (let index = 0; index < candidate.length; index += 1) {
    difference |= candidate[index] ^ expected[index]
  }
  return difference === 0
}
