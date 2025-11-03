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
      className={`p-5 ${DESIGN_SYSTEM.radius.lg} overflow-hidden transition-all duration-300 ${
        gradient
          ? "bg-gradient-to-br from-primary via-primary to-primary/90 text-primary-foreground shadow-lg shadow-primary/30 hover:shadow-xl hover:shadow-primary/40"
          : "bg-gradient-to-br from-card to-card/80 border border-border hover:border-primary/30 shadow-md hover:shadow-lg hover:scale-105"
      }`}
    >
      <div className="flex items-center justify-between mb-3">
        {icon && (
          <div
            className={`w-10 h-10 ${DESIGN_SYSTEM.radius.md} flex items-center justify-center ${
              gradient
                ? "bg-white/20 backdrop-blur text-primary-foreground"
                : "bg-primary/10 text-primary"
            }`}
          >
            {icon}
          </div>
        )}
        {trend && (
          <div className={`${gradient ? "text-primary-foreground/80" : "text-primary"}`}>
            {trend}
          </div>
        )}
      </div>
      <div className="mb-1">
        <div className="text-2xl font-bold tracking-tight">{value}</div>
      </div>
      <div
        className={`text-xs font-medium ${
          gradient ? "text-primary-foreground/80" : "text-muted-foreground"
        }`}
      >
        {label}
      </div>
    </div>
  );
};
