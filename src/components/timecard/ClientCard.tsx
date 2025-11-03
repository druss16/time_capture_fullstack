import { ChevronRight } from "lucide-react";
import { Card } from "@/components/common/Card";
import { fmtHours, pluralize } from "@/lib/utils/formatting";
import { DESIGN_SYSTEM } from "@/lib/design-system";

interface TaskRow {
  task_name: string;
  total_hours: number;
  categories: Record<string, number>;
  block_ids?: number[];
}

interface ClientRow {
  client_name: string;
  total_hours: number;
  categories: Record<string, number>;
  block_ids?: number[];
  tasks?: TaskRow[];
}

interface ClientCardProps {
  client: ClientRow;
  totalHours: number;
  isExpanded: boolean;
  onToggle: () => void;
}

export const ClientCard: React.FC<ClientCardProps> = ({
  client,
  totalHours,
  isExpanded,
  onToggle,
}) => {
  const hasDetails =
    (client.tasks?.length || 0) > 0 ||
    Object.keys(client.categories || {}).length > 0;

  const progressPercent = Math.min(
    100,
    (client.total_hours / (totalHours || 1)) * 100
  );

  return (
    <Card interactive>
      <div
        className={`p-6 cursor-pointer ${hasDetails ? "" : "cursor-default"}`}
        onClick={() => hasDetails && onToggle()}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4 flex-1">
            {hasDetails && (
              <ChevronRight
                className={`w-5 h-5 text-muted-foreground transition-transform ${
                  isExpanded ? "rotate-90" : ""
                }`}
              />
            )}
            <div className="flex-1">
              <h3 className={DESIGN_SYSTEM.typography.heading3}>
                {client.client_name}
              </h3>
              {client.tasks && client.tasks.length > 0 && (
                <p className={DESIGN_SYSTEM.typography.small}>
                  {client.tasks.length} {pluralize(client.tasks.length, "task")}
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="hidden md:block w-32">
              <div className="h-2 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary rounded-full transition-all"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
            </div>

            <div className="text-right">
              <div className="text-3xl font-bold text-foreground">
                {fmtHours(client.total_hours)}
              </div>
              <div className={DESIGN_SYSTEM.typography.small}>hours</div>
            </div>
          </div>
        </div>
      </div>

      {isExpanded && (
        <div className={`border-t border-border ${DESIGN_SYSTEM.colors.muted}`}>
          {Object.entries(client.categories || {}).filter(
            ([k]) =>
              !(k === "Uncategorized" && (client.tasks?.length || 0) > 0)
          ).length > 0 && (
            <div className={`p-6 border-b border-border`}>
              <h4 className={DESIGN_SYSTEM.typography.label + " mb-3"}>
                Categories
              </h4>
              <div className={`flex flex-wrap ${DESIGN_SYSTEM.spacing.gap}`}>
                {Object.entries(client.categories || {})
                  .filter(
                    ([k]) =>
                      !(k === "Uncategorized" && (client.tasks?.length || 0) > 0)
                  )
                  .map(([cat, hrs]) => (
                    <div
                      key={cat}
                      className={`px-4 py-2 ${DESIGN_SYSTEM.radius.md} bg-primary/10 border border-primary/20 flex items-center gap-2`}
                    >
                      <span className={DESIGN_SYSTEM.typography.body}>
                        {cat}
                      </span>
                      <span className="text-sm font-bold text-primary">
                        {fmtHours(hrs as number)}h
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {client.tasks && client.tasks.length > 0 && (
            <div className="p-6">
              <h4 className={DESIGN_SYSTEM.typography.label + " mb-3"}>
                Task Breakdown
              </h4>
              <div className="space-y-2">
                {client.tasks.map((task) => (
                  <div
                    key={`${client.client_name}-${task.task_name}`}
                    className={`flex items-center justify-between p-3 ${DESIGN_SYSTEM.radius.md} bg-card ${DESIGN_SYSTEM.colors.hover}`}
                  >
                    <span className={DESIGN_SYSTEM.typography.body}>
                      {task.task_name}
                    </span>
                    <span className="text-sm font-bold text-primary">
                      {fmtHours(Number(task.total_hours || 0))}h
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
};
