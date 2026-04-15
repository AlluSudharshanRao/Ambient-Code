import * as vscode from 'vscode';
import { EventQueue } from '../queue/eventQueue';
import { CodeEvent, EventType, CursorMoveMetadata } from '../types';

/**
 * Tracks active editor switches and emits `cursor_move` events.
 *
 * A `cursor_move` event is emitted each time the user switches to a different
 * file, providing the Layer 2 context engine with a low-cost signal for
 * which areas of the codebase the developer is currently navigating.
 *
 * Note: intra-file cursor movement is intentionally *not* tracked — the
 * signal-to-noise ratio is too low and the volume would be excessive.
 * File-level navigation is sufficient for building a working-set model.
 */
export class CursorTracker implements vscode.Disposable {
  private readonly disposables: vscode.Disposable[] = [];
  private readonly queue: EventQueue;
  private readonly workspaceName: string;

  constructor(queue: EventQueue, workspaceName: string) {
    this.queue = queue;
    this.workspaceName = workspaceName;

    this.disposables.push(
      vscode.window.onDidChangeActiveTextEditor(this.onEditorChange, this),
    );

    // Emit for the already-active editor so the context engine knows which
    // file was open at the moment the extension activated.
    if (vscode.window.activeTextEditor) {
      this.emitEvent(vscode.window.activeTextEditor);
    }
  }

  // ---------------------------------------------------------------------------
  // Event handlers
  // ---------------------------------------------------------------------------

  private onEditorChange(editor: vscode.TextEditor | undefined): void {
    if (!editor || editor.document.uri.scheme !== 'file') {
      return;
    }
    this.emitEvent(editor);
  }

  // ---------------------------------------------------------------------------
  // Internal helpers
  // ---------------------------------------------------------------------------

  private emitEvent(editor: vscode.TextEditor): void {
    const position = editor.selection.active;

    const metadata: CursorMoveMetadata = {
      line: position.line,
      character: position.character,
    };

    const event: CodeEvent = {
      timestamp: Date.now(),
      type: EventType.CursorMove,
      workspace: this.workspaceName,
      filePath: editor.document.uri.fsPath,
      language: editor.document.languageId,
      metadata,
    };

    this.queue.enqueue(event);
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  dispose(): void {
    this.disposables.forEach((d) => d.dispose());
  }
}
