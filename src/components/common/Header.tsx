import { ReactNode } from "react";
import { DESIGN_SYSTEM } from "@/lib/design-system";

export interface HeaderProps {
  title: string;
  subtitle?: string;
  icon?: ReactNode;
  rightContent?: ReactNode;
}

export const Header: React.FC<HeaderProps> = ({
  title,
  subtitle,
  icon,
  rightContent,
}) => {
  return (
    <div className="border-b border-border/50 bg-gradient-to-r from-primary/5 via-card to-primary/5 backdrop-blur-xl sticky top-0 z-50">
      <div className={DESIGN_SYSTEM.spacing.container}>
        <div className="py-5 flex items-center justify-between">
          <div className="flex items-center gap-4">
            {icon && (
              <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-primary to-primary/80 flex items-center justify-center shadow-lg shadow-primary/30">
                {icon}
              </div>
            )}
            <div>
              <h1 className={DESIGN_SYSTEM.typography.title}>{title}</h1>
              {subtitle && (
                <p className={DESIGN_SYSTEM.typography.subtitle}>{subtitle}</p>
              )}
            </div>
          </div>
          {rightContent}
        </div>
      </div>
    </div>
  );
};
