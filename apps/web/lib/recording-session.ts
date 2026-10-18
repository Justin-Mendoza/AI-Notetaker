// One recorder page owns this browser's unfinished recording until it leaves.
export function acquireRecorderSession(): Promise<(() => void) | null> {
  if (!navigator.locks) return Promise.reject(new Error("Use a browser with recording-session protection, such as current Chrome or Edge."));
  return new Promise((resolve, reject) => {
    void navigator.locks.request("class-notes-recorder", { ifAvailable: true }, async (lock) => {
      if (!lock) { resolve(null); return; }
      await new Promise<void>((release) => resolve(release));
    }).catch(reject);
  });
}

export function guardRecordingNavigation(event: MouseEvent): void {
  if (event.defaultPrevented || event.button !== 0) return;
  const target = event.target instanceof Element ? event.target.closest("a[href]") : null;
  if (!(target instanceof HTMLAnchorElement) || target.target === "_blank" || target.hasAttribute("download")) return;
  const next = new URL(target.href, window.location.href);
  if (next.origin === window.location.origin && next.pathname === window.location.pathname && next.search === window.location.search) return;
  if (!window.confirm("Your recording has not finished uploading. Leave this page?")) {
    event.preventDefault();
    event.stopPropagation();
  }
}
