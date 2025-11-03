import { ReactNode } from "react";
import { DESIGN_SYSTEM } from "@/lib/design-system";

interface CardProps {
  children: ReactNode;
  className?: string;
  interactive?: boolean;
}

export const Card: React.FC<CardProps> = ({
  children,
  className,
  interactive = false,
}) => {
  return (
    <div
      className={`${DESIGN_SYSTEM.radius.lg} ${DESIGN_SYSTEM.colors.card} ${
        interactive ? DESIGN_SYSTEM.shadows.hover : ""
      } overflow-hidden ${className || ""}`}
    >
      {children}
    </div>
  );
};

interface StatsCardProps {
  icon?: ReactNode;
  label: string;
  value: string | number;
  trend?: ReactNode;
  gradient?: boolean;
}

export const StatsCard: React.FC<StatsCardProps> = ({
  icon,
  label,
  value,
  trend,
  gradient = false,
}) => {
  return (
    <div
      className={`p-4 ${DESIGN_SYSTEM.radius.md} ${
        gradient
          ? DESIGN_SYSTEM.colors.primary + " text-primary-foreground"
          : DESIGN_SYSTEM.colors.card + " " + DESIGN_SYSTEM.shadows.hover
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        {icon && (
          <div
            className={`w-9 h-9 ${DESIGN_SYSTEM.radius.md} flex items-center justify-center ${
              gradient ? "bg-white/20 backdrop-blur" : "bg-accent"
            }`}
          >
            {icon}
          </div>
        )}
        {trend && <div className="opacity-70">{trend}</div>}
      </div>
      <div className="text-3xl font-bold mb-0.5">
        {value}
        <span className="text-lg">{gradient ? "" : ""}</span>
      </div>
      <div className={`text-xs ${gradient ? "opacity-90" : "text-muted-foreground"}`}>
        {label}
      </div>
    </div>
  );
};
