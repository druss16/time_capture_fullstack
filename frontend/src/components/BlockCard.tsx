import { useState } from "react";
import { BlockDto } from "../types";
import { labelBlock } from "../api/blocks";

type Props = { 
  block: BlockDto; 
  onLabeled: (updatedData: any, originalSuggestion?: any) => void;
};

export default function BlockCard({ block, onLabeled }: Props) {
  const [isEditing, setIsEditing] = useState(false);
  const [client, setClient] = useState(block.client_name || block.client || "");
  const [project, setProject] = useState(block.project_name || block.project || "");
  const [task, setTask] = useState(block.task || "");
  const [notes, setNotes] = useState(block.notes || "");
  const [busy, setBusy] = useState(false);

  const handleConfirm = async () => {
    setBusy(true);
    try {
      const payload: any = { block_id: block.id };
      if (client) payload.client = client;
      if (project) payload.project = project;
      if (task) payload.task = task;
      if (notes) payload.notes = notes;
      
      await labelBlock(payload);
      onLabeled(payload, block.ai_suggestion || null);
    } finally {
      setBusy(false);
    }
  };

  const handleSave = async () => {
    await handleConfirm();
    setIsEditing(false);
  };

  // Build display
  const getDisplayTitle = () => {
    return block.window_title || block.title || "Unknown Activity";
  };

  const getUrlDomain = () => {
    if (!block.url) return null;
    try {
      return new URL(block.url).hostname;
    } catch {
      return null;
    }
  };

  const urlDomain = getUrlDomain();
  const displayTitle = getDisplayTitle();

  // Confidence color
  const confidenceColor = 
    !block.ai_confidence ? 'border-gray-200' :
    block.ai_confidence >= 0.8 ? 'border-green-200 bg-green-50' : 
    block.ai_confidence >= 0.5 ? 'border-yellow-200 bg-yellow-50' : 
    'border-red-200 bg-red-50';

  return (
    <div className={`border rounded-lg p-4 space-y-3 ${confidenceColor}`}>
      {/* Header: Time + Duration */}
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-gray-900">
          {new Date(block.start).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})} 
          {" – "}
          {new Date(block.end).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}
        </h3>
        <div className="text-sm font-medium text-gray-600">{block.minutes} min</div>
      </div>

      {/* Activity */}
      <div className="text-base font-medium text-gray-800">
        {displayTitle}
      </div>
      
      {/* Domain/URL */}
      {urlDomain && (
        <div className="text-sm text-gray-600">🌐 {urlDomain}</div>
      )}
      
      {block.url && (
        <a 
          href={block.url} 
          target="_blank" 
          rel="noopener noreferrer"
          className="text-xs text-blue-600 hover:underline truncate block"
        >
          {block.url}
        </a>
      )}

      {block.file_path && (
        <div className="text-xs text-gray-500 font-mono">📄 {block.file_path}</div>
      )}

      {/* AI Classification Display - Clean Pills */}
      {!isEditing && (client || project) && (
        <div className="flex flex-wrap gap-2 items-center pt-2">
          {client && (
            <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium">
              👤 {client}
            </span>
          )}
          {project && (
            <span className="px-3 py-1 bg-purple-100 text-purple-800 rounded-full text-sm font-medium">
              📁 {project}
            </span>
          )}
          {block.ai_confidence > 0 && (
            <span className="text-xs text-gray-500">
              {Math.round(block.ai_confidence * 100)}% confident
            </span>
          )}
        </div>
      )}

      {/* No classification */}
      {!isEditing && !client && !project && (
        <div className="text-sm text-gray-500 italic pt-2">
          ⚠️ No classification yet
        </div>
      )}

      {/* Edit Mode - Show Fields */}
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
            <label className="text-xs font-medium text-gray-700 block mb-1">Task</label>
            <input 
              value={task} 
              onChange={(e) => setTask(e.target.value)}
              placeholder="Task type"
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
              {busy ? "Saving..." : "✓ Confirm"}
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