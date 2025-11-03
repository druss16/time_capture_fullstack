import { Calendar, User, RefreshCw, Download, Save } from "lucide-react";
import { Button } from "@/components/common/Button";
import { Input } from "@/components/common/Input";
import { DESIGN_SYSTEM } from "@/lib/design-system";

interface FilterBarProps {
  date: string;
  user: string;
  whoami: string;
  onDateChange: (date: string) => void;
  onUserChange: (user: string) => void;
  onRefresh: () => void;
  onDraft: () => void;
  onSubmit: () => void;
  isLoading: boolean;
}

export const FilterBar: React.FC<FilterBarProps> = ({
  date,
  user,
  whoami,
  onDateChange,
  onUserChange,
  onRefresh,
  onDraft,
  onSubmit,
  isLoading,
}) => {
  return (
    <div className={`mb-8 flex items-center ${DESIGN_SYSTEM.spacing.gap} flex-wrap`}>
      <Input
        type="date"
        value={date}
        onChange={(e) => onDateChange(e.target.value)}
        icon={<Calendar className="w-4 h-4" />}
        disabled={isLoading}
      />

      <Input
        type="text"
        placeholder="All users"
        value={user}
        onChange={(e) => onUserChange(e.target.value)}
        icon={<User className="w-4 h-4" />}
        list="user-hints"
        disabled={isLoading}
      />
      <datalist id="user-hints">
        {whoami ? <option value={whoami} /> : null}
      </datalist>

      <div className="flex-1" />

      <Button
        variant="secondary"
        onClick={onRefresh}
        disabled={isLoading}
        icon={<RefreshCw className="w-4 h-4" />}
      >
        Refresh
      </Button>

      <Button
        variant="secondary"
        onClick={onDraft}
        disabled={isLoading}
        icon={<Download className="w-4 h-4" />}
      >
        Draft
      </Button>

      <Button
        variant="primary"
        onClick={onSubmit}
        disabled={isLoading}
        icon={<Save className="w-4 h-4" />}
      >
        Submit
      </Button>
    </div>
  );
};
