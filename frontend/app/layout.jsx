import "./globals.css";

export const metadata = {
  title: "Gatekeeper",
  description: "Company documents assistant that only shows each person what they're allowed to see.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
