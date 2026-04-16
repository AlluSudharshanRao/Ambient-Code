/**
 * FindingsWatcher — Layer 1 receiver for Layer 3 Insight Engine findings.
 *
 * Watches `~/.ambient-code/findings.ndjson` for new lines appended by the
 * Python Insight Engine.  Each new line is parsed as a {@link Finding} and
 * routed to the appropriate VS Code surface based on its `severity` field:
 *
 * | Severity  | VS Code surface                                      |
 * |-----------|------------------------------------------------------|
 * | `info`    | Output channel (silent, visible on demand)           |
 * | `warning` | `showInformationMessage` toast + output channel      |
 * | `critical`| `showWarningMessage` toast + output channel          |
 *
 * The watcher uses `fs.watchFile` (polling) rather than `fs.watch` because
 * the findings file may not exist yet when the extension starts — polling
 * tolerates file creation gracefully across platforms.
 *
 * @module findingsWatcher
 */

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Mirrors the Python `Finding` Pydantic model (camelCase serialisation). */
interface Finding {
  id: string;
  timestamp: number;
  workspace: string;
  /** Alias populated by Python's `by_alias=True` serialisation. */
  filePath: string;
  trigger: string;
  severity: 'info' | 'warning' | 'critical';
  title: string;
  body: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 3_000;
const OUTPUT_CHANNEL_NAME = 'Ambient Code';

// ---------------------------------------------------------------------------
// FindingsWatcher
// ---------------------------------------------------------------------------

/**
 * Watches the findings NDJSON file and surfaces new findings inside VS Code.
 *
 * Call {@link start} after construction; call {@link dispose} (or add to
 * `context.subscriptions`) for clean shutdown.
 */
export class FindingsWatcher implements vscode.Disposable {
  private readonly findingsPath: string;
  private readonly outputChannel: vscode.OutputChannel;
  private byteOffset: number = 0;
  private pollTimer: ReturnType<typeof setInterval> | undefined;

  constructor(findingsPath?: string) {
    this.findingsPath =
      findingsPath ??
      path.join(os.homedir(), '.ambient-code', 'findings.ndjson');

    this.outputChannel = vscode.window.createOutputChannel(OUTPUT_CHANNEL_NAME);
  }

  // -------------------------------------------------------------------------
  // Lifecycle
  // -------------------------------------------------------------------------

  /** Start polling the findings file. */
  start(): void {
    // Initialise the byte offset to the current end of file so we do not
    // re-surface findings that were written before this session started.
    this.byteOffset = this._currentFileSize();

    this.pollTimer = setInterval(
      () => this._poll(),
      POLL_INTERVAL_MS,
    );
  }

  /** Stop polling and release resources. */
  dispose(): void {
    if (this.pollTimer !== undefined) {
      clearInterval(this.pollTimer);
      this.pollTimer = undefined;
    }
    this.outputChannel.dispose();
  }

  // -------------------------------------------------------------------------
  // Polling
  // -------------------------------------------------------------------------

  private _poll(): void {
    const size = this._currentFileSize();
    if (size <= this.byteOffset) {
      return;
    }

    let fd: number | undefined;
    try {
      fd = fs.openSync(this.findingsPath, 'r');
      const bytesToRead = size - this.byteOffset;
      const buffer = Buffer.alloc(bytesToRead);
      const bytesRead = fs.readSync(fd, buffer, 0, bytesToRead, this.byteOffset);
      this.byteOffset += bytesRead;

      const text = buffer.subarray(0, bytesRead).toString('utf8');
      const lines = text.split('\n').filter((l) => l.trim() !== '');

      for (const line of lines) {
        this._handleLine(line);
      }
    } catch {
      // File may have been rotated or is temporarily locked — skip this cycle.
    } finally {
      if (fd !== undefined) {
        try { fs.closeSync(fd); } catch { /* ignore */ }
      }
    }
  }

  private _handleLine(line: string): void {
    let finding: Finding;
    try {
      finding = JSON.parse(line) as Finding;
    } catch {
      return;
    }

    if (!finding.title || !finding.severity) {
      return;
    }

    this._logToOutput(finding);
    this._showNotification(finding);
  }

  // -------------------------------------------------------------------------
  // Output channel
  // -------------------------------------------------------------------------

  private _logToOutput(finding: Finding): void {
    const ts = new Date(finding.timestamp).toISOString();
    const fileName = path.basename(finding.filePath ?? '');
    this.outputChannel.appendLine(
      `[${ts}] [${finding.severity.toUpperCase()}] [${finding.trigger}] ${fileName}`,
    );
    this.outputChannel.appendLine(`  ${finding.title}`);
    this.outputChannel.appendLine(`  ${finding.body}`);
    this.outputChannel.appendLine('');
  }

  // -------------------------------------------------------------------------
  // VS Code notifications
  // -------------------------------------------------------------------------

  private _showNotification(finding: Finding): void {
    const label = 'Show Details';
    const msg = `Ambient Code: ${finding.title}`;

    const showDetails = (title: string, body: string) => () => {
      this.outputChannel.show(true);
      this.outputChannel.appendLine(`--- Details: ${title} ---`);
      this.outputChannel.appendLine(body);
      this.outputChannel.appendLine('');
    };

    switch (finding.severity) {
      case 'critical':
        void vscode.window.showWarningMessage(msg, label).then((choice) => {
          if (choice === label) {
            showDetails(finding.title, finding.body)();
          }
        });
        break;

      case 'warning':
        void vscode.window.showInformationMessage(msg, label).then((choice) => {
          if (choice === label) {
            showDetails(finding.title, finding.body)();
          }
        });
        break;

      case 'info':
      default:
        // Silent — visible in output channel only.
        break;
    }
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  private _currentFileSize(): number {
    try {
      return fs.statSync(this.findingsPath).size;
    } catch {
      return 0;
    }
  }
}
