import * as vscode from 'vscode';
import { EventQueue } from '../queue/eventQueue';
import { CodeEvent, EventType, GitEventMetadata } from '../types';

// ---------------------------------------------------------------------------
// VS Code Git extension API type stubs
// Only the subset consumed by this watcher is typed here. The full API is
// documented at https://github.com/microsoft/vscode/blob/main/extensions/git/src/api/git.d.ts
// ---------------------------------------------------------------------------

interface GitHead {
  name?: string;
  commit?: string;
}

interface GitRepositoryState {
  HEAD: GitHead | undefined;
  onDidChange: vscode.Event<void>;
}

interface GitRepository {
  state: GitRepositoryState;
}

interface GitExtensionAPI {
  repositories: GitRepository[];
  onDidOpenRepository: vscode.Event<GitRepository>;
}

interface GitExtension {
  getAPI(version: 1): GitExtensionAPI;
}

// ---------------------------------------------------------------------------

/**
 * Subscribes to the built-in VS Code Git extension and emits `git_event`
 * events whenever the HEAD of a repository changes.
 *
 * Detected actions:
 * - `branch_change` — the active branch name changed (checkout, new branch)
 * - `commit`        — a new commit was recorded on the current branch
 *
 * The watcher handles multiple repositories in a multi-root workspace and
 * defers activation if the Git extension has not yet started.
 */
export class GitWatcher implements vscode.Disposable {
  private readonly disposables: vscode.Disposable[] = [];
  private readonly repoListeners = new Map<GitRepository, vscode.Disposable>();
  private readonly repoHeads = new Map<GitRepository, GitHead>();
  private readonly queue: EventQueue;
  private readonly workspaceName: string;

  constructor(queue: EventQueue, workspaceName: string) {
    this.queue = queue;
    this.workspaceName = workspaceName;
    this.init();
  }

  // ---------------------------------------------------------------------------
  // Initialisation
  // ---------------------------------------------------------------------------

  private init(): void {
    const gitExt = vscode.extensions.getExtension<GitExtension>('vscode.git');
    if (!gitExt) {
      // Git extension is unavailable (e.g. disabled by the user)
      return;
    }

    if (!gitExt.isActive) {
      gitExt.activate().then(() => this.attach(gitExt.exports.getAPI(1)));
    } else {
      this.attach(gitExt.exports.getAPI(1));
    }
  }

  private attach(api: GitExtensionAPI): void {
    for (const repo of api.repositories) {
      this.watchRepo(repo);
    }
    // Handle repositories opened after activation (e.g. `git init` in a new folder)
    this.disposables.push(
      api.onDidOpenRepository((repo) => this.watchRepo(repo)),
    );
  }

  private watchRepo(repo: GitRepository): void {
    if (this.repoListeners.has(repo)) {
      return;
    }

    // Capture the current HEAD so we can diff on subsequent changes
    this.repoHeads.set(repo, { ...repo.state.HEAD });

    const listener = repo.state.onDidChange(() => this.onRepoStateChange(repo));
    this.repoListeners.set(repo, listener);
    this.disposables.push(listener);
  }

  // ---------------------------------------------------------------------------
  // Event handlers
  // ---------------------------------------------------------------------------

  private onRepoStateChange(repo: GitRepository): void {
    const prev = this.repoHeads.get(repo);
    const current = repo.state.HEAD;

    if (!current) {
      return;
    }

    let action: GitEventMetadata['action'] | null = null;

    if (prev?.name !== current.name) {
      action = 'branch_change';
    } else if (prev?.commit !== current.commit) {
      action = 'commit';
    }

    if (!action) {
      // State changed but neither branch nor commit moved — ignore
      return;
    }

    const metadata: GitEventMetadata = {
      action,
      branch: current.name,
      previousBranch: prev?.name,
      commitHash: current.commit,
    };

    const rootPath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '';

    const event: CodeEvent = {
      timestamp: Date.now(),
      type: EventType.GitEvent,
      workspace: this.workspaceName,
      filePath: rootPath,
      language: '',
      metadata,
    };

    this.queue.enqueue(event);

    // Advance the stored HEAD for the next diff
    this.repoHeads.set(repo, { ...current });
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  dispose(): void {
    this.repoListeners.forEach((d) => d.dispose());
    this.repoListeners.clear();
    this.disposables.forEach((d) => d.dispose());
  }
}
