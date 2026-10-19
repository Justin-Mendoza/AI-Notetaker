import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";
import { Icon } from "@/components/icon";

export const metadata: Metadata = {
  title: "Class Notes",
  description: "Private study notes for classes you choose to record",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <header className="workspace-nav">
          <Link href="/" className="brand"><span className="brand-mark"><Icon name="book" size={23} /></span><span>Class Notes<span className="brand-caption">A little more understanding.</span></span></Link>
          <nav aria-label="Main navigation"><Link href="/" className="nav-library">Your library</Link><span className="local-indicator"><span />On your Mac</span></nav>
        </header>
        {children}
        <footer className="workspace-footer"><span>Made for the moments that make it click.</span><span>Class Notes · Your study workspace</span></footer>
      </body>
    </html>
  );
}
