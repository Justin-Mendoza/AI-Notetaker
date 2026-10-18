// Keep one unfinished recording on this browser's disk, including its ordered chunks.
export type RecordingBackup = {
  meetingId: string;
  uploadKey: string;
  title: string;
  mime: string;
  durationMs: number;
};

async function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("class-notes-recording", 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore("metadata");
      request.result.createObjectStore("chunks", { autoIncrement: true });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function write(action: (tx: IDBTransaction) => void) {
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(["metadata", "chunks"], "readwrite");
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error ?? new Error("Backup interrupted"));
      action(tx);
    });
  } finally {
    db.close();
  }
}

export function clearRecordingBackup(meetingId: string) {
  return write((tx) => {
    const metadata = tx.objectStore("metadata");
    const request = metadata.get("active");
    request.onsuccess = () => {
      if (request.result?.meetingId !== meetingId) return;
      metadata.clear();
      tx.objectStore("chunks").clear();
    };
  });
}

export function beginRecordingBackup(metadata: RecordingBackup) {
  return write((tx) => {
    const store = tx.objectStore("metadata");
    const current = store.get("active");
    const count = tx.objectStore("chunks").count();
    count.onsuccess = () => {
      if (count.result && (current.result?.meetingId !== metadata.meetingId || current.result?.uploadKey !== metadata.uploadKey)) { tx.abort(); return; }
      tx.objectStore("chunks").clear();
      store.put(metadata, "active");
    };
  });
}

export function appendRecordingBackup(chunk: Blob, metadata: RecordingBackup) {
  return write((tx) => {
    const store = tx.objectStore("metadata");
    const request = store.get("active");
    request.onsuccess = () => {
      const current = request.result as RecordingBackup | undefined;
      if (current?.meetingId !== metadata.meetingId || current.uploadKey !== metadata.uploadKey) { tx.abort(); return; }
      tx.objectStore("chunks").add(chunk);
      store.put(metadata, "active");
    };
  });
}

export async function readRecordingBackup(): Promise<{ metadata: RecordingBackup; audio: Blob } | null> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(["metadata", "chunks"], "readonly");
      const metadata = tx.objectStore("metadata").get("active");
      const chunks = tx.objectStore("chunks").getAll();
      tx.oncomplete = () => {
        const saved = metadata.result as RecordingBackup | undefined;
        resolve(saved && chunks.result.length ? { metadata: saved, audio: new Blob(chunks.result, { type: saved.mime }) } : null);
      };
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}
