export interface SmoothStreamerScheduler {
  requestFrame: (callback: FrameRequestCallback) => number;
  cancelFrame: (id: number) => void;
}

/**
 * Separates irregular network deltas from the text cadence shown in the chat.
 * Text advances at a time-based 4 ms per Unicode character, independent of
 * SSE chunk size or display refresh rate. Scroll-up and completion flush at once.
 */
export class SmoothStreamer {
  private queue: string[] = [];
  private head = 0;
  private offset = 0;
  private pendingCharacters = 0;
  private visibleText = '';
  private frameId?: number;
  private previousFrame?: number;
  private fractionalCharacters = 0;
  private finished = false;

  constructor(
    private readonly onUpdate: (text: string) => void,
    private readonly scheduler: SmoothStreamerScheduler = {
      requestFrame: (callback) => window.requestAnimationFrame(callback),
      cancelFrame: (id) => window.cancelAnimationFrame(id),
    },
    private readonly characterDelayMs = 4,
  ) {}

  get text() { return this.visibleText; }
  get queuedCharacters() { return this.pendingCharacters; }

  push(delta: string) {
    if (this.finished || !delta) return;
    this.queue.push(delta);
    for (const _character of delta) this.pendingCharacters++;
    this.schedule();
  }

  /** Replace the visible text, e.g. on reconnect when SSE sends a snapshot. */
  replace(text: string) {
    if (this.finished) return;
    this.cancelPendingFrame();
    this.queue = [];
    this.head = 0;
    this.offset = 0;
    this.pendingCharacters = 0;
    this.previousFrame = undefined;
    this.fractionalCharacters = 0;
    this.visibleText = text;
    this.onUpdate(text);
  }

  /** Finish with an authoritative final response, or flush the pending queue. */
  complete(finalText?: string) {
    if (this.finished) return;
    if (finalText !== undefined) this.replace(finalText);
    else this.flush();
    this.finished = true;
    this.cancelPendingFrame();
  }

  /** Called when the user scrolls away from the bottom; never hold back text. */
  flush() {
    if (!this.pendingCharacters) return;
    this.cancelPendingFrame();
    const remainder: string[] = [];
    while (this.head < this.queue.length) {
      remainder.push(this.queue[this.head].slice(this.offset));
      this.head++;
      this.offset = 0;
    }
    this.queue = [];
    this.head = 0;
    this.offset = 0;
    this.pendingCharacters = 0;
    this.previousFrame = undefined;
    this.fractionalCharacters = 0;
    this.visibleText += remainder.join('');
    this.onUpdate(this.visibleText);
  }

  dispose() {
    this.finished = true;
    this.cancelPendingFrame();
    this.queue = [];
    this.head = 0;
    this.offset = 0;
    this.pendingCharacters = 0;
  }

  private schedule() {
    if (this.frameId !== undefined || this.finished) return;
    this.frameId = this.scheduler.requestFrame(this.tick);
  }

  private cancelPendingFrame() {
    if (this.frameId !== undefined) this.scheduler.cancelFrame(this.frameId);
    this.frameId = undefined;
  }

  private tick: FrameRequestCallback = (timestamp) => {
    this.frameId = undefined;
    const elapsed = this.previousFrame === undefined
      ? 1000 / 60
      : Math.max(0, Math.min(50, timestamp - this.previousFrame));
    this.previousFrame = timestamp;
    this.fractionalCharacters += elapsed / this.characterDelayMs;
    let budget = Math.floor(this.fractionalCharacters);
    this.fractionalCharacters -= budget;
    if (!budget && this.pendingCharacters) budget = 1;

    let added = '';
    while (budget > 0 && this.head < this.queue.length) {
      const segment = this.queue[this.head];
      const codePoint = segment.codePointAt(this.offset);
      if (codePoint === undefined) {
        this.head++;
        this.offset = 0;
        continue;
      }
      const units = codePoint > 0xffff ? 2 : 1;
      added += segment.slice(this.offset, this.offset + units);
      this.offset += units;
      this.pendingCharacters--;
      budget--;
      if (this.offset >= segment.length) {
        this.head++;
        this.offset = 0;
      }
    }
    if (added) {
      this.visibleText += added;
      this.onUpdate(this.visibleText);
    }
    if (this.head >= this.queue.length) {
      this.queue = [];
      this.head = 0;
      this.offset = 0;
      this.previousFrame = undefined;
      this.fractionalCharacters = 0;
    } else {
      this.schedule();
    }
  };
}
