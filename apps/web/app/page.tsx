"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { components } from "@/lib/api-types";
import { apiUrl } from "@/lib/api";

type Meeting = components["schemas"]["MeetingOut"];
type MeetingPage = components["schemas"]["MeetingListResponse"];

export default function Home() {
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  const loadMeetings = useCallback(async (cursor?: string) => {
    try {
      const url = new URL(`${apiUrl}/v1/meetings`);
      if (cursor) url.searchParams.set("cursor", cursor);
      const response = await fetch(url.toString(), { cache: "no-store" });
      if (!response.ok) throw new Error();
      const data: MeetingPage = await response.json();
      setMeetings((current) => cursor ? [...current, ...data.items] : data.items);
      setNextCursor(data.next_cursor);
      setMessage("");
    } catch {
      setMessage("Could not load your classes. Check that the local app is running.");
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadMeetings(), 0);
    return () => window.clearTimeout(timer);
  }, [loadMeetings]);

  async function deleteMeeting(id: string, meetingTitle: string) {
    if (!window.confirm(`Permanently delete “${meetingTitle}” and its notes?`)) return;
    try {
      const response = await fetch(`${apiUrl}/v1/meetings/${id}`, { method: "DELETE" });
      if (!response.ok) throw new Error();
      setMeetings((current) => current.filter((meeting) => meeting.id !== id));
      setMessage("Class recording deleted. Private audio cleanup is queued.");
    } catch {
      setMessage("Could not delete the class recording. Check that the local app is running.");
    }
  }

  return (
    <main className="mx-auto min-h-screen max-w-5xl px-6 py-10">
      <header className="mb-16 flex items-center justify-between border-b border-slate-300 pb-5">
        <div className="text-xl font-bold tracking-tight">Class Notes</div>
        <span className="text-sm text-slate-600">On this Mac</span>
      </header>
      <div className="grid gap-10 md:grid-cols-2">
        <section>
          <p className="mb-3 text-sm font-semibold uppercase tracking-widest text-teal-700">Private workspace</p>
          <h1 className="mb-5 text-4xl font-semibold leading-tight">Record class. Understand what you learned.</h1>
          <p className="max-w-md text-lg leading-relaxed text-slate-700">Save a class recording, then review a transcript and study notes organized by topic. Each topic explains what was covered and highlights important details.</p>
          <p className="mt-6 max-w-md text-sm text-slate-600">Recording starts only when you choose to begin and confirm the consent reminder. Raw audio is removed 24 hours after successful transcription; failed recordings are kept for up to seven days for retry.</p>
        </section>
        <section className="rounded-2xl bg-white p-7 shadow-sm" aria-label="Your classes">
          <div className="mb-6 flex items-center justify-between gap-3">
            <h2 className="text-2xl font-semibold">Your classes</h2>
            <button className="rounded border border-teal-700 px-3 py-2 text-sm text-teal-800" onClick={() => void loadMeetings()}>Refresh</button>
          </div>
          <Link href="/meetings/new" className="mb-6 inline-block rounded bg-teal-800 px-5 py-3 font-medium text-white">Record a class</Link>
          {meetings.length ? <ul className="space-y-3">{meetings.map((meeting) => <li className="rounded-lg border border-slate-200 p-4" key={meeting.id}><div className="flex items-start justify-between gap-3"><Link className="font-semibold text-teal-800 underline" href={`/meetings/${meeting.id}`}>{meeting.title}</Link><button className="text-sm text-red-700 underline" onClick={() => void deleteMeeting(meeting.id, meeting.title)}>Delete</button></div><div className="mt-1 text-sm text-slate-600">{new Date(meeting.created_at).toLocaleString()} · {meeting.duration_ms == null ? "No recording" : `${Math.ceil(meeting.duration_ms / 60000)} min`} · {meeting.status}</div></li>)}</ul> : <p className="text-slate-600">No classes yet. Record one when you are ready.</p>}
          {nextCursor && <button className="mt-5 rounded border border-teal-700 px-4 py-2 text-teal-800" onClick={() => void loadMeetings(nextCursor)}>Load more</button>}
          {message && <p role="status" aria-live="polite" className="mt-5 text-sm text-slate-700">{message}</p>}
        </section>
      </div>
    </main>
  );
}
