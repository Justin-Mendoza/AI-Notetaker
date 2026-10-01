"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { apiUrl } from "@/lib/api";

const MAX_DURATION_MS = 90 * 60 * 1000;
const MAX_BYTES = 100_000_000;
const formats = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus", "audio/ogg"];
type Phase = "idle" | "starting" | "recording" | "finishing" | "uploading" | "error" | "queued";

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

  useEffect(() => {
    if (phase !== "recording" && phase !== "finishing" && phase !== "uploading" && !blob) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "Your recording has not finished uploading.";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [phase, blob]);

  const hasUnsavedAudio = phase === "recording" || phase === "finishing" || phase === "uploading" || !!blob;
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

  useEffect(() => () => {
    if (timerRef.current) clearInterval(timerRef.current);
    interruptedRef.current = true;
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    stopTracks(streamRef.current);
  }, []);

  function stopRecording() {
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
    setPhase("uploading");
    setUploadPercent(0);
    setMessage("Keep this tab open until upload finishes.");
    const form = new FormData();
    form.append("file", recording, `meeting.${extension(recording.type)}`);
    form.append("duration_ms", String(Math.min(MAX_DURATION_MS, Math.max(1, Date.now() - startedAtRef.current))));
    const request = new XMLHttpRequest();
    request.open("POST", `${apiUrl}/v1/meetings/${meetingId}/recording`);
    request.setRequestHeader("Idempotency-Key", key);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) setUploadPercent(Math.round(event.loaded / event.total * 100));
    };
    request.onload = () => {
      if (request.status === 202) {
        setBlob(null);
        setPhase("queued");
        router.push(`/meetings/${meetingId}`);
      } else {
        setPhase("error");
        setMessage(request.status === 413 ? "Recording exceeds the 90-minute or 100 MB limit. Download your copy." : "Upload failed. Retry while this tab remains open, or download your copy.");
      }
    };
    request.onerror = () => {
      setPhase("error");
      setMessage("Network upload failed. Retry while this tab remains open, or download your copy.");
    };
    request.send(form);
  }

  async function startRecording() {
    if (!consent || phase !== "idle") return;
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
      streamRef.current = stream;
      const response = await fetch(`${apiUrl}/v1/meetings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title.trim() || undefined, consent_confirmed: true, consent_policy_version: "v1" }),
      });
      if (!response.ok) throw new Error("Could not create the meeting. Check your connection and try again.");
      const created = await response.json();
      meetingIdRef.current = created.meeting.id;
      uploadKeyRef.current = crypto.randomUUID();
      chunksRef.current = [];
      recordedBytesRef.current = 0;
      interruptedRef.current = false;
      setRecordedBytes(0);
      const recorder = new MediaRecorder(stream, { mimeType: mime });
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
        recordedBytesRef.current += event.data.size;
        setRecordedBytes(recordedBytesRef.current);
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
      recorder.onstop = () => {
        if (timerRef.current) clearInterval(timerRef.current);
        stopTracks(streamRef.current);
        streamRef.current = null;
        const captured = new Blob(chunksRef.current, { type: recorder.mimeType || mime });
        setBlob(captured);
        if (!captured.size || interruptedRef.current) {
          setPhase("error");
          if (!captured.size) setMessage("No audio was captured. Check the microphone and try a new meeting.");
          return;
        }
        void uploadRecording(captured);
      };
      recorder.start(1000);
      startedAtRef.current = Date.now();
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
    <main className="mx-auto max-w-3xl px-6 py-10">
      <Link className="text-teal-800 underline" href="/" onClick={(event) => {
        if (hasUnsavedAudio && !window.confirm("Your recording has not finished uploading. Leave this page?")) event.preventDefault();
      }}>← Meeting library</Link>
      <h1 className="mt-8 text-4xl font-semibold">New meeting</h1>
      <p className="mt-3 text-slate-700">Microphone audio only. Maximum 90 minutes or 100 MB. This tab must remain open until upload completes; a browser crash before upload may lose the recording.</p>
        <div className="mt-8 rounded-2xl bg-white p-7 shadow-sm">
          <label className="block font-medium" htmlFor="meeting-title">Meeting title</label>
          <input id="meeting-title" className="mt-2 w-full rounded border border-slate-400 p-3" maxLength={160} value={title} onChange={(event) => setTitle(event.target.value)} disabled={phase !== "idle"} placeholder="Untitled meeting" />
          <label className="mt-6 flex items-start gap-3 leading-relaxed"><input type="checkbox" className="mt-1" checked={consent} onChange={(event) => setConsent(event.target.checked)} disabled={phase !== "idle"} /><span>I have informed participants and may record this meeting. Recording rules vary by place and context.</span></label>
          {phase === "recording" ? <div className="mt-8"><p className="text-xl font-semibold"><span aria-hidden="true" className="mr-2 inline-block h-3 w-3 rounded-full bg-red-600" />Recording · {clock}</p><p className="mt-2 text-sm text-slate-600">{(recordedBytes / 1_000_000).toFixed(1)} MB captured</p><button className="mt-5 rounded bg-red-700 px-6 py-3 font-semibold text-white" onClick={stopRecording}>Stop recording</button></div> : phase === "idle" ? <button className="mt-8 rounded bg-teal-800 px-6 py-3 font-semibold text-white disabled:opacity-50" disabled={!consent} onClick={() => void startRecording()}>Start recording</button> : <p className="mt-8 font-medium">{phase === "starting" ? "Requesting microphone…" : phase === "finishing" ? "Finishing recording…" : phase === "uploading" ? `Uploading… ${uploadPercent}%` : phase === "queued" ? "Upload complete." : "Recording needs attention."}</p>}
          {phase === "uploading" && <progress className="mt-4 w-full" max={100} value={uploadPercent} aria-label="Upload progress" />}
          {phase === "error" && blob && <div className="mt-5 flex flex-wrap gap-3"><button className="rounded border border-teal-800 px-4 py-2 text-teal-800" onClick={downloadLocal}>Download captured audio</button>{blob.size > 0 && blob.size <= MAX_BYTES && <button className="rounded bg-teal-800 px-4 py-2 text-white" onClick={() => void uploadRecording(blob)}>Retry upload</button>}</div>}
          {message && <p className="mt-5 text-sm text-slate-700" role="status" aria-live="polite">{message}</p>}
        </div>
    </main>
  );
}
