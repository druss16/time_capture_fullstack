import { ReactNode } from "react";
import { DESIGN_SYSTEM } from "@/lib/design-system";

interface HeaderProps {
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
    <div className="border-b border-border bg-card/50 backdrop-blur-xl sticky top-0 z-50">
      <div className={DESIGN_SYSTEM.spacing.container}>
        <div className="py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {icon && (
              <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center">
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
