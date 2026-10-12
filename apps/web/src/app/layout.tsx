import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Tradiopro | Market analysis",
  description:
    "A forex and cryptocurrency analysis workspace with risk validation.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
