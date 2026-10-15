import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Brightline | Integration Health",
  description: "Explainable integration health for Brightline HR operations",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
