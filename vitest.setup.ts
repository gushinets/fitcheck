import "@testing-library/jest-dom/vitest"
import { cleanup } from "@testing-library/react"
import { afterEach } from "vitest"

afterEach(cleanup)

const localValues = new Map<string, string>()
const memoryLocalStorage: Storage = {
  get length() {
    return localValues.size
  },
  clear() {
    localValues.clear()
  },
  getItem(key) {
    return localValues.get(key) ?? null
  },
  key(index) {
    return [...localValues.keys()][index] ?? null
  },
  removeItem(key) {
    localValues.delete(key)
  },
  setItem(key, value) {
    localValues.set(key, String(value))
  },
}

if (typeof window !== "undefined") {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: memoryLocalStorage,
  })
}
