"use client";

import { useEffect, useState } from "react";

const SECTIONS = [
  { id: "price-h", label: "Price" },
  { id: "fin-h", label: "Results" },
  { id: "report-h", label: "Report" },
  { id: "news-h", label: "News" },
];

/** Slides in under the header once the price has scrolled out of view, so the company
 * and its price stay visible on a long page, with links to each section. */
export default function QuoteBar({ name, price, move, moveClass }: {
  name: string;
  price: string | null;
  move: string | null;
  moveClass: string;
}) {
  const [show, setShow] = useState(false);

  useEffect(() => {
    const anchor = document.getElementById("quote-anchor");
    if (!anchor) return;
    const io = new IntersectionObserver(([entry]) => setShow(!entry.isIntersecting && entry.boundingClientRect.top < 0));
    io.observe(anchor);
    return () => io.disconnect();
  }, []);

  return (
    <div className="quote-bar" data-show={show} aria-hidden={!show}>
      <div className="wrap">
        <span className="who">{name}</span>
        {price && <span className="num px">{price}</span>}
        {move && <span className={`num small ${moveClass}`}>{move}</span>}
        <nav aria-label="Sections">
          {SECTIONS.map((s) => (
            <a key={s.id} className="draw" href={`#${s.id}`} tabIndex={show ? 0 : -1}>{s.label}</a>
          ))}
        </nav>
      </div>
    </div>
  );
}
