import * as vscode from 'vscode';
import { createPatch } from 'diff';
import { EventQueue } from '../queue/eventQueue';
import { CodeEvent, EventType, FileChangeMetadata } from '../types';

/**
 * Emits `file_save` events with accurate diffs against the last-saved state.
 *
 * While {@link FileWatcher} produces debounced mid-edit diffs, `EditStream`
 * provides the authoritative snapshot at each explicit save. The diff here
 * is always clean: `prevContent` is the exact content at the previous save,
 * not an approximation.
 *
 * This also applies a paste heuristic: if the net character gain since the
 * last save exceeds 50 characters with no line deletions, `isPaste` is set
 * to `true` in the event metadata.
 */
export class EditStream implements vscode.Disposable {
  private readonly disposables: vscode.Disposable[] = [];

  /**
   * Maps absolute file path → content as of the last save (or document open,
   * whichever is more recent).
   */
  private readonly savedSnapshots = new Map<string, string>();

  private readonly queue: EventQueue;
  private readonly workspaceName: string;

  constructor(queue: EventQueue, workspaceName: string) {
    this.queue = queue;
    this.workspaceName = workspaceName;

    // Snapshot all documents that are already open at activation time
    vscode.workspace.textDocuments.forEach((doc) => this.captureSnapshot(doc));

    this.disposables.push(
      vscode.workspace.onDidOpenTextDocument(this.onOpen, this),
      vscode.workspace.onDidSaveTextDocument(this.onSave, this),
      vscode.workspace.onDidCloseTextDocument(this.onClose, this),
    );
  }

  // ---------------------------------------------------------------------------
  // Event handlers
  // ---------------------------------------------------------------------------

  private onOpen(doc: vscode.TextDocument): void {
    this.captureSnapshot(doc);
  }

  private onClose(doc: vscode.TextDocument): void {
    this.savedSnapshots.delete(doc.uri.fsPath);
  }

  private onSave(doc: vscode.TextDocument): void {
    if (doc.uri.scheme !== 'file') {
      return;
    }

    const key = doc.uri.fsPath;
    const currentContent = doc.getText();
    const prevContent = this.savedSnapshots.get(key) ?? '';

    const fileName = doc.fileName.split(/[\\/]/).pop() ?? doc.fileName;
    const patch = createPatch(fileName, prevContent, currentContent, '', '');

    const linesAdded = (patch.match(/^\+(?!\+\+)/gm) ?? []).length;
    const linesRemoved = (patch.match(/^-(?!--)/gm) ?? []).length;

    const netCharsAdded = currentContent.length - prevContent.length;
    const isPaste = netCharsAdded > 50 && linesRemoved === 0;

    const metadata: FileChangeMetadata = { isPaste, linesAdded, linesRemoved };

    const event: CodeEvent = {
      timestamp: Date.now(),
      type: EventType.FileSave,
      workspace: this.workspaceName,
      filePath: key,
      language: doc.languageId,
      diff: patch,
      metadata,
    };

    this.queue.enqueue(event);

    // Advance the snapshot so the next save diffs correctly
    this.savedSnapshots.set(key, currentContent);
  }

  // ---------------------------------------------------------------------------
  // Internal helpers
  // ---------------------------------------------------------------------------

  private captureSnapshot(doc: vscode.TextDocument): void {
    if (doc.uri.scheme === 'file') {
      this.savedSnapshots.set(doc.uri.fsPath, doc.getText());
    }
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  dispose(): void {
    this.savedSnapshots.clear();
    this.disposables.forEach((d) => d.dispose());
  }
}
