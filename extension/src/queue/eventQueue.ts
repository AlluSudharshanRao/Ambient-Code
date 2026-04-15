import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';
import { CodeEvent } from '../types';

/**
 * Append-only NDJSON (Newline-Delimited JSON) event log.
 *
 * ## Responsibilities
 * - Accepts {@link CodeEvent} objects from any collector via {@link enqueue}.
 * - Batches them in memory and flushes to disk on a configurable interval,
 *   so collectors are never blocked on I/O.
 * - Guarantees a final flush on {@link dispose} to avoid losing events on
 *   extension deactivation.
 *
 * ## File format
 * Each line is one JSON-serialised {@link CodeEvent}, terminated by `\n`.
 * This is the standard NDJSON / JSON Lines format, directly consumable by
 * the Python Layer 2 context engine.
 *
 * ## Default path
 * `~/.ambient-code/events.ndjson` — see {@link EventQueue.defaultLogPath}.
 * The directory is created automatically if it does not exist.
 */
export class EventQueue {
  private readonly buffer: CodeEvent[] = [];
  private readonly logPath: string;
  private readonly flushIntervalMs: number;
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private fileHandle: fs.WriteStream | null = null;
  private disposed = false;

  constructor(logPath: string, flushIntervalMs = 5000) {
    this.logPath = logPath;
    this.flushIntervalMs = flushIntervalMs;

    const dir = path.dirname(logPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    this.fileHandle = fs.createWriteStream(logPath, { flags: 'a', encoding: 'utf8' });

    this.fileHandle.on('error', (err) => {
      // Non-fatal: log to stderr so it surfaces in the extension host log
      // without interrupting collection.
      console.error(`[ambient-code] EventQueue write error: ${err.message}`);
    });
  }

  /**
   * Returns the default NDJSON log path: `~/.ambient-code/events.ndjson`.
   */
  static defaultLogPath(): string {
    return path.join(os.homedir(), '.ambient-code', 'events.ndjson');
  }

  /**
   * Adds an event to the in-memory buffer.
   * The event will be written to disk on the next {@link flush} call.
   *
   * @param event - The {@link CodeEvent} to enqueue.
   */
  enqueue(event: CodeEvent): void {
    if (this.disposed) {
      return;
    }
    this.buffer.push(event);
  }

  /**
   * Writes all buffered events to the NDJSON log in a single write call,
   * then clears the buffer.
   *
   * Safe to call when the buffer is empty (no-op).
   */
  flush(): void {
    if (this.buffer.length === 0 || !this.fileHandle) {
      return;
    }

    const batch = this.buffer.splice(0);
    const lines = batch.map((e) => JSON.stringify(e)).join('\n') + '\n';
    this.fileHandle.write(lines);
  }

  /**
   * Starts the periodic flush interval. Idempotent — calling more than
   * once has no effect.
   */
  startFlushInterval(): void {
    if (this.flushTimer !== null) {
      return;
    }
    this.flushTimer = setInterval(() => this.flush(), this.flushIntervalMs);
    // `unref` prevents the timer from keeping the Node process alive if VS Code
    // tears down the extension host while the timer is pending.
    this.flushTimer.unref();
  }

  /**
   * Stops the periodic flush interval without flushing.
   * Use {@link dispose} for a clean shutdown that includes a final flush.
   */
  stopFlushInterval(): void {
    if (this.flushTimer !== null) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }
  }

  /**
   * Stops the flush interval, performs a final flush of any buffered events,
   * and closes the underlying write stream.
   *
   * After calling `dispose`, further {@link enqueue} calls are silently ignored.
   */
  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.stopFlushInterval();
    this.flush();
    this.fileHandle?.end();
    this.fileHandle = null;
  }
}
