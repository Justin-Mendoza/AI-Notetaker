# Repository map

Source revision: `3f279169c3843b77bf5932f79bb601f7bff74120`

Browse the Mermaid diagrams below on GitHub. PDFs and PNGs are linked for download.

[Overview PDF](overview/repository-map.pdf) | [Overview details](overview/README.md)

## meeting-api: How a recording becomes study notes (1/2)

This area is the backend for a local class-recording notes tool. A person on the same machine creates a meeting, uploads audio (or streams live audio in pieces), and the system transcribes it and turns the transcript into structured study notes. Before any work starts, the system checks the file, limits how much can be uploaded, applies per-hour caps, and saves a job and audio record so processing can happen later. Only local requests from a fixed owner are allowed, and there is no real account login.

A local client asks the API to create a meeting and send audio; the system verifies the request is local, checks and stores the audio, queues a job, transcribes it, and builds structured study notes.

```mermaid
%%{init: {"themeVariables": {"fontSize": "22px"}}}%%
flowchart TD
  n0["Local user<br/>client"]
  n1["Meeting notes<br/>API"]
  n2["Local-only<br/>access check"]
  n3["Meeting and<br/>audio handling"]
  n4["Audio checks and<br/>cutting"]
  n5["Saved records<br/>and audio"]
  n0 -->|"Sends meeting<br/>actions"| n1
  n1 -->|"Checks local<br/>request"| n2
  n2 -->|"Allows as local<br/>owner"| n3
  n3 -->|"Passes audio to<br/>check"| n4
  n4 -->|"Stores checked<br/>audio"| n5
```

Read from top to bottom; arrows show what happens next or what is passed along.

[More about this area and its source evidence](maps/meeting-api/README.md)

## operations: How the app starts up

This area is the local launcher and build/run tooling for a class-recording notes app. Shell scripts on a Mac start the database in Docker, choose a local speech-to-text service, then bring up the backend API, a background worker, and the web page, opening it in the browser. Stop scripts and CI checks keep things repeatable; the whole stack stays on the local machine.

A person runs the Mac launcher, which starts the database, picks a local speech service, and brings up the app so the page opens in a browser.

```mermaid
%%{init: {"themeVariables": {"fontSize": "22px"}}}%%
flowchart TD
  n0["Mac launcher<br/>script"]
  n1["Main start-up<br/>script"]
  n2["Local database"]
  n3["Local speech<br/>service"]
  n4["Backend, worker,<br/>web page"]
  n5["Browser page"]
  n0 -->|"Starts and waits"| n1
  n1 -->|"Starts database"| n2
  n1 -->|"Starts chosen<br/>service"| n3
  n1 -->|"Runs app pieces"| n4
  n0 -->|"Opens the page"| n5
```

Read from top to bottom; arrows show what happens next or what is passed along.

[More about this area and its source evidence](maps/operations/README.md)

## persistence: How a meeting's notes data is organized

This area stores and protects the data behind a meeting-notes service: meetings, their uploaded recordings, transcription jobs, transcript text, and generated summaries. It also sets up database structure, private file storage, error replies, and structured logs. Most pieces are foundations (schema, settings, storage); the actual web endpoints and background workers are not shown here.

A meeting is the central record. Its recording, processing job, transcript pieces, and summary all belong to it, and removing the meeting removes them all.

```mermaid
%%{init: {"themeVariables": {"fontSize": "22px"}}}%%
flowchart TD
  n0["Meeting record"]
  n1["Stored recording<br/>info"]
  n2["Processing job"]
  n3["Transcript<br/>segments"]
  n4["Generated<br/>summary"]
  n0 -->|"has one"| n1
  n0 -->|"has one"| n2
  n0 -->|"has many"| n3
  n0 -->|"has one"| n4
  n0 -->|"delete cascades"| n1
```

Read from top to bottom; arrows show what happens next or what is passed along.

[More about this area and its source evidence](maps/persistence/README.md)

## processing: How a recording becomes meeting notes

This area is the background processing engine for a meeting-notes app. A separate worker process quietly picks up queued jobs, converts uploaded audio into text, and turns that text into structured class notes with topics, decisions, and action items. It also periodically deletes expired audio and abandoned drafts. Some provider wiring and the surrounding web endpoints are only partly shown.

A background worker process loops continuously, claiming one queued job at a time, transcribing and then summarizing it, and saving the outcome.

```mermaid
%%{init: {"themeVariables": {"fontSize": "22px"}}}%%
flowchart TD
  n0["Background<br/>worker process"]
  n1["Pick up next job"]
  n2["Download and<br/>prepare audio"]
  n3["Turn speech into<br/>text"]
  n4["Build structured<br/>notes"]
  n5["Save notes and<br/>finish"]
  n0 -.->|"asks for work"| n1
  n1 -.->|"job points to<br/>audio"| n2
  n2 -.->|"sends each audio<br/>chunk"| n3
  n3 -.->|"hands over<br/>transcript"| n4
  n4 -.->|"checklist of<br/>notes"| n5
  n5 -.->|"meeting marked<br/>ready"| n0
```

Read from top to bottom. Dashed arrows show connections that need confirmation.

[More about this area and its source evidence](maps/processing/README.md)

## web: How a class recording becomes study notes

This area is the web workspace for a private class-recording notes tool. From the browser you record a class, watch it upload and be transcribed, then read AI-generated study notes tied back to the transcript. It also lets you browse, rename, regenerate notes for, delete, or recover your recordings.

You record audio in the browser; it is uploaded for processing; afterwards the page shows a transcript and AI-generated notes, refreshed automatically until ready.

```mermaid
%%{init: {"themeVariables": {"fontSize": "22px"}}}%%
flowchart TD
  n0["Record class<br/>audio"]
  n1["Upload recording"]
  n2["Track processing<br/>status"]
  n3["Read notes and<br/>transcript"]
  n0 -->|"stopped audio<br/>sent"| n1
  n1 -->|"opens class page"| n2
  n2 -->|"notes become<br/>ready"| n3
```

Read from top to bottom; arrows show what happens next or what is passed along.

[More about this area and its source evidence](maps/web/README.md)

## Subsystem maps

| Map | Summary | Views | Last analyzed source |
| --- | --- | --- | --- |
| [meeting-api](maps/meeting-api/README.md) | This area is the backend for a local class-recording notes tool. A person on the same machine creates a meeting, uploads audio (or streams live audio in pieces), and the system transcribes it and turns the transcript into structured study notes. Before any work starts, the system checks the file, limits how much can be uploaded, applies per-hour caps, and saves a job and audio record so processing can happen later. Only local requests from a fixed owner are allowed, and there is no real account login. | [PDF](maps/meeting-api/repository-map.pdf) · [JSON](maps/meeting-api/map.json) | `3f279169c384` |
| [operations](maps/operations/README.md) | This area is the local launcher and build/run tooling for a class-recording notes app. Shell scripts on a Mac start the database in Docker, choose a local speech-to-text service, then bring up the backend API, a background worker, and the web page, opening it in the browser. Stop scripts and CI checks keep things repeatable; the whole stack stays on the local machine. | [PDF](maps/operations/repository-map.pdf) · [JSON](maps/operations/map.json) | `3f279169c384` |
| [persistence](maps/persistence/README.md) | This area stores and protects the data behind a meeting-notes service: meetings, their uploaded recordings, transcription jobs, transcript text, and generated summaries. It also sets up database structure, private file storage, error replies, and structured logs. Most pieces are foundations (schema, settings, storage); the actual web endpoints and background workers are not shown here. | [PDF](maps/persistence/repository-map.pdf) · [JSON](maps/persistence/map.json) | `3f279169c384` |
| [processing](maps/processing/README.md) | This area is the background processing engine for a meeting-notes app. A separate worker process quietly picks up queued jobs, converts uploaded audio into text, and turns that text into structured class notes with topics, decisions, and action items. It also periodically deletes expired audio and abandoned drafts. Some provider wiring and the surrounding web endpoints are only partly shown. | [PDF](maps/processing/repository-map.pdf) · [JSON](maps/processing/map.json) | `3f279169c384` |
| [web](maps/web/README.md) | This area is the web workspace for a private class-recording notes tool. From the browser you record a class, watch it upload and be transcribed, then read AI-generated study notes tied back to the transcript. It also lets you browse, rename, regenerate notes for, delete, or recover your recordings. | [PDF](maps/web/repository-map.pdf) · [JSON](maps/web/map.json) | `3f279169c384` |

JSON is the source of truth; Mermaid, PNGs, and PDFs are generated views.

Unchanged subsystem views are retained. Source existence checks do not prove model interpretation. See manifest.json and update.json for dependencies, coverage and updates.
