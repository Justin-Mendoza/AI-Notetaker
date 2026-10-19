import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";
import { Icon } from "@/components/icon";

export const metadata: Metadata = {
  title: "Oatmeal AI",
  description: "A personal class study assistant: follow the transcript during class, then review clear notes on the lesson.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <header className="workspace-nav">
          <Link href="/" className="brand"><span className="brand-mark"><Icon name="book" size={23} /></span><span>Oatmeal AI<span className="brand-caption">Your class study assistant.</span></span></Link>
          <nav aria-label="Main navigation"><Link href="/" className="nav-library">Your library</Link><span className="local-indicator"><span />On your Mac</span></nav>
        </header>
        {children}
        <footer className="workspace-footer"><span>Listen now. Review when you’re ready.</span><span>Oatmeal AI · Your study workspace</span></footer>
      </body>
    </html>
  );
}
