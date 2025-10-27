// types.ts - Update your BlockDto type

export interface BlockDto {
  id: number;
  start: string;
  end: string;
  minutes: number;
  title: string;
  window_title?: string;  // ADD THIS LINE
  url?: string;
  file_path?: string;
  client?: string;
  project?: string;
  task?: string;
  notes?: string;
  suggestions?: Suggestion[];
}

export interface Suggestion {
  label_type: string;
  value_text: string;
  confidence: number;
}