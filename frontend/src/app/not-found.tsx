import Link from "next/link";

import SearchBox from "@/components/SearchBox";

export default function NotFound() {
  return (
    <div className="prose">
      <h1>No company with that ticker</h1>
      <p>Check the NSE symbol or BSE code, or search by name.</p>
      <div style={{ maxWidth: "30rem", marginTop: "1.5rem" }}><SearchBox /></div>
      <p style={{ marginTop: "1.5rem" }}><Link href="/">See the companies tracked</Link></p>
    </div>
  );
}
