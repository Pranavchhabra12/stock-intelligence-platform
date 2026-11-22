"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Companies" },
  { href: "/about", label: "How it works" },
];

export default function NavLinks() {
  const path = usePathname();
  return (
    <nav aria-label="Site">
      {LINKS.map((l) => (
        <Link key={l.href} href={l.href} aria-current={path === l.href ? "page" : undefined}>{l.label}</Link>
      ))}
    </nav>
  );
}
