"use client";

import type { Session } from "@supabase/supabase-js";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { components } from "@/lib/api-types";
import { apiUrl, makeClient } from "@/lib/supabase";

type Meeting = components["schemas"]["MeetingOut"];
type MeetingPage = components["schemas"]["MeetingListResponse"];

export default function Home() {
  const [client] = useState(makeClient);
  const [session, setSession] = useState<Session | null>(null);
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  const loadMeetings = useCallback(async (accessToken: string, cursor?: string) => {
    try {
      const url = new URL(`${apiUrl}/v1/meetings`);
      if (cursor) url.searchParams.set("cursor", cursor);
      const response = await fetch(url.toString(), {
        headers: { Authorization: `Bearer ${accessToken}` },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`Meeting request failed (${response.status})`);
      const data: MeetingPage = await response.json();
      setMeetings((current) => cursor ? [...current, ...data.items] : data.items);
      setNextCursor(data.next_cursor);
      setMessage("");
    } catch {
      setMessage("Could not load your meetings. Check the API and try again.");
    }
  }, []);

  useEffect(() => {
    if (!client) return;
    client.auth.getSession().then(({ data }) => {
      setSession(data.session);
      if (data.session) void loadMeetings(data.session.access_token);
    });
    const { data } = client.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      if (nextSession) void loadMeetings(nextSession.access_token);
      else { setMeetings([]); setNextCursor(null); }
    });
    return () => data.subscription.unsubscribe();
  }, [client, loadMeetings]);

  async function sendCode(event: React.FormEvent) {
    event.preventDefault();
    if (!client) return;
    setBusy(true);
    const { error } = await client.auth.signInWithOtp({
      email,
      options: { shouldCreateUser: false },
    });
    setBusy(false);
    if (error) setMessage(error.message);
    else { setSent(true); setMessage("Check your email for a sign-in code or link."); }
  }

  async function verifyCode(event: React.FormEvent) {
    event.preventDefault();
    if (!client) return;
    setBusy(true);
    const { error } = await client.auth.verifyOtp({ email, token: code, type: "email" });
    setBusy(false);
    setMessage(error ? error.message : "Signed in.");
  }

  return (
    <main className="mx-auto min-h-screen max-w-5xl px-6 py-10">
      <header className="mb-16 flex items-center justify-between border-b border-slate-300 pb-5">
        <div className="text-xl font-bold tracking-tight">Meeting Notes</div>
        {session && <button className="rounded border border-slate-400 px-4 py-2" onClick={() => void client?.auth.signOut()}>Sign out</button>}
      </header>
      <div className="grid gap-10 md:grid-cols-2">
        <section>
          <p className="mb-3 text-sm font-semibold uppercase tracking-widest text-teal-700">Private workspace</p>
          <h1 className="mb-5 text-4xl font-semibold leading-tight">Keep the meeting. Find the next step.</h1>
          <p className="max-w-md text-lg leading-relaxed text-slate-700">A place for the meetings you choose to record. Your transcript and draft notes will appear here after processing.</p>
          <p className="mt-6 max-w-md text-sm text-slate-600">Recording starts only when you choose to begin and confirm the consent reminder. Raw audio is removed after processing under the retention policy.</p>
        </section>
        <section className="rounded-2xl bg-white p-7 shadow-sm" aria-label={session ? "Your meetings" : "Sign in"}>
          {!client ? (
            <p>Set the public Supabase values in <code>apps/web/.env.local</code> to enable sign-in.</p>
          ) : session ? (
            <>
              <div className="mb-6 flex items-center justify-between gap-3">
                <h2 className="text-2xl font-semibold">Your meetings</h2>
                <button className="rounded border border-teal-700 px-3 py-2 text-sm text-teal-800" onClick={() => void loadMeetings(session.access_token)}>Refresh</button>
              </div>
              <Link href="/meetings/new" className="mb-6 inline-block rounded bg-teal-800 px-5 py-3 font-medium text-white">New meeting</Link>
              {meetings.length ? <ul className="space-y-3">{meetings.map((meeting) => <li className="rounded-lg border border-slate-200 p-4" key={meeting.id}><Link className="font-semibold text-teal-800 underline" href={`/meetings/${meeting.id}`}>{meeting.title}</Link><div className="mt-1 text-sm text-slate-600">{new Date(meeting.created_at).toLocaleString()} · {meeting.status}</div></li>)}</ul> : <p className="text-slate-600">No meetings yet. Start one when you are ready.</p>}
              {nextCursor && <button className="mt-5 rounded border border-teal-700 px-4 py-2 text-teal-800" onClick={() => void loadMeetings(session.access_token, nextCursor)}>Load more</button>}
            </>
          ) : (
            <>
              <h2 className="mb-2 text-2xl font-semibold">Sign in</h2>
              <p className="mb-6 text-sm text-slate-600">Your meetings are visible only to your account.</p>
              <form onSubmit={sendCode} className="space-y-3">
                <label className="block font-medium" htmlFor="email">Email</label>
                <input className="w-full rounded border border-slate-400 p-3" id="email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
                <button className="rounded bg-teal-800 px-5 py-3 font-medium text-white" disabled={busy} type="submit">Send sign-in code</button>
              </form>
              {sent && <form onSubmit={verifyCode} className="mt-7 space-y-3"><label className="block font-medium" htmlFor="code">Email code</label><input className="w-full rounded border border-slate-400 p-3" id="code" inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={(event) => setCode(event.target.value)} /><button className="rounded bg-teal-800 px-5 py-3 font-medium text-white" disabled={busy} type="submit">Verify code</button></form>}
            </>
          )}
          {message && <p role="status" aria-live="polite" className="mt-5 text-sm text-slate-700">{message}</p>}
        </section>
      </div>
    </main>
  );
}
