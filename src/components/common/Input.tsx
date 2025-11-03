import { ReactNode } from "react";
import { DESIGN_SYSTEM } from "@/lib/design-system";

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  icon?: ReactNode;
  label?: string;
  error?: string;
}

export const Input: React.FC<InputProps> = ({
  icon,
  label,
  error,
  className,
  ...props
}) => {
  return (
    <div>
      {label && (
        <label className={`block ${DESIGN_SYSTEM.typography.small} mb-2`}>
          {label}
        </label>
      )}
      <div
        className={`flex items-center gap-2 px-4 py-2.5 ${DESIGN_SYSTEM.radius.md} 
        border border-border bg-card ${DESIGN_SYSTEM.shadows.hover}`}
      >
        {icon && <span className="text-muted-foreground">{icon}</span>}
        <input
          className="flex-1 bg-transparent border-none outline-none text-sm font-medium text-foreground placeholder:text-muted-foreground"
          {...props}
        />
      </div>
      {error && <p className="text-xs text-destructive mt-1">{error}</p>}
    </div>
  );
};
