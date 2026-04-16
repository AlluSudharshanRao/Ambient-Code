import * as vscode from 'vscode';
import { EventQueue } from './queue/eventQueue';
import { FileWatcher } from './collectors/fileWatcher';
import { CursorTracker } from './collectors/cursorTracker';
import { EditStream } from './collectors/editStream';
import { GitWatcher } from './collectors/gitWatcher';
import { FindingsWatcher } from './findings/findingsWatcher';

let queue: EventQueue | undefined;
let findingsWatcher: FindingsWatcher | undefined;
let collectors: vscode.Disposable[] = [];

/**
 * Called by VS Code when the extension activates (`onStartupFinished`).
 *
 * Reads configuration, creates the {@link EventQueue}, starts all four
 * collectors, and registers everything with the extension context for
 * automatic cleanup on deactivation.
 */
export function activate(context: vscode.ExtensionContext): void {
  const config = vscode.workspace.getConfiguration('ambientCode');

  const logPath: string =
    config.get<string>('dbPath') || EventQueue.defaultLogPath();

  const debounceMs = config.get<number>('debounceMs') ?? 2000;
  const flushIntervalMs = config.get<number>('flushIntervalMs') ?? 5000;

  const workspaceName =
    vscode.workspace.workspaceFolders?.[0]?.name ?? 'unknown';

  queue = new EventQueue(logPath, flushIntervalMs);
  queue.startFlushInterval();

  collectors = [
    new FileWatcher(queue, workspaceName, debounceMs),
    new CursorTracker(queue, workspaceName),
    new EditStream(queue, workspaceName),
    new GitWatcher(queue, workspaceName),
  ];

  // Layer 3: watch findings.ndjson for insights from the Insight Engine.
  findingsWatcher = new FindingsWatcher();
  findingsWatcher.start();

  context.subscriptions.push(...collectors, findingsWatcher, {
    dispose: () => queue?.dispose(),
  });

  vscode.window.setStatusBarMessage(
    `Ambient Code: collecting → ${logPath}`,
    5000,
  );
}

/**
 * Called by VS Code when the extension deactivates or VS Code shuts down.
 *
 * Collectors and the event queue are disposed via `context.subscriptions`
 * automatically; this function provides an explicit cleanup path for any
 * edge-cases where VS Code calls `deactivate` directly.
 */
export function deactivate(): void {
  collectors.forEach((c) => c.dispose());
  collectors = [];
  findingsWatcher?.dispose();
  findingsWatcher = undefined;
  queue?.dispose();
  queue = undefined;
}
