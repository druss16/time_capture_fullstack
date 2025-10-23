import { useState } from "react";
import { BlockDto } from "../types";
import SuggestionChips from "./SuggestionChips";
import { labelBlock } from "../api/blocks";

type Props = { block: BlockDto; onLabeled: () => void };

export default function BlockCard({ block, onLabeled }: Props) {
  const [client, setClient] = useState(block.client ?? "");
  const [project, setProject] = useState(block.project ?? "");
  const [task, setTask] = useState(block.task ?? "");
  const [notes, setNotes] = useState(block.notes ?? "");
  const [createRule, setCreateRule] = useState(false);
  const [ruleField, setRuleField] = useState<"client" | "project" | "task">("client");
  const [ruleValue, setRuleValue] = useState("");
  const [busy, setBusy] = useState(false);

  const apply = async () => {
    setBusy(true);
    try {
      const payload: any = { block_id: block.id };

      if (client) payload.client = client;
      if (project) payload.project = project;
      if (task) payload.task = task;
      if (notes) payload.notes = notes;

      if (createRule) {
        payload.create_rule = true;
        payload.create_rule_field = ruleField;
        payload.create_rule_value = ruleValue;
      }

      await labelBlock(payload);
      onLabeled();
    } finally {
      setBusy(false);
    }
  };


  const meta = [
    block.title || "",
    block.url || "",
    block.file_path || "",
  ].filter(Boolean).join(" • ");

  return (
    <div className="border rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">{new Date(block.start).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})} – {new Date(block.end).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}</h3>
        <div className="text-sm opacity-70">{block.minutes} min</div>
      </div>

      {meta && <div className="text-sm opacity-80">{meta}</div>}

      <SuggestionChips suggestions={block.suggestions ?? []} />

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="text-xs opacity-70">Client</label>
          <input value={client} onChange={(e)=>setClient(e.target.value)} className="w-full border rounded px-2 py-1" />
        </div>
        <div>
          <label className="text-xs opacity-70">Project</label>
          <input value={project} onChange={(e)=>setProject(e.target.value)} className="w-full border rounded px-2 py-1" />
        </div>
        <div>
          <label className="text-xs opacity-70">Task</label>
          <input value={task} onChange={(e)=>setTask(e.target.value)} className="w-full border rounded px-2 py-1" />
        </div>
      </div>

      <div>
        <label className="text-xs opacity-70">Notes</label>
        <textarea value={notes} onChange={(e)=>setNotes(e.target.value)} className="w-full border rounded px-2 py-1" rows={2} />
      </div>

      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={createRule} onChange={(e)=>setCreateRule(e.target.checked)} />
          Create rule from this
        </label>
        {createRule && (
          <div className="flex items-center gap-2">
            <select value={ruleField} onChange={(e)=>setRuleField(e.target.value as any)} className="border rounded px-2 py-1 text-sm">
              <option value="client">client</option>
              <option value="project">project</option>
              <option value="task">task</option>
            </select>
            <input placeholder="Rule value…" value={ruleValue} onChange={(e)=>setRuleValue(e.target.value)} className="border rounded px-2 py-1 text-sm" />
          </div>
        )}
      </div>

      <div className="flex justify-end">
        <button onClick={apply} disabled={busy} className="border rounded-lg px-3 py-2">
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}
