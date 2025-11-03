// src/components/BlockCard.tsx
import { useState } from "react";
import { Clock, Save, AlertCircle, CheckCircle2, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Card } from "./ui/card";
import { Badge } from "./ui/badge";
import { LabeledBlock } from "../types";
import { cn } from "@/lib/utils";

interface BlockCardProps {
  block: LabeledBlock;
  onSave: (id: number, data: {
    client?: string | null;
    project?: string | null;
    categories?: Record<string, number>;
  }) => Promise<void>;
}

export default function BlockCard({ block, onSave }: BlockCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [client, setClient] = useState(block.client_name || "");
  const [project, setProject] = useState(block.project_name || "");
  const [categories, setCategories] = useState<Record<string, number>>(
    block.categories || {}
  );
  const [isSaving, setIsSaving] = useState(false);
  const [newCatName, setNewCatName] = useState("");
  const [newCatHours, setNewCatHours] = useState("");

  const totalHours = Object.values(categories).reduce((sum, h) => sum + h, 0);
  const blockHours = (block.duration_minutes / 60).toFixed(2);
  const hasChanges = 
    client !== (block.client_name || "") ||
    project !== (block.project_name || "") ||
    JSON.stringify(categories) !== JSON.stringify(block.categories || {});

  const confidence = block.ai_confidence ?? 0;
  const needsReview = block.needs_review || confidence < 0.7;

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await onSave(block.id, {
        client: client.trim() || null,
        project: project.trim() || null,
        categories,
      });
    } finally {
      setIsSaving(false);
    }
  };

  const addCategory = () => {
    if (newCatName.trim() && newCatHours.trim()) {
      const hours = parseFloat(newCatHours);
      if (Number.isFinite(hours) && hours >= 0) {
        setCategories({ ...categories, [newCatName.trim()]: hours });
        setNewCatName("");
        setNewCatHours("");
      }
    }
  };

  const removeCategory = (catName: string) => {
    const updated = { ...categories };
    delete updated[catName];
    setCategories(updated);
  };

  return (
    <Card className={cn(
      "p-4 transition-all duration-200 hover:shadow-elevated border-2",
      needsReview ? "border-warning/30 bg-warning-light/50" : "border-border hover:border-primary/30"
    )}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <h3 className="font-semibold text-foreground truncate">
              {block.app_name}
            </h3>
            {needsReview ? (
              <Badge variant="outline" className="bg-warning/10 text-warning border-warning/30">
                <AlertCircle className="w-3 h-3 mr-1" />
                Review
              </Badge>
            ) : block.client_name ? (
              <Badge variant="outline" className="bg-success/10 text-success border-success/30">
                <CheckCircle2 className="w-3 h-3 mr-1" />
                Classified
              </Badge>
            ) : null}
          </div>
          
          <p className="text-sm text-muted-foreground mb-2 truncate">
            {block.window_title}
          </p>
          
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {new Date(block.time_block_start).toLocaleTimeString([], { 
                hour: "2-digit", 
                minute: "2-digit" 
              })} - {new Date(block.time_block_end).toLocaleTimeString([], { 
                hour: "2-digit", 
                minute: "2-digit" 
              })}
            </span>
            <span className="font-medium text-primary">
              {blockHours}h
            </span>
          </div>
        </div>

        <Button
          variant="ghost"
          size="sm"
          onClick={() => setIsExpanded(!isExpanded)}
          className="shrink-0"
        >
          {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </Button>
      </div>

      {isExpanded && (
        <div className="mt-4 pt-4 border-t space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">
                Client
              </label>
              <Input
                value={client}
                onChange={(e) => setClient(e.target.value)}
                placeholder="Enter client name"
                className="h-9"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">
                Project
              </label>
              <Input
                value={project}
                onChange={(e) => setProject(e.target.value)}
                placeholder="Enter project name"
                className="h-9"
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-muted-foreground mb-2 block">
              Categories (Total: {totalHours.toFixed(2)}h / Block: {blockHours}h)
            </label>
            
            {Object.entries(categories).length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {Object.entries(categories).map(([name, hours]) => (
                  <Badge
                    key={name}
                    variant="secondary"
                    className="gap-1 pr-1"
                  >
                    {name}: {hours}h
                    <button
                      onClick={() => removeCategory(name)}
                      className="ml-1 hover:bg-destructive/20 rounded px-1"
                    >
                      ×
                    </button>
                  </Badge>
                ))}
              </div>
            )}

            <div className="flex gap-2">
              <Input
                value={newCatName}
                onChange={(e) => setNewCatName(e.target.value)}
                placeholder="Category name"
                className="h-9 flex-1"
              />
              <Input
                value={newCatHours}
                onChange={(e) => setNewCatHours(e.target.value)}
                placeholder="Hours"
                type="number"
                step="0.25"
                min="0"
                className="h-9 w-24"
              />
              <Button onClick={addCategory} size="sm" variant="outline">
                Add
              </Button>
            </div>
          </div>

          {block.ai_reasoning && (
            <div className="text-xs text-muted-foreground bg-accent/50 p-3 rounded-md">
              <span className="font-medium">AI Reasoning:</span> {block.ai_reasoning}
            </div>
          )}

          <Button
            onClick={handleSave}
            disabled={!hasChanges || isSaving}
            className="w-full"
            size="sm"
          >
            <Save className="w-4 h-4 mr-2" />
            {isSaving ? "Saving..." : "Save Classification"}
          </Button>
        </div>
      )}
    </Card>
  );
}
