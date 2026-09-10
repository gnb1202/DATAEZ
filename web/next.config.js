// Validate required env vars at build time (production only)
if (process.env.NODE_ENV === "production" && !process.env.NEXT_PUBLIC_API_URL?.trim()) {
  console.warn(
    "[DATAEZ] NEXT_PUBLIC_API_URL is not set. Publishing the frontend with authentication disabled."
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
