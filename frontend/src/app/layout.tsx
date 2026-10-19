import type { Metadata } from "next";
import "./globals.css";
import { DemoAccess } from "@/components/demo-access";
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
      <body>
        <DemoAccess>{children}</DemoAccess>
      </body>
    </html>
  );
}
