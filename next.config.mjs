/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    unoptimized: true,
  },
  typescript: {
    tsconfigPath: "tsconfig.next.json",
  },
}

export default nextConfig
