import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
} from "react";
import {
  ChevronRight,
  Download,
  FileText,
  Folder,
  FolderPlus,
  Home,
  Loader2,
  Pencil,
  Trash2,
  Upload,
} from "lucide-react";
import { api } from "@/lib/api";
import type { FileEntry, FilesReadResponse } from "@/lib/api";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";

function formatBytes(n: number | null | undefined): string {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString();
}

const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico"]);

function isImage(name: string): boolean {
  const ext = name.split(".").pop()?.toLowerCase();
  return ext ? IMAGE_EXT.has(ext) : false;
}

interface Crumb {
  label: string;
  path: string;
}

function buildCrumbs(path: string): Crumb[] {
  if (!path) return [];
  const parts = path.split("/").filter(Boolean);
  const out: Crumb[] = [];
  let acc = "";
  for (const p of parts) {
    acc = acc ? `${acc}/${p}` : p;
    out.push({ label: p, path: acc });
  }
  return out;
}

type RootName = "workspace" | "hermes";

const ROOT_OPTIONS: { key: RootName; label: string; hint: string }[] = [
  {
    key: "workspace",
    label: "Working folder",
    hint: "cwd of `sopify dashboard` (bind-mounted into the sandbox)",
  },
  {
    key: "hermes",
    label: "Hermes home",
    hint: "/home/sopify/.hermes — vibe projects, sessions DB, logs (container-local)",
  },
];

export default function FilesPage() {
  const { toast, showToast } = useToast();
  const [rootName, setRootName] = useState<RootName>("workspace");
  const [cwd, setCwd] = useState<string>("");
  const [root, setRoot] = useState<string>("");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<FileEntry | null>(null);
  const [preview, setPreview] = useState<FilesReadResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragHover, setDragHover] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await api.listFiles(cwd, rootName);
      setRoot(resp.root);
      setEntries(resp.entries);
    } catch (e) {
      showToast(`Load failed: ${(e as Error).message}`, "error");
    } finally {
      setLoading(false);
    }
  }, [cwd, rootName, showToast]);

  // Reset cwd + selection when switching root, otherwise paths from the old
  // root would 403 against the new one's traversal guard.
  const switchRoot = useCallback((next: RootName) => {
    setRootName(next);
    setCwd("");
    setSelected(null);
    setPreview(null);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Clear preview when cwd changes.
  useEffect(() => {
    setSelected(null);
    setPreview(null);
  }, [cwd]);

  const openEntry = useCallback(
    async (e: FileEntry) => {
      if (e.is_dir) {
        setCwd(e.path);
        return;
      }
      setSelected(e);
      setPreview(null);
      if (isImage(e.name)) return; // image is rendered via <img> from download URL
      setPreviewLoading(true);
      try {
        const resp = await api.readFile(e.path, rootName);
        setPreview(resp);
      } catch (err) {
        showToast(`Read failed: ${(err as Error).message}`, "error");
      } finally {
        setPreviewLoading(false);
      }
    },
    [rootName, showToast],
  );

  const uploadFiles = useCallback(
    async (files: FileList | File[]) => {
      const arr = Array.from(files);
      if (arr.length === 0) return;
      setUploading(true);
      try {
        const resp = await api.uploadFiles(cwd, arr, rootName);
        showToast(`Uploaded ${resp.saved.length} file(s)`, "success");
        await refresh();
      } catch (e) {
        showToast(`Upload failed: ${(e as Error).message}`, "error");
      } finally {
        setUploading(false);
      }
    },
    [cwd, rootName, refresh, showToast],
  );

  const onDrop = useCallback(
    async (ev: DragEvent<HTMLDivElement>) => {
      ev.preventDefault();
      setDragHover(false);
      if (ev.dataTransfer.files?.length) {
        await uploadFiles(ev.dataTransfer.files);
      }
    },
    [uploadFiles],
  );

  const onMkdir = useCallback(async () => {
    const name = window.prompt("New folder name");
    if (!name) return;
    const trimmed = name.trim();
    if (!trimmed || trimmed.includes("/") || trimmed === "." || trimmed === "..") {
      showToast("Invalid folder name", "error");
      return;
    }
    const target = cwd ? `${cwd}/${trimmed}` : trimmed;
    try {
      await api.mkdir(target, rootName);
      showToast("Folder created", "success");
      await refresh();
    } catch (e) {
      showToast(`Mkdir failed: ${(e as Error).message}`, "error");
    }
  }, [cwd, rootName, refresh, showToast]);

  const onDelete = useCallback(
    async (e: FileEntry) => {
      const ok = window.confirm(
        e.is_dir
          ? `Delete folder "${e.name}" and ALL its contents?`
          : `Delete file "${e.name}"?`,
      );
      if (!ok) return;
      try {
        await api.deleteFile(e.path, rootName);
        showToast("Deleted", "success");
        if (selected?.path === e.path) {
          setSelected(null);
          setPreview(null);
        }
        await refresh();
      } catch (err) {
        showToast(`Delete failed: ${(err as Error).message}`, "error");
      }
    },
    [refresh, rootName, selected, showToast],
  );

  const onRename = useCallback(
    async (e: FileEntry) => {
      const next = window.prompt("Rename to", e.name);
      if (!next) return;
      const trimmed = next.trim();
      if (!trimmed || trimmed === e.name) return;
      if (trimmed.includes("/")) {
        showToast("Name cannot contain '/'", "error");
        return;
      }
      const parentDir = cwd;
      const dst = parentDir ? `${parentDir}/${trimmed}` : trimmed;
      try {
        await api.renameFile(e.path, dst, rootName);
        showToast("Renamed", "success");
        if (selected?.path === e.path) {
          setSelected(null);
          setPreview(null);
        }
        await refresh();
      } catch (err) {
        showToast(`Rename failed: ${(err as Error).message}`, "error");
      }
    },
    [cwd, rootName, refresh, selected, showToast],
  );

  const crumbs = useMemo(() => buildCrumbs(cwd), [cwd]);

  const currentRootOption = ROOT_OPTIONS.find((o) => o.key === rootName)!;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Toast toast={toast} />

      {/* Root selector — two sections, only one active at a time */}
      <div className="flex flex-col gap-2">
        <div className="inline-flex w-fit overflow-hidden rounded-md border border-border bg-background/40">
          {ROOT_OPTIONS.map((opt) => {
            const active = opt.key === rootName;
            return (
              <button
                key={opt.key}
                onClick={() => switchRoot(opt.key)}
                type="button"
                aria-pressed={active}
                className={
                  "px-3 py-1.5 text-xs font-medium transition-colors " +
                  (active
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-secondary/50")
                }
              >
                {opt.label}
              </button>
            );
          })}
        </div>
        <p className="text-[11px] text-muted-foreground">
          {currentRootOption.hint}
        </p>
      </div>

      {/* Breadcrumb + absolute root path */}
      <div className="flex flex-col gap-1">
        <div className="font-mono-ui text-[10px] tracking-wider uppercase text-muted-foreground">
          {currentRootOption.label}
        </div>
        <div className="font-mono-ui text-xs text-muted-foreground break-all">
          {root || "—"}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1 text-sm">
          <button
            onClick={() => setCwd("")}
            className="inline-flex items-center gap-1 px-2 py-1 hover:bg-secondary/40 rounded"
            type="button"
          >
            <Home className="h-3.5 w-3.5" />
            <span>root</span>
          </button>
          {crumbs.map((c) => (
            <span key={c.path} className="flex items-center gap-1">
              <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
              <button
                onClick={() => setCwd(c.path)}
                className="px-2 py-1 hover:bg-secondary/40 rounded"
                type="button"
              >
                {c.label}
              </button>
            </span>
          ))}
        </div>
      </div>

      {/* Action toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border pb-3">
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="inline-flex items-center gap-1.5 border border-border bg-secondary/30 hover:bg-secondary/60 px-3 py-1.5 text-sm rounded disabled:opacity-50"
          type="button"
        >
          {uploading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Upload className="h-3.5 w-3.5" />
          )}
          Upload
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          hidden
          onChange={async (ev) => {
            if (ev.target.files) {
              await uploadFiles(ev.target.files);
              ev.target.value = "";
            }
          }}
        />
        <button
          onClick={onMkdir}
          className="inline-flex items-center gap-1.5 border border-border bg-secondary/30 hover:bg-secondary/60 px-3 py-1.5 text-sm rounded"
          type="button"
        >
          <FolderPlus className="h-3.5 w-3.5" />
          New folder
        </button>
        <div className="ml-auto text-xs text-muted-foreground">
          {entries.length} item{entries.length === 1 ? "" : "s"}
        </div>
      </div>

      {/* Two-pane: list + preview */}
      <div
        className={`flex flex-1 min-h-0 gap-3 ${
          dragHover ? "ring-2 ring-primary/60 rounded" : ""
        }`}
        onDragOver={(ev) => {
          ev.preventDefault();
          if (!dragHover) setDragHover(true);
        }}
        onDragLeave={() => setDragHover(false)}
        onDrop={onDrop}
      >
        {/* File list */}
        <div className="flex flex-col flex-1 min-w-0 min-h-0 border border-border bg-background/40 rounded">
          {loading ? (
            <div className="flex flex-1 items-center justify-center text-muted-foreground text-sm">
              <Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading…
            </div>
          ) : entries.length === 0 ? (
            <div className="flex flex-1 items-center justify-center text-muted-foreground text-sm">
              Empty folder — drop files here to upload
            </div>
          ) : (
            <div className="flex-1 min-h-0 overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-background/95 backdrop-blur-sm">
                  <tr className="text-muted-foreground text-[10px] uppercase tracking-wider border-b border-border">
                    <th className="text-left font-medium px-3 py-2">Name</th>
                    <th className="text-right font-medium px-3 py-2 w-20">Size</th>
                    <th className="text-right font-medium px-3 py-2 w-40">Modified</th>
                    <th className="px-3 py-2 w-28"></th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((e) => {
                    const isSelected = selected?.path === e.path;
                    return (
                      <tr
                        key={e.path}
                        className={`border-b border-border/40 hover:bg-secondary/30 cursor-pointer ${
                          isSelected ? "bg-secondary/40" : ""
                        }`}
                        onClick={() => openEntry(e)}
                        onDoubleClick={() => openEntry(e)}
                      >
                        <td className="px-3 py-2 min-w-0">
                          <div className="flex items-center gap-2 min-w-0">
                            {e.is_dir ? (
                              <Folder className="h-4 w-4 shrink-0 text-primary" />
                            ) : (
                              <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                            )}
                            <span className="truncate">{e.name}</span>
                          </div>
                        </td>
                        <td className="px-3 py-2 text-right font-mono-ui text-xs text-muted-foreground">
                          {formatBytes(e.size)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono-ui text-[11px] text-muted-foreground">
                          {formatTime(e.mtime)}
                        </td>
                        <td className="px-3 py-2 text-right">
                          <div
                            className="flex items-center justify-end gap-1"
                            onClick={(ev) => ev.stopPropagation()}
                          >
                            {!e.is_dir && (
                              <a
                                href={api.downloadFileUrl(e.path, rootName)}
                                title="Download"
                                className="p-1.5 hover:bg-secondary/60 rounded text-muted-foreground hover:text-foreground"
                              >
                                <Download className="h-3.5 w-3.5" />
                              </a>
                            )}
                            <button
                              onClick={() => onRename(e)}
                              title="Rename"
                              className="p-1.5 hover:bg-secondary/60 rounded text-muted-foreground hover:text-foreground"
                              type="button"
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                            <button
                              onClick={() => onDelete(e)}
                              title="Delete"
                              className="p-1.5 hover:bg-destructive/15 rounded text-muted-foreground hover:text-destructive"
                              type="button"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Preview pane */}
        <div className="flex flex-col w-[45%] min-w-[280px] min-h-0 border border-border bg-background/40 rounded">
          {selected ? (
            <>
              <div className="border-b border-border px-3 py-2 flex items-center gap-2 min-w-0">
                <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                <span className="truncate text-sm">{selected.name}</span>
                <span className="ml-auto text-xs text-muted-foreground shrink-0">
                  {formatBytes(selected.size)}
                </span>
              </div>
              <div className="flex-1 min-h-0 overflow-auto">
                {isImage(selected.name) ? (
                  <img
                    src={api.downloadFileUrl(selected.path, rootName)}
                    alt={selected.name}
                    className="max-w-full max-h-full m-auto"
                  />
                ) : previewLoading ? (
                  <div className="flex h-full items-center justify-center text-muted-foreground text-sm">
                    <Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading…
                  </div>
                ) : preview && "content" in preview ? (
                  <pre className="text-xs font-mono-ui p-3 whitespace-pre-wrap break-all">
                    {preview.content}
                  </pre>
                ) : preview && "too_large" in preview ? (
                  <div className="p-4 text-sm text-muted-foreground">
                    File is {formatBytes(preview.size)} — too large for inline
                    preview. Use{" "}
                    <a
                      href={api.downloadFileUrl(selected.path, rootName)}
                      className="text-primary underline"
                    >
                      Download
                    </a>
                    .
                  </div>
                ) : preview && "binary" in preview ? (
                  <div className="p-4 text-sm text-muted-foreground">
                    Binary file ({formatBytes(preview.size)}). Use{" "}
                    <a
                      href={api.downloadFileUrl(selected.path, rootName)}
                      className="text-primary underline"
                    >
                      Download
                    </a>
                    .
                  </div>
                ) : null}
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center text-muted-foreground text-sm p-6 text-center">
              {dragHover
                ? "Drop files to upload to this folder"
                : "Select a file to preview, or drop files here to upload"}
            </div>
          )}
        </div>
      </div>

    </div>
  );
}
