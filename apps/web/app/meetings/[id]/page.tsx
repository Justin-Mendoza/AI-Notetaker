"use client";

import type { Session } from "@supabase/supabase-js";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "@/lib/api-types";
import { apiUrl, makeClient } from "@/lib/supabase";

type Detail = components["schemas"]["MeetingDetailResponse"];
type Transcript = components["schemas"]["TranscriptResponse"];

export default function MeetingDetail() {
  const { id } = useParams<{ id: string }>();
  const [client] = useState(makeClient);
  const [session, setSession] = useState<Session | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const editingRef = useRef(false);

  const load = useCallback(async (accessToken: string) => {
    try {
      const response = await fetch(`${apiUrl}/v1/meetings/${id}`, {
        headers: { Authorization: `Bearer ${accessToken}` }, cache: "no-store",
      });
      if (response.status === 404) throw new Error("Meeting not found.");
      if (!response.ok) throw new Error("Could not load this meeting. Try again.");
      const next: Detail = await response.json();
      setDetail(next);
      if (next.has_transcript) {
        const transcriptResponse = await fetch(`${apiUrl}/v1/meetings/${id}/transcript`, {
          headers: { Authorization: `Bearer ${accessToken}` }, cache: "no-store",
        });
        if (transcriptResponse.ok) setTranscript(await transcriptResponse.json());
      }
      if (!editingRef.current) setTitle(next.meeting.title);
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not load this meeting.");
    }
  }, [id]);

  useEffect(() => {
    if (!client) return;
    client.auth.getSession().then(({ data }) => {
      setSession(data.session);
      if (data.session) void load(data.session.access_token);
    });
    const { data } = client.auth.onAuthStateChange((_event, next) => {
      setSession(next);
      if (next) void load(next.access_token);
      else { setDetail(null); setTranscript(null); }
    });
    return () => data.subscription.unsubscribe();
  }, [client, load]);

  useEffect(() => {
    if (!session || !detail || !["uploading", "queued", "transcribing", "summarizing"].includes(detail.meeting.status)) return;
    const timer = window.setInterval(() => void load(session.access_token), 4000);
    return () => window.clearInterval(timer);
  }, [session, detail, load]);

  async function saveTitle(event: React.FormEvent) {
    event.preventDefault();
    if (!session || !title.trim()) return;
    const response = await fetch(`${apiUrl}/v1/meetings/${id}`, {
      method: "PATCH",
      headers: { Authorization: `Bearer ${session.access_token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    if (!response.ok) { setMessage("Could not save the title. Try again."); return; }
    editingRef.current = false;
    await load(session.access_token);
    setMessage("Title saved.");
  }

  async function retry() {
    if (!session) return;
    const response = await fetch(`${apiUrl}/v1/meetings/${id}/retry`, {
      method: "POST", headers: { Authorization: `Bearer ${session.access_token}` },
    });
    if (!response.ok) { setMessage("This job cannot be retried. Check the error and recording."); return; }
    setMessage("Processing queued again.");
    await load(session.access_token);
  }

  function downloadTranscript() {
    if (!transcript) return;
    const url = URL.createObjectURL(new Blob([transcript.full_text], { type: "text/plain" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${(detail?.meeting.title || "meeting").replace(/[^a-z0-9-_ ]/gi, "").slice(0, 80)}.txt`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <Link className="text-teal-800 underline" href="/">← Meeting library</Link>
      {!session ? <p className="mt-8">Sign in from the library to view this meeting.</p> : !detail ? <p className="mt-8">Loading meeting…</p> : (
        <>
          <form className="mt-8 flex flex-wrap items-end gap-3" onSubmit={saveTitle}>
            <div className="min-w-64 flex-1"><label htmlFor="title" className="block text-sm font-medium">Meeting title</label><input id="title" className="mt-2 w-full rounded border border-slate-400 bg-white p-3 text-2xl font-semibold" maxLength={160} value={title} onChange={(event) => { editingRef.current = true; setTitle(event.target.value); }} /></div>
            <button className="rounded bg-teal-800 px-5 py-3 font-medium text-white" type="submit">Save title</button>
          </form>
          <p className="mt-3 text-sm text-slate-600">{new Date(detail.meeting.created_at).toLocaleString()}{detail.meeting.duration_ms ? ` · ${Math.round(detail.meeting.duration_ms / 60000)} min` : ""}</p>
          <div role="status" aria-live="polite" className="mt-8 rounded-xl border border-teal-200 bg-teal-50 p-5"><strong className="capitalize">{detail.meeting.status}</strong><p className="mt-2 text-sm">{detail.meeting.status === "queued" ? "Your recording is saved and waiting to be transcribed." : detail.meeting.status === "draft" ? "This meeting has no uploaded recording yet." : detail.meeting.status === "uploading" ? "The recording is uploading. Keep the recording tab open." : detail.meeting.status === "failed" ? `Processing failed${detail.job?.last_error_code ? ` (${detail.job.last_error_code})` : ""}. Retry if the issue was temporary.` : detail.meeting.status === "summarizing" ? "The transcript is saved. Draft notes are being prepared." : "Your meeting is being processed."}</p>{detail.meeting.status === "failed" && <button className="mt-4 rounded bg-teal-800 px-4 py-2 text-white" onClick={() => void retry()}>Retry processing</button>}</div>
          {detail.recording && <p className="mt-5 text-sm text-slate-600">Recording uploaded: {(detail.recording.size_bytes / 1_000_000).toFixed(1)} MB</p>}
          <section className="mt-10 rounded-2xl bg-white p-7 shadow-sm"><h2 className="text-2xl font-semibold">Transcript</h2>{transcript ? <><div className="mt-4 flex flex-wrap gap-3"><button className="rounded border border-teal-800 px-4 py-2 text-teal-800" onClick={() => void navigator.clipboard.writeText(transcript.full_text)}>Copy transcript</button><button className="rounded border border-teal-800 px-4 py-2 text-teal-800" onClick={downloadTranscript}>Download .txt</button></div><ol className="mt-6 space-y-5">{transcript.segments.map((segment) => <li key={segment.id} className="border-t border-slate-200 pt-4"><span className="text-sm text-slate-500">~{Math.floor(segment.start_ms / 60000)}–{Math.ceil(segment.end_ms / 60000)} min</span><p className="mt-2 whitespace-pre-wrap">{segment.text || "[No speech detected in this chunk]"}</p></li>)}</ol></> : <p className="mt-3 text-slate-600">The transcript will appear after transcription completes.</p>}</section>
          <section className="mt-6 rounded-2xl bg-white p-7 shadow-sm"><h2 className="text-2xl font-semibold">AI draft notes</h2><p className="mt-3 text-slate-600">Draft notes will appear after summarization. Review before sharing.</p></section>
        </>
      )}
      {message && <p className="mt-5" role="status" aria-live="polite">{message}</p>}
    </main>
  );
}
