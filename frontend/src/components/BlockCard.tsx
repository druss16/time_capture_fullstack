import { useMemo, useState } from "react";
import { BlockDto } from "../types";
import { labelBlock } from "../api/blocks";

// ----- helpers (mirror DailyReview) -----
function isIdle(b: BlockDto) {
  const t = (b.window_title || (b as any).title || "").trim();
  return (b as any).bundle_id === "__idle__" || (b as any).app_name === "Idle" || t === "Uncategorized - Idle";
}
function isIdleOnlyCats(cats?: Record<string, number> | null) {
  if (!cats) return false;
  const keys = Object.keys(cats);
  return keys.length === 1 && keys[0].trim().toLowerCase() === "uncategorized - idle";
}
function cleanName(v?: string | null) {
  if (!v) return "";
  const t = String(v).trim();
  if (!t) return "";
  const BAD = new Set(["none", "unassigned", "—", "-", "(none)"]);
  if (BAD.has(t.toLowerCase())) return "";
  return t.slice(0, 120);
}
function sanitizeCategories(obj: Record<string, any> | undefined | null) {
  const out: Record<string, number> = {};
  if (!obj) return out;
  for (const [k, v] of Object.entries(obj)) {
    if (v == null) continue;
    const s = String(v).toLowerCase().replace(/h(rs)?$/i, "").trim();
    const num = Number(s);
    if (Number.isFinite(num) && num >= 0) out[String(k).trim()] = num;
  }
  return out;
}

// simple UI helpers for a tiny categories editor
function stringifyCats(cats?: Record<string, number>) {
  if (!cats) return "";
  return Object.entries(cats).map(([k, v]) => `${k}=${v}`).join(", ");
}
function parseCats(input: string) {
  const out: Record<string, number> = {};
  input.split(",").forEach(part => {
    const [kRaw, vRaw] = part.split("=").map(s => (s || "").trim());
    if (!kRaw) return;
    const num = Number((vRaw || "0").toLowerCase().replace(/h(rs)?$/i, ""));
    if (Number.isFinite(num) && num >= 0) out[kRaw] = num;
  });
  return out;
}

type Props = {
  block: BlockDto & {
    client_name?: string | null;
    project_name?: string | null;
    categories?: Record<string, number>;
    ai_confidence?: number;
    ai_suggestion?: any;
  };
  onLabeled: (updatedData: any, originalSuggestion?: any) => void;
};

export default function BlockCard({ block, onLabeled }: Props) {
  const [isEditing, setIsEditing] = useState(false);

  // seed from normalized fields first
  const [client, setClient] = useState(block.client_name || block.client || "");
  const [project, setProject] = useState(block.project_name || block.project || "");
  const [notes, setNotes] = useState((block as any).notes || "");
  const [catsStr, setCatsStr] = useState(stringifyCats(block.categories));

  const [busy, setBusy] = useState(false);

  const urlDomain = useMemo(() => {
    if (!block.url) return null;
    try { return new URL(block.url).hostname; } catch { return null; }
  }, [block.url]);

  const displayTitle = block.window_title || (block as any).title || "Unknown Activity";
  const idleLike = isIdle(block) || isIdleOnlyCats(block.categories);

  const confidenceColor =
    !block.ai_confidence ? "border-gray-200" :
    block.ai_confidence >= 0.8 ? "border-green-200 bg-green-50" :
    block.ai_confidence >= 0.5 ? "border-yellow-200 bg-yellow-50" :
    "border-red-200 bg-red-50";

  const handleConfirm = async () => {
    // skip sending idle-only to backend
    const cats = sanitizeCategories(parseCats(catsStr));
    const isIdleCats = isIdleOnlyCats(cats) || idleLike;

    // build payload expected by backend label_block
    const payload: any = { block_id: block.id };
    const c = cleanName(client);
    const p = cleanName(project);

    if (c) payload.client = c;
    if (p) payload.project = p;
    if (Object.keys(cats).length > 0) payload.categories = cats;
    if (notes) payload.notes = notes;

    // If it's purely idle, don't POST; just bubble up so UI updates
    if (isIdleCats) {
      onLabeled(
        { client_name: "", project_name: "", category_hours: { "Uncategorized - Idle": (block.minutes || 0) / 60 } },
        block.ai_suggestion || null
      );
      return;
    }

    setBusy(true);
    try {
      await labelBlock(payload); // must hit /api/label-block/
      onLabeled(
        { client_name: c || "", project_name: p || "", category_hours: cats },
        block.ai_suggestion || null
      );
    } finally {
      setBusy(false);
    }
  };

  const handleSave = async () => {
    await handleConfirm();
    setIsEditing(false);
  };

  return (
    <div className={`border rounded-lg p-4 space-y-3 ${confidenceColor}`}>
      {/* Header: Time + Duration */}
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-gray-900">
          {new Date(block.start).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}{" – "}
          {new Date(block.end).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </h3>
        <div className="text-sm font-medium text-gray-600">{block.minutes} min</div>
      </div>

      {/* Activity */}
      <div className="text-base font-medium text-gray-800">{displayTitle}</div>

      {/* Domain/URL */}
      {urlDomain && <div className="text-sm text-gray-600">🌐 {urlDomain}</div>}
      {block.url && (
        <a href={block.url} target="_blank" rel="noopener noreferrer" className="text-xs text-blue-600 hover:underline truncate block">
          {block.url}
        </a>
      )}
      {(block as any).file_path && (
        <div className="text-xs text-gray-500 font-mono">📄 {(block as any).file_path}</div>
      )}

      {/* Idle badge */}
      {idleLike && (
        <div className="inline-flex items-center gap-2 px-2 py-1 rounded-full border border-gray-300 text-xs text-gray-700 bg-gray-50">
          💤 Idle/Away
        </div>
      )}

      {/* Display pills */}
      {!isEditing && (client || project || (block.categories && Object.keys(block.categories).length > 0)) && (
        <div className="flex flex-wrap gap-2 items-center pt-2">
          {client && <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium">👤 {client}</span>}
          {project && <span className="px-3 py-1 bg-purple-100 text-purple-800 rounded-full text-sm font-medium">📁 {project}</span>}
          {block.categories && Object.entries(block.categories).map(([k, v]) => (
            <span key={k} className="px-2 py-1 bg-gray-100 text-gray-800 rounded-full text-xs font-medium">
              {k}: {Number(v).toFixed(2)}h
            </span>
          ))}
          {block.ai_confidence! > 0 && (
            <span className="text-xs text-gray-500">{Math.round((block.ai_confidence || 0) * 100)}% confident</span>
          )}
        </div>
      )}

      {/* Edit Mode */}
      {isEditing && (
        <div className="space-y-3 pt-3 border-t">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Client</label>
              <input
                value={client}
                onChange={(e) => setClient(e.target.value)}
                placeholder="Client name"
                className="w-full border rounded px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Project</label>
              <input
                value={project}
                onChange={(e) => setProject(e.target.value)}
                placeholder="Project name"
                className="w-full border rounded px-3 py-2 text-sm"
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Categories (Name=Hours, comma separated)</label>
            <input
              value={catsStr}
              onChange={(e) => setCatsStr(e.target.value)}
              placeholder='Email=0.5, Meetings=1.25'
              className="w-full border rounded px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Notes</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add notes..."
              className="w-full border rounded px-3 py-2 text-sm"
              rows={2}
            />
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex gap-2 pt-3">
        {!isEditing ? (
          <>
            <button
              onClick={handleConfirm}
              disabled={busy}
              className="flex-1 bg-green-600 hover:bg-green-700 disabled:bg-gray-400 text-white font-medium rounded-lg px-4 py-2 text-sm"
            >
              {busy ? "Saving..." : idleLike ? "✓ Confirm (Idle only)" : "✓ Confirm"}
            </button>
            <button
              onClick={() => setIsEditing(true)}
              className="px-4 py-2 border border-gray-300 hover:bg-gray-50 rounded-lg text-sm font-medium"
            >
              ✏️ Edit
            </button>
          </>
        ) : (
          <>
            <button
              onClick={handleSave}
              disabled={busy}
              className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white font-medium rounded-lg px-4 py-2 text-sm"
            >
              {busy ? "Saving..." : "Save Changes"}
            </button>
            <button
              onClick={() => setIsEditing(false)}
              disabled={busy}
              className="px-4 py-2 border border-gray-300 hover:bg-gray-50 rounded-lg text-sm font-medium"
            >
              Cancel
            </button>
          </>
        )}
      </div>
    </div>
  );
}