import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Class Notes",
  description: "Private study notes for classes you choose to record",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
