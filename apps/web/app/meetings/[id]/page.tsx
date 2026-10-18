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
  const topics = summary?.topics ?? [];
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const editingRef = useRef(false);

  const load = useCallback(async () => {
    try {
      const response = await fetch(`${apiUrl}/v1/meetings/${id}`, {
        cache: "no-store",
      });
      if (response.status === 404) throw new Error("Class recording not found.");
      if (!response.ok) throw new Error("Could not load this class recording. Try again.");
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
      setMessage(error instanceof Error ? error.message : "Could not load this class recording.");
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

  async function regenerateNotes() {
    try {
      const response = await fetch(`${apiUrl}/v1/meetings/${id}/regenerate`, {
        method: "POST",
      });
      if (!response.ok) {
        const payload = await response.json();
        setMessage(payload.error?.message || "Could not regenerate class notes.");
        return;
      }
      setMessage("Updating class notes from the saved transcript.");
      await load();
    } catch {
      setMessage("Could not regenerate class notes. Check your connection and try again.");
    }
  }

  async function deleteMeeting() {
    if (!window.confirm("Permanently delete this class recording, its transcript, and draft notes?")) return;
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
    link.download = `${(detail?.meeting.title || "class").replace(/[^a-z0-9-_ ]/gi, "").slice(0, 80)}.txt`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  function copyNotes() {
    if (!summary || !detail) return;
    void navigator.clipboard.writeText(notesMarkdown());
    setMessage("Draft notes copied. Review before sharing.");
  }

  function notesMarkdown() {
    if (!summary || !detail) return "";
    const bullets = (items: string[], empty: string) => items.length
      ? items.map((item) => `- ${item}`)
      : [`- ${empty}`];
    const cell = (value: string) => value.replaceAll("|", "\\|").replace(/\s+/g, " ");
    return [
      `# ${detail.meeting.title}`,
      `Date: ${new Date(detail.meeting.started_at || detail.meeting.created_at).toLocaleString()}`,
      "AI draft — review before using or sharing",
      "",
      "## Class overview", summary.overview,
      "",
      "## Topics covered",
      ...(topics.length ? topics.flatMap((topic, index) => [
        "",
        `### ${index + 1}. ${topic.heading}`,
        `**What was explained:** ${topic.summary}`,
        ...(topic.key_details.length ? ["", "**Important details**", ...topic.key_details.map((detail) => `- ${detail}`)] : []),
      ]) : ["Topic explanations are unavailable for this older note. Regenerate class notes in the app."]),
      "",
      "## Quick review", ...bullets(summary.key_points, "No review points identified."),
      "",
      "## Announcements and decisions", ...bullets(summary.decisions.map((item) => item.text), "None identified."),
      "",
      "## Assignments and follow-ups",
      ...(summary.action_items.length
        ? ["| Task | Owner | Due date |", "| --- | --- | --- |", ...summary.action_items.map((item) =>
          `| ${cell(item.task)} | ${cell(item.owner || "Not specified")} | ${cell(item.due_date || "Not specified")} |`)]
        : ["No assignments or follow-ups identified."]),
      "",
      "## Questions to revisit", ...bullets(summary.open_questions, "No open questions identified."),
      "",
    ].join("\n");
  }

  function downloadNotes() {
    if (!summary || !detail) return;
    const url = URL.createObjectURL(new Blob([notesMarkdown()], { type: "text/markdown" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${detail.meeting.title.replace(/[^a-z0-9-_ ]/gi, "").slice(0, 80) || "class-notes"}.md`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  function evidence(ids: string[]) {
    if (!ids.length || !transcript) return null;
    return <span className="ml-2 text-sm text-slate-500">Evidence: {ids.map((id, index) => {
      const segment = transcript.segments.find((item) => item.id === id);
      return segment ? <span key={id}>{index ? ", " : ""}<a className="text-teal-800 underline" href={`#segment-${id}`}>~{Math.floor(segment.start_ms / 60000)} min</a></span> : null;
    })}</span>;
  }

  const meetingDate = detail
    ? new Date(detail.meeting.started_at || detail.meeting.created_at).toLocaleString()
    : "";

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <Link className="text-teal-800 underline" href="/">← Class library</Link>
      {!detail ? <p className="mt-8">Loading recording…</p> : (
        <>
          <form className="mt-8 flex flex-wrap items-end gap-3" onSubmit={saveTitle}>
            <div className="min-w-64 flex-1"><label htmlFor="title" className="block text-sm font-medium">Class title</label><input id="title" className="mt-2 w-full rounded border border-slate-400 bg-white p-3 text-2xl font-semibold" maxLength={160} value={title} onChange={(event) => { editingRef.current = true; setTitle(event.target.value); }} /></div>
            <button className="rounded bg-teal-800 px-5 py-3 font-medium text-white" type="submit">Save title</button>
          </form>
          <p className="mt-3 text-sm text-slate-600">{meetingDate}{detail.meeting.duration_ms ? ` · ${Math.round(detail.meeting.duration_ms / 60000)} min` : ""}</p>
          <button className="mt-3 text-sm text-red-700 underline" onClick={() => void deleteMeeting()}>Delete recording</button>
          <div role="status" aria-live="polite" className="mt-8 rounded-xl border border-teal-200 bg-teal-50 p-5"><strong className="capitalize">{detail.meeting.status}</strong><p className="mt-2 text-sm">{detail.meeting.status === "queued" ? "Your recording is saved and waiting to be transcribed." : detail.meeting.status === "draft" ? "This class has no uploaded recording yet." : detail.meeting.status === "uploading" ? "The recording is uploading. Keep the recording tab open." : detail.meeting.status === "failed" ? `Processing failed${detail.job?.last_error_code ? ` (${detail.job.last_error_code})` : ""}. Your previous notes remain available if you were regenerating them.` : detail.meeting.status === "summarizing" ? detail.has_summary ? "Updated class notes are being prepared. Your previous draft remains below." : "The transcript is saved. Class notes are being prepared." : detail.meeting.status === "ready" ? "Transcript and class notes are ready for your review." : "Your recording is being processed."}</p>{detail.meeting.status === "failed" && <button className="mt-4 rounded bg-teal-800 px-4 py-2 text-white" onClick={() => void retry()}>Retry processing</button>}</div>
          {detail.recording && <p className="mt-5 text-sm text-slate-600">Recording uploaded: {(detail.recording.size_bytes / 1_000_000).toFixed(1)} MB</p>}
          <section className="mt-6 rounded-2xl bg-white p-7 shadow-sm" aria-labelledby="class-notes-heading">
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 pb-5">
              <div>
                <p className="text-sm font-semibold uppercase tracking-wide text-teal-700">AI draft — check against the transcript</p>
                <h2 id="class-notes-heading" className="mt-2 text-2xl font-semibold">Class notes</h2>
                <p className="mt-1 text-sm text-slate-600">{detail.meeting.title} · {meetingDate}</p>
              </div>
              {summary && <div className="flex flex-wrap gap-2">
                {detail.meeting.status === "ready" && <button className="rounded border border-teal-800 px-4 py-2 text-teal-800" onClick={() => void regenerateNotes()}>Regenerate class notes</button>}
                <button className="rounded border border-teal-800 px-4 py-2 text-teal-800" onClick={copyNotes}>Copy notes</button>
                <button className="rounded border border-teal-800 px-4 py-2 text-teal-800" onClick={downloadNotes}>Download .md</button>
              </div>}
            </div>
            {summary ? <div className="mt-6 space-y-8 leading-relaxed">
              <section><h3 className="text-lg font-semibold">Class overview</h3><p className="mt-2">{summary.overview}</p></section>
              <section><h3 className="text-lg font-semibold">Topics covered</h3>{topics.length ? <ol className="mt-3 space-y-5">{topics.map((topic, index) => <li className="rounded-xl border border-slate-200 bg-slate-50 p-5" key={index}><h4 className="text-lg font-semibold">{index + 1}. {topic.heading}</h4><h5 className="mt-3 text-sm font-semibold uppercase tracking-wide text-slate-600">What was explained</h5><p className="mt-1">{topic.summary}</p>{topic.key_details.length > 0 && <><h5 className="mt-4 text-sm font-semibold uppercase tracking-wide text-slate-600">Important details</h5><ul className="mt-2 list-disc space-y-1 pl-6">{topic.key_details.map((point, pointIndex) => <li key={pointIndex}>{point}</li>)}</ul></>}<p className="mt-3 text-sm text-slate-600">{evidence(topic.evidence_segment_ids)}</p></li>)}</ol> : <p className="mt-2 text-slate-500">Topic explanations are unavailable for this older draft. Use “Regenerate class notes” to build them from the saved transcript.</p>}</section>
              <section><h3 className="text-lg font-semibold">Quick review</h3>{summary.key_points.length ? <ul className="mt-2 list-disc space-y-2 pl-6">{summary.key_points.map((point, index) => <li key={index}>{point}</li>)}</ul> : <p className="mt-2 text-slate-500">No review points identified.</p>}</section>
              {summary.decisions.length > 0 && <section><h3 className="text-lg font-semibold">Announcements and decisions</h3><ol className="mt-2 list-decimal space-y-2 pl-6">{summary.decisions.map((item, index) => <li key={index}>{item.text}{evidence(item.evidence_segment_ids)}</li>)}</ol></section>}
              {summary.action_items.length > 0 && <section><h3 className="text-lg font-semibold">Assignments and follow-ups</h3><div className="mt-3 overflow-x-auto"><table className="w-full border-collapse text-left text-sm"><thead><tr className="border-b border-slate-300 text-slate-600"><th scope="col" className="px-3 py-2 font-semibold">Task</th><th scope="col" className="px-3 py-2 font-semibold">Owner</th><th scope="col" className="px-3 py-2 font-semibold">Due date</th></tr></thead><tbody>{summary.action_items.map((item, index) => <tr className="border-b border-slate-200 align-top" key={index}><td className="px-3 py-3">{item.task}{evidence(item.evidence_segment_ids)}</td><td className="px-3 py-3">{item.owner || "Not specified"}</td><td className="px-3 py-3">{item.due_date || "Not specified"}</td></tr>)}</tbody></table></div></section>}
              <section><h3 className="text-lg font-semibold">Questions to revisit</h3>{summary.open_questions.length ? <ul className="mt-2 list-disc space-y-2 pl-6">{summary.open_questions.map((question, index) => <li key={index}>{question}</li>)}</ul> : <p className="mt-2 text-slate-500">No open questions identified.</p>}</section>
            </div> : <p className="mt-5 text-slate-600">Class notes will appear after summarization.</p>}
          </section>
          <section className="mt-10 rounded-2xl bg-white p-7 shadow-sm"><h2 className="text-2xl font-semibold">Transcript</h2>{transcript ? <><div className="mt-4 flex flex-wrap gap-3"><button className="rounded border border-teal-800 px-4 py-2 text-teal-800" onClick={() => void navigator.clipboard.writeText(transcript.full_text)}>Copy transcript</button><button className="rounded border border-teal-800 px-4 py-2 text-teal-800" onClick={downloadTranscript}>Download .txt</button></div><ol className="mt-6 space-y-5">{transcript.segments.map((segment) => <li id={`segment-${segment.id}`} key={segment.id} className="border-t border-slate-200 pt-4"><span className="text-sm text-slate-500">~{Math.floor(segment.start_ms / 60000)}–{Math.ceil(segment.end_ms / 60000)} min</span><p className="mt-2 whitespace-pre-wrap">{segment.text || "[No speech detected in this chunk]"}</p></li>)}</ol></> : <p className="mt-3 text-slate-600">The transcript will appear after transcription completes.</p>}</section>
        </>
      )}
      {message && <p className="mt-5" role="status" aria-live="polite">{message}</p>}
    </main>
  );
}
