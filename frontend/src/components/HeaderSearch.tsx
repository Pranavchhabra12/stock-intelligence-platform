"use client";

import { usePathname } from "next/navigation";

import SearchBox from "@/components/SearchBox";

/** The header search, everywhere except the home page, which has its own big search box. */
export default function HeaderSearch() {
  if (usePathname() === "/") return <div className="header-search" aria-hidden="true" />;
  return <div className="header-search"><SearchBox compact /></div>;
}
