import * as vscode from 'vscode';
import { createPatch } from 'diff';
import { EventQueue } from '../queue/eventQueue';
import { CodeEvent, EventType, FileChangeMetadata } from '../types';

/**
 * Debouncing threshold for classifying a single change as a paste operation.
 * If a single change inserts more than this many characters with no deletions,
 * the event is tagged `isPaste: true`.
 */
const PASTE_CHAR_THRESHOLD = 50;

/**
 * Watches text document changes and emits debounced `file_change` events.
 *
 * Design principle: one event per editing *session* on a file, not per
 * keystroke. A session ends after {@link debounceMs} ms of inactivity.
 * The emitted diff covers the full session, from the first keystroke to
 * the last one before the debounce fires.
 *
 * Snapshot accuracy:
 *   - When a document is opened, its content is captured as a clean baseline.
 *   - On the first edit of an unseen file (opened before the extension
 *     activated), an empty-string baseline is used, producing a diff that
 *     shows the full current content as added lines. This is intentionally
 *     conservative — the accurate per-save diff is handled by {@link EditStream}.
 */
export class FileWatcher implements vscode.Disposable {
  private readonly disposables: vscode.Disposable[] = [];

  /**
   * Per-file state: the content snapshot taken at the start of a debounce
   * window plus the active debounce timer handle.
   */
  private readonly fileState = new Map<
    string,
    { snapshot: string; timer: ReturnType<typeof setTimeout> }
  >();

  /**
   * Clean content snapshots captured when documents are opened.
   * Used as the baseline for the first edit of each session.
   */
  private readonly openSnapshots = new Map<string, string>();

  private readonly debounceMs: number;
  private readonly queue: EventQueue;
  private readonly workspaceName: string;

  constructor(queue: EventQueue, workspaceName: string, debounceMs = 2000) {
    this.queue = queue;
    this.workspaceName = workspaceName;
    this.debounceMs = debounceMs;

    // Snapshot documents that are already open at activation time
    vscode.workspace.textDocuments.forEach((doc) => this.captureOpenSnapshot(doc));

    this.disposables.push(
      vscode.workspace.onDidOpenTextDocument(this.onDidOpen, this),
      vscode.workspace.onDidChangeTextDocument(this.onDidChange, this),
      vscode.workspace.onDidCloseTextDocument(this.onDidClose, this),
    );
  }

  // ---------------------------------------------------------------------------
  // Event handlers
  // ---------------------------------------------------------------------------

  private onDidOpen(doc: vscode.TextDocument): void {
    this.captureOpenSnapshot(doc);
  }

  private onDidClose(doc: vscode.TextDocument): void {
    const key = doc.uri.fsPath;
    const state = this.fileState.get(key);
    if (state) {
      // Flush any pending debounced event before the document disappears
      clearTimeout(state.timer);
      this.fileState.delete(key);
    }
    this.openSnapshots.delete(key);
  }

  private onDidChange(e: vscode.TextDocumentChangeEvent): void {
    const { document: doc, contentChanges: changes } = e;

    if (doc.uri.scheme !== 'file' || changes.length === 0) {
      return;
    }

    const key = doc.uri.fsPath;
    const currentContent = doc.getText();
    const existing = this.fileState.get(key);

    if (existing) {
      // Extend the debounce window; keep the original snapshot
      clearTimeout(existing.timer);
      existing.timer = this.scheduleEmit(key, existing.snapshot, currentContent, doc, changes);
    } else {
      // Start a new debounce window using the most recent open snapshot,
      // falling back to an empty string for documents opened before activation
      const snapshot = this.openSnapshots.get(key) ?? '';
      const timer = this.scheduleEmit(key, snapshot, currentContent, doc, changes);
      this.fileState.set(key, { snapshot, timer });
    }
  }

  // ---------------------------------------------------------------------------
  // Internal helpers
  // ---------------------------------------------------------------------------

  private scheduleEmit(
    key: string,
    snapshot: string,
    currentContent: string,
    doc: vscode.TextDocument,
    changes: readonly vscode.TextDocumentContentChangeEvent[],
  ): ReturnType<typeof setTimeout> {
    return setTimeout(() => {
      this.emitEvent(snapshot, currentContent, doc, changes);
      this.fileState.delete(key);
      // Update the open snapshot so the next editing session diffs cleanly
      this.openSnapshots.set(key, currentContent);
    }, this.debounceMs);
  }

  private emitEvent(
    snapshot: string,
    currentContent: string,
    doc: vscode.TextDocument,
    changes: readonly vscode.TextDocumentContentChangeEvent[],
  ): void {
    const fileName = doc.fileName.split(/[\\/]/).pop() ?? doc.fileName;
    const patch = createPatch(fileName, snapshot, currentContent, '', '');

    const linesAdded = (patch.match(/^\+(?!\+\+)/gm) ?? []).length;
    const linesRemoved = (patch.match(/^-(?!--)/gm) ?? []).length;

    const totalInserted = changes.reduce((sum, c) => sum + c.text.length, 0);
    const totalDeleted = changes.reduce((sum, c) => sum + c.rangeLength, 0);
    const isPaste = totalInserted >= PASTE_CHAR_THRESHOLD && totalDeleted === 0;

    const metadata: FileChangeMetadata = { isPaste, linesAdded, linesRemoved };

    const event: CodeEvent = {
      timestamp: Date.now(),
      type: EventType.FileChange,
      workspace: this.workspaceName,
      filePath: doc.uri.fsPath,
      language: doc.languageId,
      diff: patch,
      metadata,
    };

    this.queue.enqueue(event);
  }

  private captureOpenSnapshot(doc: vscode.TextDocument): void {
    if (doc.uri.scheme === 'file') {
      this.openSnapshots.set(doc.uri.fsPath, doc.getText());
    }
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  dispose(): void {
    for (const { timer } of this.fileState.values()) {
      clearTimeout(timer);
    }
    this.fileState.clear();
    this.openSnapshots.clear();
    this.disposables.forEach((d) => d.dispose());
  }
}
