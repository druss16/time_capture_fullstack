export type Suggestion = {
  label_type: "client" | "project" | "task";
  value_text: string;
  confidence: number;
};

export type BlockDto = {
  id: number;
  start: string;  // ISO
  end: string;    // ISO
  minutes: number;
  title: string | null;
  url: string | null;
  file_path: string | null;
  client: string | null;
  project: string | null;
  task: string | null;
  notes?: string;
  suggestions?: Suggestion[];
};
