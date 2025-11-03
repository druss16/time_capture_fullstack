// src/components/StatsCard.tsx
import { Card } from "./ui/card";
import { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatsCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: LucideIcon;
  variant?: "default" | "success" | "warning";
}

export default function StatsCard({ 
  title, 
  value, 
  subtitle, 
  icon: Icon, 
  variant = "default" 
}: StatsCardProps) {
  return (
    <Card className={cn(
      "p-4 transition-all duration-200 hover:shadow-elevated",
      variant === "success" && "border-success/30 bg-success-light/30",
      variant === "warning" && "border-warning/30 bg-warning-light/30"
    )}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <p className="text-sm font-medium text-muted-foreground mb-1">
            {title}
          </p>
          <p className="text-2xl font-bold text-foreground mb-1">
            {value}
          </p>
          {subtitle && (
            <p className="text-xs text-muted-foreground">
              {subtitle}
            </p>
          )}
        </div>
        <div className={cn(
          "w-12 h-12 rounded-lg flex items-center justify-center",
          variant === "default" && "bg-primary/10",
          variant === "success" && "bg-success/10",
          variant === "warning" && "bg-warning/10"
        )}>
          <Icon className={cn(
            "w-6 h-6",
            variant === "default" && "text-primary",
            variant === "success" && "text-success",
            variant === "warning" && "text-warning"
          )} />
        </div>
      </div>
    </Card>
  );
}
