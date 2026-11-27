"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Customer chat" },
  { href: "/console", label: "Support console" },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <nav className="nav">
      <span className="brand">Northwind Supply · AI Support</span>
      <div className="nav-links">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} className={pathname === l.href ? "active" : ""}>
            {l.label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
