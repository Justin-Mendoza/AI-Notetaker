"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "@/lib/api-types";
import { apiUrl } from "@/lib/api";

type Detail = components["schemas"]["MeetingDetailResponse"];
type Transcript = components["schemas"]["TranscriptResponse"];
type Summary = components["schemas"]["SummaryContent"];

export default function MeetingDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const editingRef = useRef(false);

  const load = useCallback(async () => {
    try {
      const response = await fetch(`${apiUrl}/v1/meetings/${id}`, {
        cache: "no-store",
      });
      if (response.status === 404) throw new Error("Meeting not found.");
      if (!response.ok) throw new Error("Could not load this meeting. Try again.");
      const next: Detail = await response.json();
      setDetail(next);
      if (next.has_transcript) {
        const transcriptResponse = await fetch(`${apiUrl}/v1/meetings/${id}/transcript`, {
          cache: "no-store",
        });
        if (transcriptResponse.ok) setTranscript(await transcriptResponse.json());
      }
      if (next.has_summary) {
        const summaryResponse = await fetch(`${apiUrl}/v1/meetings/${id}/summary`, {
          cache: "no-store",
        });
        if (summaryResponse.ok) {
          const payload = await summaryResponse.json();
          setSummary(payload.summary);
        }
      }
      if (!editingRef.current) setTitle(next.meeting.title);
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not load this meeting.");
    }
  }, [id]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    if (!detail || !["uploading", "queued", "transcribing", "summarizing"].includes(detail.meeting.status)) return;
    const timer = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(timer);
  }, [detail, load]);

  async function saveTitle(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    const response = await fetch(`${apiUrl}/v1/meetings/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    if (!response.ok) { setMessage("Could not save the title. Try again."); return; }
    editingRef.current = false;
    await load();
    setMessage("Title saved.");
  }

  async function retry() {
    try {
      const response = await fetch(`${apiUrl}/v1/meetings/${id}/retry`, {
        method: "POST",
      });
      if (!response.ok) {
        const payload = await response.json();
        setMessage(payload.error?.message || "This job cannot be retried.");
        return;
      }
      setMessage("Processing queued again.");
      await load();
    } catch {
      setMessage("Could not retry processing. Check your connection and try again.");
    }
  }

  async function deleteMeeting() {
    if (!window.confirm("Permanently delete this meeting, its transcript, and draft notes?")) return;
    try {
      const response = await fetch(`${apiUrl}/v1/meetings/${id}`, {
        method: "DELETE",
      });
      if (response.status !== 204) throw new Error();
      router.push("/");
    } catch {
      setMessage("Could not delete this meeting. Check your connection and try again.");
    }
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

  function copyNotes() {
    if (!summary) return;
    const lines = [
      detail?.meeting.title || "Meeting notes", "", "Overview", summary.overview, "",
      "Key points", ...summary.key_points.map((point) => `- ${point}`), "",
      "Decisions", ...summary.decisions.map((item) => `- ${item.text}`), "",
      "Action items", ...summary.action_items.map((item) => `- ${item.task}${item.owner ? ` — ${item.owner}` : ""}${item.due_date ? ` (due ${item.due_date})` : ""}`), "",
      "Open questions", ...summary.open_questions.map((question) => `- ${question}`),
    ];
    void navigator.clipboard.writeText(lines.join("\n"));
    setMessage("Draft notes copied. Review before sharing.");
  }

  function evidence(ids: string[]) {
    if (!ids.length || !transcript) return null;
    return <span className="ml-2 text-sm text-slate-500">Evidence: {ids.map((id, index) => {
      const segment = transcript.segments.find((item) => item.id === id);
      return segment ? <span key={id}>{index ? ", " : ""}<a className="text-teal-800 underline" href={`#segment-${id}`}>~{Math.floor(segment.start_ms / 60000)} min</a></span> : null;
    })}</span>;
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <Link className="text-teal-800 underline" href="/">← Meeting library</Link>
      {!detail ? <p className="mt-8">Loading meeting…</p> : (
        <>
          <form className="mt-8 flex flex-wrap items-end gap-3" onSubmit={saveTitle}>
            <div className="min-w-64 flex-1"><label htmlFor="title" className="block text-sm font-medium">Meeting title</label><input id="title" className="mt-2 w-full rounded border border-slate-400 bg-white p-3 text-2xl font-semibold" maxLength={160} value={title} onChange={(event) => { editingRef.current = true; setTitle(event.target.value); }} /></div>
            <button className="rounded bg-teal-800 px-5 py-3 font-medium text-white" type="submit">Save title</button>
          </form>
          <p className="mt-3 text-sm text-slate-600">{new Date(detail.meeting.created_at).toLocaleString()}{detail.meeting.duration_ms ? ` · ${Math.round(detail.meeting.duration_ms / 60000)} min` : ""}</p>
          <button className="mt-3 text-sm text-red-700 underline" onClick={() => void deleteMeeting()}>Delete meeting</button>
          <div role="status" aria-live="polite" className="mt-8 rounded-xl border border-teal-200 bg-teal-50 p-5"><strong className="capitalize">{detail.meeting.status}</strong><p className="mt-2 text-sm">{detail.meeting.status === "queued" ? "Your recording is saved and waiting to be transcribed." : detail.meeting.status === "draft" ? "This meeting has no uploaded recording yet." : detail.meeting.status === "uploading" ? "The recording is uploading. Keep the recording tab open." : detail.meeting.status === "failed" ? `Processing failed${detail.job?.last_error_code ? ` (${detail.job.last_error_code})` : ""}. Retry if the issue was temporary.` : detail.meeting.status === "summarizing" ? "The transcript is saved. Draft notes are being prepared." : detail.meeting.status === "ready" ? "Transcript and draft notes are ready for your review." : "Your meeting is being processed."}</p>{detail.meeting.status === "failed" && <button className="mt-4 rounded bg-teal-800 px-4 py-2 text-white" onClick={() => void retry()}>Retry processing</button>}</div>
          {detail.recording && <p className="mt-5 text-sm text-slate-600">Recording uploaded: {(detail.recording.size_bytes / 1_000_000).toFixed(1)} MB</p>}
          <section className="mt-6 rounded-2xl bg-white p-7 shadow-sm"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-2xl font-semibold">AI draft — review before sharing</h2>{summary && <button className="rounded border border-teal-800 px-4 py-2 text-teal-800" onClick={copyNotes}>Copy notes</button>}</div>{summary ? <div className="mt-6 space-y-6"><section><h3 className="font-semibold">Overview</h3><p className="mt-2">{summary.overview}</p></section><section><h3 className="font-semibold">Key points</h3>{summary.key_points.length ? <ul className="mt-2 list-disc pl-6">{summary.key_points.map((point, index) => <li key={index}>{point}</li>)}</ul> : <p className="mt-2 text-slate-500">None supported by the transcript.</p>}</section><section><h3 className="font-semibold">Decisions</h3>{summary.decisions.length ? <ul className="mt-2 list-disc pl-6">{summary.decisions.map((item, index) => <li key={index}>{item.text}{evidence(item.evidence_segment_ids)}</li>)}</ul> : <p className="mt-2 text-slate-500">No decisions identified.</p>}</section><section><h3 className="font-semibold">Action items</h3>{summary.action_items.length ? <ul className="mt-2 list-disc pl-6">{summary.action_items.map((item, index) => <li key={index}>{item.task}{item.owner && ` — ${item.owner}`}{item.due_date && ` · Due ${item.due_date}`}{evidence(item.evidence_segment_ids)}</li>)}</ul> : <p className="mt-2 text-slate-500">No action items identified.</p>}</section><section><h3 className="font-semibold">Open questions</h3>{summary.open_questions.length ? <ul className="mt-2 list-disc pl-6">{summary.open_questions.map((question, index) => <li key={index}>{question}</li>)}</ul> : <p className="mt-2 text-slate-500">No open questions identified.</p>}</section></div> : <p className="mt-3 text-slate-600">Draft notes will appear after summarization.</p>}</section>
          <section className="mt-10 rounded-2xl bg-white p-7 shadow-sm"><h2 className="text-2xl font-semibold">Transcript</h2>{transcript ? <><div className="mt-4 flex flex-wrap gap-3"><button className="rounded border border-teal-800 px-4 py-2 text-teal-800" onClick={() => void navigator.clipboard.writeText(transcript.full_text)}>Copy transcript</button><button className="rounded border border-teal-800 px-4 py-2 text-teal-800" onClick={downloadTranscript}>Download .txt</button></div><ol className="mt-6 space-y-5">{transcript.segments.map((segment) => <li id={`segment-${segment.id}`} key={segment.id} className="border-t border-slate-200 pt-4"><span className="text-sm text-slate-500">~{Math.floor(segment.start_ms / 60000)}–{Math.ceil(segment.end_ms / 60000)} min</span><p className="mt-2 whitespace-pre-wrap">{segment.text || "[No speech detected in this chunk]"}</p></li>)}</ol></> : <p className="mt-3 text-slate-600">The transcript will appear after transcription completes.</p>}</section>
        </>
      )}
      {message && <p className="mt-5" role="status" aria-live="polite">{message}</p>}
    </main>
  );
}
