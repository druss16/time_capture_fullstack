/**
 * SectionHeader — simple title bar for grouping primitives.
 */
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/design-system";

interface Props {
  title: string;
  collapsible?: boolean;
  collapsed?: boolean;
  onToggle?: () => void;
  children?: React.ReactNode;
}

export default function SectionHeader({ title, collapsible, collapsed, onToggle, children }: Props) {
  return (
    <div className="flex items-center justify-between mb-3">
      <button
        onClick={collapsible ? onToggle : undefined}
        disabled={!collapsible}
        className={cn(
          "flex items-center gap-1.5 text-xs uppercase tracking-wider text-slate-500 font-semibold",
          collapsible && "hover:text-slate-800 cursor-pointer",
        )}
      >
        <span>{title}</span>
        {collapsible && (
          <ChevronDown className={cn(
            "h-3.5 w-3.5 transition-transform",
            collapsed && "-rotate-90",
          )} />
        )}
      </button>
      {children && <div>{children}</div>}
    </div>
  );
}
