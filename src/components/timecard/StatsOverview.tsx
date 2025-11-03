import { Clock, User, Calendar, TrendingUp } from "lucide-react";
import { StatsCard } from "@/components/common/Card";
import { fmtHours } from "@/lib/utils/formatting";
import { DESIGN_SYSTEM } from "@/lib/design-system";

interface StatsOverviewProps {
  totalHours: number;
  currentUser: string;
  clientCount: number;
}

export const StatsOverview: React.FC<StatsOverviewProps> = ({
  totalHours,
  currentUser,
  clientCount,
}) => {
  return (
    <div className={`mb-6 grid grid-cols-1 md:grid-cols-3 ${DESIGN_SYSTEM.spacing.gap}`}>
      <StatsCard
        gradient
        icon={<Clock className="w-5 h-5" />}
        label="Total Hours Today"
        value={`${fmtHours(totalHours)}h`}
        trend={<TrendingUp className="w-4 h-4" />}
      />

      <StatsCard
        icon={<User className="w-5 h-5 text-accent-foreground" />}
        label="Timecard For"
        value={currentUser}
      />

      <StatsCard
        icon={<Calendar className="w-5 h-5 text-success" />}
        label="Active Clients"
        value={clientCount}
      />
    </div>
  );
};
