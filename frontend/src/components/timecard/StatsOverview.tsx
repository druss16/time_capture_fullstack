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
    <div className={`mb-8 grid grid-cols-1 md:grid-cols-3 gap-6`}>
      <StatsCard
        gradient
        icon={<Clock className="w-6 h-6" />}
        label="Total Hours Today"
        value={`${fmtHours(totalHours)}h`}
        trend={<TrendingUp className="w-5 h-5" />}
      />

      <StatsCard
        icon={<User className="w-6 h-6" />}
        label="Timecard For"
        value={currentUser}
      />

      <StatsCard
        icon={<Calendar className="w-6 h-6" />}
        label="Active Clients"
        value={clientCount}
      />
    </div>
  );
};
