"use client";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="prose">
      <h1>This page didn’t load</h1>
      <p>The data service may be waking up; free servers sleep when nobody is using them. Try again in a few seconds.</p>
      <p><button type="button" className="more" onClick={reset}>Try again</button></p>
    </div>
  );
}
