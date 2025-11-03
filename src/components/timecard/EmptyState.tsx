import { Clock, RefreshCw } from "lucide-react";
import { Card } from "@/components/common/Card";
import { DESIGN_SYSTEM } from "@/lib/design-system";

export const EmptyState: React.FC = () => {
  return (
    <Card>
      <div className="text-center py-20 border-2 border-dashed border-border bg-muted/20">
        <Clock className="w-16 h-16 text-muted-foreground mx-auto mb-4 opacity-50" />
        <h3 className={`text-xl font-semibold text-foreground mb-2`}>
          No time tracked
        </h3>
        <p className={DESIGN_SYSTEM.typography.small}>
          Select a different date or user to view entries
        </p>
      </div>
    </Card>
  );
};

export const LoadingState: React.FC = () => {
  return (
    <div className="text-center py-20">
      <RefreshCw className="w-12 h-12 text-primary mx-auto mb-4 animate-spin" />
      <p className={DESIGN_SYSTEM.typography.small}>
        Loading timecard data...
      </p>
    </div>
  );
};

interface ErrorBannerProps {
  message: string;
}

export const ErrorBanner: React.FC<ErrorBannerProps> = ({ message }) => {
  return (
    <div
      className={`mb-6 p-4 ${DESIGN_SYSTEM.radius.md} ${DESIGN_SYSTEM.colors.destructive} text-sm`}
    >
      {message}
    </div>
  );
};
