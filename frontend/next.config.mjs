/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The access token travels in the URL fragment after login; never leak the
  // page URL to other sites.
  async headers() {
    return [{ source: "/:path*", headers: [{ key: "Referrer-Policy", value: "no-referrer" }] }];
  },
};

export default nextConfig;
