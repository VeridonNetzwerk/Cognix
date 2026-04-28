/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
  async rewrites() {
    if (process.env.NODE_ENV !== "development") return [];
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8080"}/api/:path*`,
      },
      {
        source: "/ws",
        destination: `${process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8080"}/ws`,
      },
    ];
  },
};

export default nextConfig;
