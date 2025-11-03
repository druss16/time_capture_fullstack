// src/types/index.ts
export interface BlockDto {
  id: number;
  app_name: string;
  window_title: string;
  time_block_start: string;
  time_block_end: string;
  duration_minutes: number;
  user_id?: string;
  created_at?: string;
}

export interface AISuggestion {
  block_id: number;
  ai_suggestion?: {
    client?: string | null;
    project?: string | null;
    categories?: Record<string, number>;
    confidence?: number;
    needs_review?: boolean;
    reasoning?: string;
  };
}

export interface LabeledBlock extends BlockDto {
  client_name?: string | null;
  project_name?: string | null;
  categories?: Record<string, number>;
  ai_confidence?: number;
  needs_review?: boolean;
  ai_reasoning?: string;
}

export interface ClassificationPayload {
  client?: string | null;
  project?: string | null;
  categories?: Record<string, number>;
}
