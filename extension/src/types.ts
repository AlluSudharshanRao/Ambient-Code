/**
 * Discriminated union of all event types emitted by the collection layer.
 * These string values are written verbatim into the NDJSON event log and
 * must remain stable — they form the Layer 1 → Layer 2 contract.
 */
export const enum EventType {
  FileChange = 'file_change',
  CursorMove = 'cursor_move',
  FileSave   = 'file_save',
  GitEvent   = 'git_event',
}

/**
 * A single observable event captured by the collection layer.
 *
 * Serialised as one line of NDJSON in `~/.ambient-code/events.ndjson`.
 * The Layer 2 context engine reads this file and processes events in order.
 */
export interface CodeEvent {
  /** Unix timestamp (ms) when the event was enqueued. */
  timestamp: number;
  /** Discriminator — matches one of the {@link EventType} string values. */
  type: EventType;
  /** VS Code workspace folder name (first folder when multi-root). */
  workspace: string;
  /** Absolute path to the file associated with this event. */
  filePath: string;
  /** VS Code language identifier, e.g. `"typescript"`, `"python"`. */
  language: string;
  /**
   * Unified diff string (GNU patch format).
   * Populated for `file_change` and `file_save` events only.
   */
  diff?: string;
  /** Event-type-specific structured payload. See the `*Metadata` interfaces. */
  metadata?: Record<string, unknown>;
}

/**
 * Metadata attached to `git_event` events.
 */
export interface GitEventMetadata extends Record<string, unknown> {
  /** The specific git operation that triggered this event. */
  action: 'branch_change' | 'stash' | 'commit' | 'checkout';
  /** Branch name after the event. */
  branch?: string;
  /** Branch name before a `branch_change` event. */
  previousBranch?: string;
  /** Full commit SHA after a `commit` event. */
  commitHash?: string;
}

/**
 * Metadata attached to `file_change` and `file_save` events.
 */
export interface FileChangeMetadata extends Record<string, unknown> {
  /**
   * True when a single change inserted ≥ 50 characters with no deletions —
   * a heuristic indicator that the content was pasted rather than typed.
   */
  isPaste: boolean;
  /** Number of lines added relative to the previous snapshot. */
  linesAdded: number;
  /** Number of lines removed relative to the previous snapshot. */
  linesRemoved: number;
}

/**
 * Metadata attached to `cursor_move` events.
 */
export interface CursorMoveMetadata extends Record<string, unknown> {
  /** Zero-based line number of the active cursor position. */
  line: number;
  /** Zero-based character offset within the line. */
  character: number;
}
