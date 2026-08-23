import { defineConfig } from "wxt"

function backendHostPermission() {
  const baseUrl = process.env.WXT_PUBLIC_API_BASE_URL ?? "http://localhost:3000"
  return `${new URL(baseUrl).origin}/*`
}

export default defineConfig({
  modules: ["@wxt-dev/module-react"],
  manifest: {
    name: "__MSG_extensionName__",
    description: "__MSG_extensionDescription__",
    default_locale: "en",
    permissions: ["storage", "activeTab"],
    host_permissions: [backendHostPermission()],
    icons: {
      32: "/icon-light-32x32.png",
      128: "/apple-icon.png",
    },
  },
})
