import { Suggestion } from "../types";

export default function SuggestionChips({ suggestions }: { suggestions: Suggestion[] }) {
  if (!suggestions?.length) return null;
  return (
    <div className="flex flex-wrap gap-2 mt-2">
      {suggestions.map((s, i) => (
        <span key={i} className="inline-flex items-center gap-2 border rounded-full px-3 py-1 text-sm">
          <strong className="uppercase">{s.label_type}</strong>
          <span>{s.value_text}</span>
          <em className="opacity-60">({Math.round(s.confidence * 100)}%)</em>
        </span>
      ))}
    </div>
  );
}
