"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { components } from "@/lib/api-types";
import { apiUrl } from "@/lib/api";
import { clearRecordingBackup } from "@/lib/recording-backup";
import { Icon } from "@/components/icon";

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
      await clearRecordingBackup(id).catch(() => {});
      setMeetings((current) => current.filter((meeting) => meeting.id !== id));
      setMessage("Class recording deleted. Private audio cleanup is queued.");
    } catch {
      setMessage("Could not delete the class recording. Check that the local app is running.");
    }
  }

  const statusLabels: Record<string, string> = { ready: "Ready to study", draft: "Not recorded", queued: "In the queue", uploading: "Uploading", transcribing: "Transcribing", summarizing: "Writing notes", failed: "Needs attention" };

  return (
    <main className="library-page workspace-page">
      <section className="library-hero">
        <div className="hero-copy">
          <p className="eyebrow"><span className="small-star">✳</span> LESS SCRIBBLING. MORE LISTENING.</p>
          <h1>Be in class.<br /><span>Keep the whole lesson.</span></h1>
          <p className="hero-description">Stay with the explanation, the example, the lightbulb moment. Turn your lecture into a transcript and thoughtful study notes, ready when you are.</p>
          <Link href="/meetings/new" className="button-primary"><Icon name="mic" size={18} />Record a class<Icon name="arrow" size={18} /></Link>
          <p className="hero-footnote"><Icon name="clock" size={14} /> Up to 2 hours per recording · Audio processed on your Mac</p>
        </div>
        <aside className="lesson-card" aria-label="How Class Notes works">
          <div className="lesson-card-top"><span className="eyebrow">A GOOD CLASS, KEPT.</span><span className="paper-star" aria-hidden="true">✳</span></div>
          <div className="lesson-illustration" aria-hidden="true"><div className="audio-orb"><Icon name="mic" size={28} /></div><div className="illustration-wave">{[9,18,28,15,38,48,26,40,20,32,14,22].map((height, i) => <i key={i} style={{ height }} />)}</div><span className="note-sticker"><Icon name="check" size={17} />Keep the important bits</span></div>
          <h2>From lecture<br />to lightbulb.</h2>
          <ol className="lesson-steps"><li><span>01</span>Record without missing a moment</li><li><span>02</span>Revisit what was actually said</li><li><span>03</span>Study one clear topic at a time</li></ol>
        </aside>
      </section>
      <section className="class-library" aria-label="Your classes">
        <div className="section-heading"><div><p className="eyebrow">PICK UP WHERE YOU LEFT OFF</p><h2>Your class library<span className="count-badge">{meetings.length}</span></h2></div><button className="button-quiet" onClick={() => void loadMeetings()}><Icon name="refresh" size={16} />Refresh</button></div>
        {meetings.length ? <ul className="class-list">{meetings.map((meeting) => <li className="class-row" key={meeting.id}><span className={`class-icon ${meeting.status === "ready" ? "class-icon-ready" : ""}`}><Icon name={meeting.status === "ready" ? "book" : "file"} size={22} /></span><Link className="class-row-link" href={`/meetings/${meeting.id}`}><h3>{meeting.title}</h3><p>{new Date(meeting.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}<span>·</span>{meeting.duration_ms == null ? "No audio yet" : `${Math.ceil(meeting.duration_ms / 60000)} min recording`}</p></Link><span className={`status-pill status-${meeting.status}`}><i />{statusLabels[meeting.status] || meeting.status}</span><button className="delete-button" aria-label={`Delete ${meeting.title}`} onClick={() => void deleteMeeting(meeting.id, meeting.title)}><Icon name="trash" size={17} /></button><Link className="open-class" href={`/meetings/${meeting.id}`} aria-label={`Open ${meeting.title}`}><Icon name="arrow" size={18} /></Link></li>)}</ul> : <div className="library-empty"><span className="empty-book"><Icon name="book" size={30} /></span><div><h3>Your next lightbulb moment starts here.</h3><p>Record your first class. We’ll keep the notes in one easy-to-find place.</p></div><Link href="/meetings/new" className="button-quiet">Let’s begin<Icon name="arrow" size={17} /></Link></div>}
        {nextCursor && <button className="button-quiet load-more" onClick={() => void loadMeetings(nextCursor)}>Load more classes<Icon name="arrow" size={16} /></button>}
        {message && <p role="status" aria-live="polite" className="app-message">{message}</p>}
      </section>
      <div className="privacy-note"><Icon name="book" size={16} /><p>Yours to record. Yours to review. Audio stays on your Mac for transcription; the transcript goes to Kyma for study notes.</p></div>
    </main>
  );
}
