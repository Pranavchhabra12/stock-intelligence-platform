"use client";

import { useEffect, useRef, useState } from "react";

/** Shows a value; if it changes while the page is open (after a refresh), it glows once. */
export default function Flash({ value, className }: { value: string; className?: string }) {
  const previous = useRef(value);
  const [key, setKey] = useState(0);

  useEffect(() => {
    if (previous.current !== value) {
      previous.current = value;
      setKey((k) => k + 1);
    }
  }, [value]);

  return (
    <span key={key} className={[className, key > 0 ? "flash" : ""].filter(Boolean).join(" ") || undefined}>
      {value}
    </span>
  );
}
