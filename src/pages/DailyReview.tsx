// src/pages/DailyReview.tsx
import { useEffect, useMemo, useState } from "react";
import { Download, Clock, CheckCircle, AlertTriangle, TrendingUp } from "lucide-react";
import { BlockDto, LabeledBlock, AISuggestion } from "../types";
import { downloadTodayCsv, fetchBlocksToday, classifyBlock } from "../api/blocks";
import BlockCard from "../components/BlockCard";
import Navigation from "../components/Navigation";
import StatsCard from "../components/StatsCard";
import { Button } from "../components/ui/button";
import { useToast } from "@/hooks/use-toast";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

function titleCase(s?: string | null) {
  if (!s) return s ?? null;
  return s.trim().toLowerCase().replace(/\b\w/g, (m) => m.toUpperCase());
}

function cleanName(v?: string | null) {
  if (!v) return null;
  const t = String(v).trim();
  if (!t) return null;
  const BAD = new Set(["none", "unassigned", "—", "-", "(none)"]);
  if (BAD.has(t.toLowerCase())) return null;
  return t.slice(0, 120);
}

function cleanCategories(obj: Record<string, any> | undefined | null) {
  const out: Record<string, number> = {};
  if (!obj) return out;
  for (const [k, v] of Object.entries(obj)) {
    const s = String(v).toLowerCase().replace(/hrs?|h/g, "").trim();
    const f = Number(s);
    if (Number.isFinite(f) && f >= 0) out[String(k).trim()] = f;
  }
  return out;
}

async function fetchAISuggestions(blockIds: number[]): Promise<AISuggestion[]> {
  if (blockIds.length === 0) return [];
  
  try {
    const response = await fetch(`${API_BASE}/classify/suggest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ block_ids: blockIds }),
    });
    
    if (!response.ok) {
      console.warn("AI suggestions unavailable, using fallback");
      return [];
    }
    
    return await response.json();
  } catch (error) {
    console.warn("AI suggestions failed:", error);
    return [];
  }
}

function mergeAISuggestions(blocks: BlockDto[], suggestions: AISuggestion[]): LabeledBlock[] {
  const suggestionMap = new Map(
    suggestions.map((s) => [s.block_id, s.ai_suggestion])
  );

  return blocks.map((block) => {
    const suggestion = suggestionMap.get(block.id);
    
    return {
      ...block,
      client_name: suggestion?.client ? titleCase(suggestion.client) : null,
      project_name: suggestion?.project ? titleCase(suggestion.project) : null,
      categories: suggestion?.categories || {},
      ai_confidence: suggestion?.confidence,
      needs_review: suggestion?.needs_review ?? true,
      ai_reasoning: suggestion?.reasoning,
    };
  });
}

export default function DailyReview() {
  const [blocks, setBlocks] = useState<LabeledBlock[]>([]);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    try {
      const rawBlocks = await fetchBlocksToday();
      const uncategorized = rawBlocks.filter(
        (b) => !(b as any).client_name && !(b as any).project_name
      );
      
      let suggestions: AISuggestion[] = [];
      if (uncategorized.length > 0) {
        suggestions = await fetchAISuggestions(uncategorized.map((b) => b.id));
      }
      
      const labeled = mergeAISuggestions(rawBlocks, suggestions);
      setBlocks(labeled);
    } catch (error) {
      console.error("Error loading data:", error);
      toast({
        title: "Error",
        description: "Failed to load time blocks",
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  }

  async function handleSave(
    id: number,
    data: {
      client?: string | null;
      project?: string | null;
      categories?: Record<string, number>;
    }
  ) {
    try {
      const client = cleanName(data.client);
      const project = cleanName(data.project);
      const categories = cleanCategories(data.categories);

      await classifyBlock(id, { client, project, categories });

      setBlocks((prev) =>
        prev.map((b) =>
          b.id === id
            ? {
                ...b,
                client_name: client ? titleCase(client) : null,
                project_name: project ? titleCase(project) : null,
                categories,
                needs_review: false,
              }
            : b
        )
      );

      toast({
        title: "Success",
        description: "Classification saved successfully",
      });
    } catch (error) {
      console.error("Error saving:", error);
      toast({
        title: "Error",
        description: "Failed to save classification",
        variant: "destructive",
      });
    }
  }

  async function handleExport() {
    setExporting(true);
    try {
      await downloadTodayCsv();
      toast({
        title: "Success",
        description: "CSV exported successfully",
      });
    } catch (error) {
      toast({
        title: "Error",
        description: "Failed to export CSV",
        variant: "destructive",
      });
    } finally {
      setExporting(false);
    }
  }

  const stats = useMemo(() => {
    const totalHours = blocks.reduce((sum, b) => sum + b.duration_minutes / 60, 0);
    const classified = blocks.filter((b) => b.client_name || b.project_name).length;
    const needsReview = blocks.filter((b) => b.needs_review).length;
    
    return {
      totalHours: totalHours.toFixed(1),
      totalBlocks: blocks.length,
      classified,
      needsReview,
      classifiedPercent: blocks.length ? Math.round((classified / blocks.length) * 100) : 0,
    };
  }, [blocks]);

  return (
    <div className="min-h-screen bg-gradient-subtle">
      <Navigation />
      
      <main className="container mx-auto px-4 py-8">
        <div className="mb-8">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-3xl font-bold text-foreground mb-2">
                Daily Review
              </h2>
              <p className="text-muted-foreground">
                {new Date().toLocaleDateString("en-US", {
                  weekday: "long",
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                })}
              </p>
            </div>
            
            <Button
              onClick={handleExport}
              disabled={exporting || blocks.length === 0}
              size="lg"
              variant="outline"
            >
              <Download className="w-4 h-4 mr-2" />
              {exporting ? "Exporting..." : "Export CSV"}
            </Button>
          </div>

          {/* Stats Grid */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
            <StatsCard
              title="Total Time"
              value={`${stats.totalHours}h`}
              subtitle={`${stats.totalBlocks} time blocks`}
              icon={Clock}
              variant="default"
            />
            <StatsCard
              title="Classified"
              value={`${stats.classifiedPercent}%`}
              subtitle={`${stats.classified} of ${stats.totalBlocks} blocks`}
              icon={CheckCircle}
              variant="success"
            />
            <StatsCard
              title="Needs Review"
              value={stats.needsReview}
              subtitle="Blocks requiring attention"
              icon={AlertTriangle}
              variant={stats.needsReview > 0 ? "warning" : "success"}
            />
            <StatsCard
              title="Progress"
              value={`${stats.classified}/${stats.totalBlocks}`}
              subtitle="Blocks completed"
              icon={TrendingUp}
              variant="default"
            />
          </div>
        </div>

        {/* Blocks List */}
        {loading ? (
          <div className="text-center py-12">
            <div className="animate-spin w-8 h-8 border-4 border-primary border-t-transparent rounded-full mx-auto mb-4" />
            <p className="text-muted-foreground">Loading time blocks...</p>
          </div>
        ) : blocks.length === 0 ? (
          <div className="text-center py-12 bg-card rounded-xl shadow-card border">
            <Clock className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <h3 className="text-xl font-semibold mb-2">No time blocks yet</h3>
            <p className="text-muted-foreground">
              Start tracking your time to see blocks appear here
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {blocks.map((block) => (
              <BlockCard key={block.id} block={block} onSave={handleSave} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
