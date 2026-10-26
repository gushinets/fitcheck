import { readFile, mkdir, writeFile } from "node:fs/promises"
import { fileURLToPath } from "node:url"
import openapiTS, { astToString } from "openapi-typescript"

const source = new URL("../contracts/fitcheck.openapi.json", import.meta.url)
const target = new URL("../lib/backend/generated/schema.ts", import.meta.url)
const ast = await openapiTS(JSON.parse(await readFile(source, "utf8")), { alphabetize: true })
const content = "// Generated from contracts/fitcheck.openapi.json. Do not edit.\n" + astToString(ast)
if (process.argv.includes("--check")) {
  const previous = await readFile(target, "utf8").catch(() => null)
  if (previous !== content) {
    process.stderr.write("Backend TypeScript drift: run pnpm backend:types\n")
    process.exitCode = 1
  } else process.stdout.write("Backend TypeScript artifact is current\n")
} else {
  await mkdir(fileURLToPath(new URL(".", target)), { recursive: true })
  await writeFile(target, content)
  process.stdout.write("Generated backend TypeScript types\n")
}
