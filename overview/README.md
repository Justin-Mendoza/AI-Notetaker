# Repository map

The overview brings together the analyzed architecture view from each subsystem. Open a subsystem map for its source evidence, detailed flows, and uncertainties.

Commit: `3f279169c3843b77bf5932f79bb601f7bff74120` | Generated: 2026-10-19T00:34:02.817194+00:00

[Open PDF](repository-map.pdf)

**AI-generated analysis. Source references are checked for existence and supplied scope; this does not prove semantic correctness.**

## Scope

Source-backed architecture views composed from each subsystem map. See linked subsystem pages for evidence.

0/0 eligible files analyzed; 0 tracked files excluded by policy.

0 API calls. See coverage.json for budgets, exclusions, and usage.

## meeting-api: How a recording becomes study notes (1/2)

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

<details>
<summary>PNG fallback</summary>

![Diagram](diagram-01.png)

</details>

Read from top to bottom; arrows show what happens next or what is passed along.

### Source evidence


## operations: How the app starts up

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

<details>
<summary>PNG fallback</summary>

![Diagram](diagram-02.png)

</details>

Read from top to bottom; arrows show what happens next or what is passed along.

### Source evidence


## persistence: How a meeting's notes data is organized

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

<details>
<summary>PNG fallback</summary>

![Diagram](diagram-03.png)

</details>

Read from top to bottom; arrows show what happens next or what is passed along.

### Source evidence


## processing: How a recording becomes meeting notes

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

<details>
<summary>PNG fallback</summary>

![Diagram](diagram-04.png)

</details>

Read from top to bottom. Dashed arrows show connections that need confirmation.

### Source evidence


## web: How a class recording becomes study notes

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

<details>
<summary>PNG fallback</summary>

![Diagram](diagram-05.png)

</details>

Read from top to bottom; arrows show what happens next or what is passed along.

### Source evidence


## Uncertainties and untraced areas

- Subsystem boundaries and configured or import-inferred dependencies are recorded in manifest.json; they do not establish runtime calls.
