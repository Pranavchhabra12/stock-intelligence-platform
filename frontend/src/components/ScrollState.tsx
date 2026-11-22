"use client";

import { useEffect } from "react";

/** Marks the page as scrolled (for the header's soft edge) and makes taps show
 * their pressed state on touch-down, so buttons answer the finger at once. */
export default function ScrollState() {
  useEffect(() => {
    const root = document.documentElement;
    let frame = 0;
    const update = () => {
      frame = 0;
      root.dataset.scrolled = window.scrollY > 4 ? "true" : "false";
    };
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(update); };
    const noop = () => {};
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    document.addEventListener("touchstart", noop, { passive: true });   // enables :active on iOS
    return () => {
      window.removeEventListener("scroll", onScroll);
      document.removeEventListener("touchstart", noop);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
  return null;
}
