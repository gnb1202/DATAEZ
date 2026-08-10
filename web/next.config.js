// Validate required env vars at build time (production only)
if (process.env.NODE_ENV === "production" && !process.env.NEXT_PUBLIC_API_URL) {
  console.warn(
    "[DATAEZ] WARNING: NEXT_PUBLIC_API_URL is not set. Falling back to http://localhost:8000"
  );
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  poweredByHeader: false,
  compress: true,
  images: {
    formats: ["image/avif", "image/webp"],
  },
  reactStrictMode: true,
};

module.exports = nextConfig;

