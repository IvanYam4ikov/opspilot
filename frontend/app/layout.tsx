import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OpsPilot | Operations Resolution",
  description: "Investigate and resolve customer operations tickets.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
