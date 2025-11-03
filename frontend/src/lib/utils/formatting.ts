export const fmtHours = (n: number): string => {
  return (Math.round((n || 0) * 100) / 100).toFixed(2);
};

export const displayClientName = (name?: string): string => {
  const n = (name || "").trim();
  if (!n || n.toLowerCase() === "unknown") return "Unassigned";
  return n;
};

export const pluralize = (count: number, singular: string, plural?: string): string => {
  return count === 1 ? singular : plural || `${singular}s`;
};
