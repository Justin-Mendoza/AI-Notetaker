"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { apiUrl } from "@/lib/api";
import { Icon } from "@/components/icon";
import { acquireRecorderSession, guardRecordingNavigation } from "@/lib/recording-session";
import { appendRecordingBackup, beginRecordingBackup, clearRecordingBackup, readRecordingBackup, type RecordingBackup } from "@/lib/recording-backup";

const MAX_DURATION_MS = 120 * 60 * 1000;
const MAX_BYTES = 100_000_000;
const LIVE_WINDOW_MS = 60_000;
type LiveSegment = { sequence_no: number; start_ms: number; end_ms: number; text: string };
const formats = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus", "audio/ogg"];
type Phase = "idle" | "starting" | "recording" | "finishing" | "uploading" | "error" | "queued" | "busy";

function stopTracks(stream: MediaStream | null) {
  stream?.getTracks().forEach((track) => track.stop());
}

function extension(mime: string) {
  if (mime.includes("mp4")) return "m4a";
  if (mime.includes("ogg")) return "ogg";
  return "webm";
}

export default function NewMeeting() {
  const router = useRouter();
  const [liveSegments, setLiveSegments] = useState<LiveSegment[]>([]);
  const [liveStatus, setLiveStatus] = useState("Transcript updates will appear here during class.");
  const [backupChecked, setBackupChecked] = useState(false);
  const [title, setTitle] = useState("");
  const [consent, setConsent] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [recordedBytes, setRecordedBytes] = useState(0);
  const [uploadPercent, setUploadPercent] = useState(0);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [message, setMessage] = useState("");
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recordedBytesRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAtRef = useRef(0);
  const meetingIdRef = useRef<string | null>(null);
  const uploadKeyRef = useRef<string | null>(null);
  const interruptedRef = useRef(false);
  const durationRef = useRef(0);
  const liveNextRef = useRef(0);
  const liveStoppedRef = useRef(true);
  const liveRetryAtRef = useRef(0);
  const livePromiseRef = useRef<Promise<void> | null>(null);
  const sessionReleaseRef = useRef<(() => void) | null>(null);
  const unmountedRef = useRef(false);
  const backupRef = useRef<RecordingBackup | null>(null);
  const backupWritesRef = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      void (async () => {
        let release: (() => void) | null;
        try { release = await acquireRecorderSession(); }
        catch (error) {
          if (active) { setPhase("busy"); setMessage(error instanceof Error ? error.message : "Could not protect this recording session."); }
          return;
        }
        if (!active) { release?.(); return; }
        if (!release) {
          setPhase("busy");
          setMessage("The recorder is open in another tab. Return to that tab, or close it and reload this page before recording or recovering audio.");
          return;
        }
        sessionReleaseRef.current = release;
        try {
          const saved = await readRecordingBackup();
          if (!active || !saved) return;
          meetingIdRef.current = saved.metadata.meetingId;
          uploadKeyRef.current = saved.metadata.uploadKey;
          durationRef.current = saved.metadata.durationMs;
          setElapsed(saved.metadata.durationMs);
          setTitle(saved.metadata.title);
          setBlob(saved.audio);
          setPhase("error");
          setMessage("Recovered audio from an unfinished recording. Download a copy or retry upload. Recording did not continue while this page was closed.");
        } catch {
          if (active) setMessage("Browser backup storage is unavailable. Keep this tab open while recording.");
        } finally { if (active) setBackupChecked(true); }
      })();
    }, 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, []);

  useEffect(() => {
    if (phase !== "starting" && phase !== "recording" && phase !== "finishing" && phase !== "uploading" && !blob) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "Your recording has not finished uploading.";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [phase, blob]);

  const hasUnsavedAudio = phase === "starting" || phase === "recording" || phase === "finishing" || phase === "uploading" || !!blob;
  useEffect(() => {
    if (!hasUnsavedAudio) return;
    document.addEventListener("click", guardRecordingNavigation, true);
    return () => document.removeEventListener("click", guardRecordingNavigation, true);
  }, [hasUnsavedAudio]);

  useEffect(() => {
    if (!hasUnsavedAudio) return;
    window.history.pushState({ meetingRecordingGuard: true }, "", window.location.href);
    const warnOnBack = () => {
      if (window.confirm("Your recording has not finished uploading. Leave this page?")) {
        window.removeEventListener("popstate", warnOnBack);
        window.history.back();
      } else {
        window.history.pushState({ meetingRecordingGuard: true }, "", window.location.href);
      }
    };
    window.addEventListener("popstate", warnOnBack);
    return () => window.removeEventListener("popstate", warnOnBack);
  }, [hasUnsavedAudio]);

  useEffect(() => {
    unmountedRef.current = false;
    return () => {
      unmountedRef.current = true;
      if (timerRef.current) clearInterval(timerRef.current);
      interruptedRef.current = true;
      liveStoppedRef.current = true;
      if (recorderRef.current?.state === "recording") recorderRef.current.stop();
      else void backupWritesRef.current.finally(() => { sessionReleaseRef.current?.(); sessionReleaseRef.current = null; });
      stopTracks(streamRef.current);
    };
  }, []);

  async function transcribeLivePrefix(mime: string) {
    if (liveStoppedRef.current || livePromiseRef.current || Date.now() < liveRetryAtRef.current) return;
    if (Date.now() - startedAtRef.current < (liveNextRef.current + 1) * LIVE_WINDOW_MS + 2500) return;
    const meetingId = meetingIdRef.current;
    const key = uploadKeyRef.current;
    if (!meetingId || !key) return;
    const sequence = liveNextRef.current;
    // Include the original container header. Individual MediaRecorder blobs are not standalone files.
    const prefix = new Blob(chunksRef.current, { type: mime });
    const form = new FormData();
    form.append("file", prefix, `live.${extension(mime)}`);
    form.append("sequence_no", String(sequence));
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 100_000);
    setLiveStatus(`Transcribing minute ${sequence + 1} on your Mac…`);
    const task = (async () => {
      try {
        const response = await fetch(`${apiUrl}/v1/meetings/${meetingId}/live-transcript`, {
          method: "POST", headers: { "Idempotency-Key": key }, body: form, signal: controller.signal,
        });
        if (!response.ok) throw new Error("Live transcription paused");
        const segment: LiveSegment = await response.json();
        liveNextRef.current = sequence + 1;
        setLiveSegments((current) => [...current.filter((item) => item.sequence_no !== sequence), segment]);
        setLiveStatus(`Transcript saved through ${sequence + 1} min. Still listening.`);
      } catch {
        liveRetryAtRef.current = Date.now() + 15_000;
        setLiveStatus("Live transcription is catching up. Your audio is still recording; any missing transcript will be completed after you stop.");
      } finally {
        window.clearTimeout(timeout);
        livePromiseRef.current = null;
      }
    })();
    livePromiseRef.current = task;
    await task;
  }

  function stopRecording() {
    liveStoppedRef.current = true;
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
    setPhase("finishing");
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    stopTracks(streamRef.current);
    streamRef.current = null;
  }

  async function uploadRecording(recording: Blob) {
    const meetingId = meetingIdRef.current;
    const key = uploadKeyRef.current;
    if (!meetingId || !key) return;
    await backupWritesRef.current;
    await livePromiseRef.current;
    setPhase("uploading");
    setUploadPercent(0);
    setMessage("Keep this tab open until upload finishes.");
    const form = new FormData();
    form.append("file", recording, `meeting.${extension(recording.type)}`);
    form.append("duration_ms", String(durationRef.current));
    form.append("live_transcription", "true");
    const request = new XMLHttpRequest();
    request.open("POST", `${apiUrl}/v1/meetings/${meetingId}/recording`);
    request.setRequestHeader("Idempotency-Key", key);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) setUploadPercent(Math.round(event.loaded / event.total * 100));
    };
    request.onload = () => {
      if (request.status === 202) {
        void clearRecordingBackup(meetingId).catch(() => {});
        setBlob(null);
        setPhase("queued");
        router.push(`/meetings/${meetingId}`);
      } else {
        setPhase("error");
        setMessage(request.status === 413 ? "Recording exceeds the 120-minute or 100 MB limit. Download your copy." : "Upload failed. Retry while this tab remains open, or download your copy.");
      }
    };
    request.onerror = () => {
      setPhase("error");
      setMessage("Network upload failed. Retry while this tab remains open, or download your copy.");
    };
    request.send(form);
  }

  async function startRecording() {
    if (!backupChecked || !consent || phase !== "idle") return;
    setMessage("");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setMessage("This browser cannot record audio here. Use a current desktop browser over HTTPS or localhost.");
      return;
    }
    const mime = formats.find((candidate) => MediaRecorder.isTypeSupported(candidate));
    if (!mime) {
      setMessage("This browser does not offer a supported recording format. Try current Chrome, Edge, or Safari.");
      return;
    }
    setPhase("starting");
    let stream: MediaStream | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (unmountedRef.current) { stopTracks(stream); return; }
      streamRef.current = stream;
      const response = await fetch(`${apiUrl}/v1/meetings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title.trim() || undefined, consent_confirmed: true, consent_policy_version: "v1" }),
      });
      if (!response.ok) throw new Error("Could not start this class recording. Check your connection and try again.");
      const created = await response.json();
      if (unmountedRef.current) { stopTracks(stream); return; }
      meetingIdRef.current = created.meeting.id;
      uploadKeyRef.current = crypto.randomUUID();
      chunksRef.current = [];
      recordedBytesRef.current = 0;
      interruptedRef.current = false;
      liveNextRef.current = 0;
      liveRetryAtRef.current = 0;
      setLiveSegments([]);
      setLiveStatus("Listening. The first transcript appears after about a minute of audio.");
      setRecordedBytes(0);
      backupRef.current = { meetingId: created.meeting.id, uploadKey: uploadKeyRef.current!, title, mime, durationMs: 1 };
      try {
        await beginRecordingBackup(backupRef.current);
        void navigator.storage?.persist?.().catch(() => false);
      } catch {
        backupRef.current = null;
        setMessage("Disk backup is unavailable. Keep this tab open; captured audio is held in memory until upload.");
      }
      if (unmountedRef.current) { stopTracks(stream); return; }
      const recorder = new MediaRecorder(stream, { mimeType: mime, audioBitsPerSecond: 64_000 });
      recorderRef.current = recorder;
      stream.getAudioTracks().forEach((track) => {
        track.onended = () => {
          if (recorder.state !== "recording") return;
          interruptedRef.current = true;
          setMessage("The microphone disconnected. Download the captured audio if available.");
          stopRecording();
        };
      });
      recorder.ondataavailable = (event) => {
        if (event.data.size === 0) return;
        chunksRef.current.push(event.data);
        if (backupRef.current) {
          const metadata = { ...backupRef.current, mime: recorder.mimeType || mime, durationMs: Math.min(MAX_DURATION_MS, Math.max(1, Date.now() - startedAtRef.current)) };
          backupWritesRef.current = backupWritesRef.current.then(() => appendRecordingBackup(event.data, metadata)).catch(() => {
            backupRef.current = null;
            setMessage("Disk backup failed. Keep this tab open and download the captured audio after stopping.");
          });
        }
        recordedBytesRef.current += event.data.size;
        setRecordedBytes(recordedBytesRef.current);
        void transcribeLivePrefix(recorder.mimeType || mime);
        if (recordedBytesRef.current > MAX_BYTES && recorder.state === "recording") {
          interruptedRef.current = true;
          setMessage("The recording passed 100 MB. It stopped; download a local copy.");
          stopRecording();
        }
      };
      recorder.onerror = () => {
        interruptedRef.current = true;
        setMessage("Recording was interrupted. Download the captured audio if available.");
        stopRecording();
      };
      recorder.onstop = async () => {
        if (timerRef.current) clearInterval(timerRef.current);
        stopTracks(streamRef.current);
        streamRef.current = null;
        durationRef.current = Math.min(MAX_DURATION_MS, Math.max(1, Date.now() - startedAtRef.current));
        const captured = new Blob(chunksRef.current, { type: recorder.mimeType || mime });
        setBlob(captured);
        await backupWritesRef.current;
        if (unmountedRef.current) { sessionReleaseRef.current?.(); sessionReleaseRef.current = null; return; }
        if (!captured.size || interruptedRef.current) {
          setPhase("error");
          if (!captured.size) setMessage("No audio was captured. Check the microphone and try a new recording.");
          return;
        }
        await backupWritesRef.current;
        void uploadRecording(captured);
      };
      recorder.start(1000);
      startedAtRef.current = Date.now();
      liveStoppedRef.current = false;
      setPhase("recording");
      timerRef.current = setInterval(() => {
        const ms = Date.now() - startedAtRef.current;
        setElapsed(ms);
        if (ms >= MAX_DURATION_MS - 1000) stopRecording();
      }, 1000);
    } catch (error) {
      stopTracks(stream);
      streamRef.current = null;
      setPhase("idle");
      const name = error instanceof DOMException ? error.name : "";
      setMessage(name === "NotAllowedError" ? "Microphone access was denied. Allow it in your browser settings and try again." : name === "NotFoundError" ? "No microphone was found. Connect one and try again." : error instanceof Error ? error.message : "Could not start recording. Try again.");
    }
  }

  async function discardBackup() {
    if (!window.confirm("Discard the saved recording? Download a copy first if you need it.")) return;
    await backupWritesRef.current;
    try {
      if (meetingIdRef.current) await clearRecordingBackup(meetingIdRef.current);
    } catch {
      setMessage("Could not remove the browser backup. Try again before starting another recording.");
      return;
    }
    setBlob(null);
    setElapsed(0);
    setLiveSegments([]);
    setPhase("idle");
    setMessage("");
  }

  function downloadLocal() {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `meeting.${extension(blob.type)}`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  const clock = `${String(Math.floor(elapsed / 60_000)).padStart(2, "0")}:${String(Math.floor(elapsed / 1000) % 60).padStart(2, "0")}`;

  return (
    <main className="workspace-page record-page">
      <Link className="back-link" href="/">← Back to your library</Link>
      <div className="page-heading"><p className="eyebrow">FOR YOUR NEXT LIGHTBULB MOMENT</p><h1>Make room for listening.</h1><p>Settle in, press record, and follow the lesson. We’ll help you turn what you hear into something you can study.</p></div>
      <div className="record-layout">
        <section className="recorder-card" aria-label="Class recorder">
          <label className="field-label" htmlFor="meeting-title">Give this class a name</label>
          <input id="meeting-title" className="class-title-input" maxLength={160} value={title} onChange={(event) => setTitle(event.target.value)} disabled={phase !== "idle"} placeholder="e.g. Biology · Photosynthesis" />
          <div className="record-center">
            <span className={`record-symbol ${phase === "recording" ? "is-recording" : ""}`}><Icon name="mic" size={29} /></span>
            <p className="record-time">{clock}</p>
            <p className="record-label" role="status" aria-live="polite">{phase === "recording" ? `Recording · ${(recordedBytes / 1_000_000).toFixed(1)} MB captured` : phase === "idle" ? "A new lesson, ready to capture." : phase === "starting" ? "Requesting microphone…" : phase === "finishing" ? "Saving the last moments…" : phase === "uploading" ? `Uploading your class… ${uploadPercent}%` : phase === "queued" ? "All saved. Let’s make sense of it." : phase === "busy" ? "Another recorder tab is open." : "Your recording needs a little attention."}</p>
            {phase === "recording" ? <button className="button-primary" onClick={stopRecording}><span aria-hidden="true">■</span>Stop recording</button> : phase === "idle" ? <button className="button-primary" disabled={!backupChecked || !consent} onClick={() => void startRecording()}><Icon name="mic" size={16} />Start recording</button> : null}
            {phase === "uploading" && <progress className="mt-4 w-full" max={100} value={uploadPercent} aria-label="Upload progress" />}
            <p className="record-limit">Up to 2 hours · 100 MB maximum · Microphone audio only</p>
            {phase === "error" && blob && <div className="backup-actions"><button className="button-quiet" onClick={downloadLocal}>Download captured audio</button>{blob.size > 0 && blob.size <= MAX_BYTES && <button className="button-primary" onClick={() => void uploadRecording(blob)}>Retry upload<Icon name="arrow" size={15} /></button>}<button className="button-quiet" onClick={() => void discardBackup()}>Discard recording</button></div>}
          </div>
          <label className="consent-row"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} disabled={phase !== "idle"} /><span>I have informed the people who need to know and may record this class. Recording rules and school policies vary.</span></label>
          {message && <p className="record-message" role="status" aria-live="polite">{message}</p>}
        </section>
        <aside className="record-guide"><p className="eyebrow">A LITTLE PREPARATION GOES A LONG WAY</p><h2>Better audio.<br />Better understanding.</h2><div className="guide-item"><span className="guide-icon"><Icon name="mic" size={17} /></span><div><h3>Let the professor come through</h3><p>Keep your microphone close to the speaker and away from rustling bags or keyboard noise.</p></div></div><div className="guide-item"><span className="guide-icon"><Icon name="clock" size={17} /></span><div><h3>Keep your Mac awake</h3><p>Leave the lid open, stay plugged in, and keep this tab open until your upload finishes.</p></div></div><div className="guide-item"><span className="guide-icon"><Icon name="book" size={17} /></span><div><h3>Come back to clear notes</h3><p>Your transcript builds during class. DeepSeek prepares detailed topics, examples, and assignments after you stop.</p></div></div><p className="record-reminder">Audio is backed up in this browser when storage is available. After an interruption, reopen this page in the same browser to recover what was captured. Recording pauses while your Mac sleeps or the page is closed.</p></aside>
      </div>
      {(phase !== "idle" || liveSegments.length > 0) && <section className="live-transcript-card" aria-label="Live class transcript"><div className="section-heading"><div><p className="eyebrow">LESS WAITING AFTER CLASS</p><h2>As the lesson unfolds.</h2></div><span className="status-pill"><i />Near-live transcript</span></div><p className="live-caption" role="status" aria-live="polite">{phase === "finishing" || phase === "uploading" ? "Finishing the recording. Any remaining audio will be transcribed before your study notes are prepared." : liveStatus}</p><div className="live-transcript-text">{liveSegments.map((segment) => <p key={segment.sequence_no}><span>{Math.floor(segment.start_ms / 60000)}–{Math.ceil(segment.end_ms / 60000)} min</span>{segment.text || "No clear speech detected in this minute."}</p>)}</div></section>}
    </main>
  );
}
