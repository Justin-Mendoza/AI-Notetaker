"use client";

import { useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";

export type Deck = { filename: string; page_count: number; references: Record<string, number[]> };

export function ClassSlides({ meetingId, page, onPage, onDeck }: {
  meetingId: string; page: number; onPage: (page: number) => void;
  onDeck: (deck: Deck | null) => void;
}) {
  const [deck, setDeck] = useState<Deck | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const base = `${apiUrl}/v1/meetings/${meetingId}/slides`;
  useEffect(() => {
    let active = true;
    void fetch(base, { cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw new Error("Could not load slides.");
      const next: Deck | null = await response.json();
      if (active) { setDeck(next); onDeck(next); }
    }).catch((error) => { if (active) setMessage(error.message); });
    return () => { active = false; };
  }, [base, onDeck]);

  async function upload(file: File) {
    setBusy(true); setMessage("");
    try {
      if (file.size > 20 * 1024 * 1024) throw new Error("Slides must be 20 MB or smaller.");
      const form = new FormData(); form.append("file", file);
      const response = await fetch(base, { method: "POST", body: form });
      if (!response.ok) {
        const payload = await response.json();
        throw new Error(payload.error?.message || "Could not upload slides.");
      }
      const next: Deck = await response.json();
      setDeck(next); onDeck(next); onPage(1);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not upload slides."); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!window.confirm("Remove this PDF and its slide references?")) return;
    setBusy(true);
    try {
      const response = await fetch(base, { method: "DELETE" });
      if (!response.ok) throw new Error("Could not remove slides.");
      setDeck(null); onDeck(null); onPage(1); setMessage("");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not remove slides."); }
    finally { setBusy(false); }
  }

  return <section id="class-slides" className="mt-6 rounded-2xl bg-white p-7 shadow-sm" aria-labelledby="slides-heading">
    <h2 id="slides-heading" className="text-2xl font-semibold">Class slides <span className="text-sm font-normal text-slate-500">Optional</span></h2>
    {deck ? <>
      <div className="my-4 flex flex-wrap items-center gap-3">
        <p className="mr-auto text-sm">{deck.filename} · {deck.page_count} slides</p>
        <button disabled={busy} className="text-sm text-red-700 underline" onClick={() => void remove()}>Remove PDF</button>
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <button className="rounded border px-3 py-2 disabled:opacity-40" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
        <label>Slide <select className="rounded border p-2" value={page} onChange={(event) => onPage(Number(event.target.value))}>{Array.from({ length: deck.page_count }, (_, index) => <option key={index} value={index + 1}>{index + 1}</option>)}</select> of {deck.page_count}</label>
        <button className="rounded border px-3 py-2 disabled:opacity-40" disabled={page >= deck.page_count} onClick={() => onPage(page + 1)}>Next</button>
        <a className="text-sm text-teal-800 underline" href={`${base}/pdf#page=${page}`} target="_blank" rel="noreferrer">Open PDF in new tab</a>
      </div>
      <iframe key={page} title={`Class slides — slide ${page}`} src={`${base}/pdf#page=${page}&view=FitH`} className="h-[600px] w-full rounded border" />
      <p className="mt-3 text-sm text-slate-600">Each PDF page is one slide. Link the current slide from a topic below. If the viewer is unavailable, open the PDF in a new tab.</p>
    </> : <>
      <p className="my-3 text-sm text-slate-600">Add a PDF to view slides and link them to your study-guide topics. You can record and generate notes without slides. The PDF stays in your local app.</p>
      <label className="block text-sm font-medium">Add slides (PDF, up to 20 MB / 500 pages)
        <input className="mt-2 block w-full" type="file" accept="application/pdf,.pdf" disabled={busy} onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = ""; }} />
      </label>
    </>}
    {(busy || message) && <p className="mt-3 text-sm" role="status">{busy ? "Saving slides…" : message}</p>}
  </section>;
}
