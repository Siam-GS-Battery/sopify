/**
 * useCanvasPreview — decides what the Canvas iframe shows and when to reload.
 *
 * The agent writes website files into the workspace via tool calls. We scan
 * the transcript's tool calls (best-effort) for the most recent ``.html`` a
 * write-type tool touched, pre-fill it as the preview entry, and bump a
 * reload token whenever a write-type tool completes so edits to the page (or
 * its CSS/JS siblings) show up without a manual refresh.
 *
 * The detected path only *seeds* the entry field — the user can override it
 * (e.g. point at a subfolder's index.html), which is the reliable path when
 * detection can't parse a tool's arguments.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import type { Turn } from "@/hooks/useChatStream";

// Tool names that imply a file mutation. Matched case-insensitively against
// the substring, so `write_file`, `create_file`, `str_replace_editor`,
// `apply_patch`, `edit`, `save` etc. all qualify.
const WRITE_TOOL_RE = /(write|create|edit|replace|patch|save|mkdir)/i;

// A path token ending in .html inside a tool's context/summary string.
const HTML_PATH_RE = /([\w./@-]+\.html)\b/i;

/** Strip sandbox/host prefixes so the path is relative to the workspace root. */
function normalizeWorkspacePath(raw: string): string {
  let p = raw.trim().replace(/^["'`(]+|["'`)]+$/g, "");
  // The agent runs in a sandbox that bind-mounts the workspace at /workspace.
  const ws = p.indexOf("/workspace/");
  if (ws >= 0) p = p.slice(ws + "/workspace/".length);
  return p.replace(/^\/+/, "");
}

interface Scan {
  detected: string | null;
  writeCount: number;
}

function scanTools(turns: Turn[]): Scan {
  let detected: string | null = null;
  let writeCount = 0;
  for (const turn of turns) {
    if (turn.kind !== "assistant") continue;
    for (const tool of turn.tools) {
      const isWrite = WRITE_TOOL_RE.test(tool.name);
      if (isWrite && tool.status === "done") writeCount += 1;
      const haystack = `${tool.context ?? ""} ${tool.summary ?? ""}`;
      const m = haystack.match(HTML_PATH_RE);
      if (m && (isWrite || /\.html/i.test(tool.context ?? ""))) {
        detected = normalizeWorkspacePath(m[1]);
      }
    }
  }
  return { detected, writeCount };
}

export interface UseCanvasPreview {
  /** Effective entry path being previewed (user override or detected). */
  path: string;
  setPath: (p: string) => void;
  /** Reload token — changes whenever a write completes or reload() is called. */
  version: number;
  reload: () => void;
  hasPreview: boolean;
  /** True once at least one .html was detected (used to auto-open the canvas). */
  detectedAny: boolean;
}

export function useCanvasPreview(turns: Turn[]): UseCanvasPreview {
  const [userPath, setUserPath] = useState<string | null>(null);
  const [autoPath, setAutoPath] = useState("");
  const [version, setVersion] = useState(0);

  const { detected, writeCount } = useMemo(() => scanTools(turns), [turns]);

  // Adopt a freshly detected entry as the seed (only until the user overrides).
  useEffect(() => {
    if (detected && detected !== autoPath) setAutoPath(detected);
  }, [detected, autoPath]);

  // Reload the frame each time the count of completed writes grows.
  const lastWriteCount = useRef(0);
  useEffect(() => {
    if (writeCount !== lastWriteCount.current) {
      lastWriteCount.current = writeCount;
      setVersion((v) => v + 1);
    }
  }, [writeCount]);

  const path = userPath ?? autoPath;

  return {
    path,
    setPath: setUserPath,
    version,
    reload: () => setVersion((v) => v + 1),
    hasPreview: path.trim().length > 0,
    detectedAny: autoPath.length > 0,
  };
}
