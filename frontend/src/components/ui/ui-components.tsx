/**
 * ui-components.tsx - Reusable UI components
 * Uses shadcn/ui CSS variable naming convention
 * 
 * Put this in: src/components/ui/ui-components.tsx
 * Or: src/components/ui-components.tsx
 */
import React from 'react';
import { 
  cn, 
  STATUS_COLORS, 
  ROLE_COLORS, 
  SKELETON, 
  DESIGN_SYSTEM,
  BUTTON_VARIANTS,
  type StatusType,
  type RoleType,
  type ButtonVariant
} from '@/lib/design-system';
import { 
  FileQuestion, 
  AlertTriangle, 
  CheckCircle2, 
  XCircle, 
  Clock,
  Loader2,
  Info
} from 'lucide-react';

// =============================================================================
// STATUS BADGE
// =============================================================================

interface StatusBadgeProps {
  status: StatusType;
  showDot?: boolean;
  size?: 'sm' | 'md';
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ 
  status, 
  showDot = true, 
  size = 'md',
  className 
}) => {
  const colors = STATUS_COLORS[status] || STATUS_COLORS.draft;
  const label = status.charAt(0).toUpperCase() + status.slice(1);
  
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 rounded-full font-semibold',
      colors.bg, colors.text,
      size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs',
      className
    )}>
      {showDot && <span className={cn('w-1.5 h-1.5 rounded-full', colors.dot)} />}
      {label}
    </span>
  );
};

// =============================================================================
// ROLE BADGE
// =============================================================================

interface RoleBadgeProps {
  role: RoleType;
  className?: string;
}

export const RoleBadge: React.FC<RoleBadgeProps> = ({ role, className }) => {
  if (role === 'member') return null;
  
  const colors = ROLE_COLORS[role] || ROLE_COLORS.member;
  const label = role.charAt(0).toUpperCase() + role.slice(1);
  
  return (
    <span className={cn('text-xs px-2 py-0.5 rounded font-semibold', colors, className)}>
      {label}
    </span>
  );
};

// =============================================================================
// EMPTY STATE
// =============================================================================

interface EmptyStateProps {
  icon?: React.ElementType;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
    icon?: React.ElementType;
  };
  className?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon: Icon = FileQuestion,
  title,
  description,
  action,
  className
}) => (
  <div className={cn(
    'text-center py-16 bg-card rounded-2xl border-2 border-border/50',
    className
  )}>
    <div className="w-16 h-16 rounded-2xl bg-muted flex items-center justify-center mx-auto mb-4">
      <Icon className="w-8 h-8 text-muted-foreground" />
    </div>
    <h3 className="text-lg font-bold text-foreground tracking-tight mb-1">{title}</h3>
    {description && <p className="text-muted-foreground mb-6 max-w-sm mx-auto">{description}</p>}
    {action && (
      <button
        onClick={action.onClick}
        className={cn(DESIGN_SYSTEM.components.buttonBase, BUTTON_VARIANTS.primary)}
      >
        {action.icon && <action.icon className="w-4 h-4" />}
        {action.label}
      </button>
    )}
  </div>
);

// =============================================================================
// ALERT BANNER
// =============================================================================

type AlertType = 'info' | 'warning' | 'error' | 'success';

interface AlertBannerProps {
  type: AlertType;
  message: string;
  action?: {
    label: string;
    onClick: () => void;
  };
  onDismiss?: () => void;
  className?: string;
}

const alertStyles: Record<AlertType, { bg: string; border: string; text: string; icon: React.ElementType; button: string }> = {
  info: { 
    bg: 'bg-primary/10', 
    border: 'border-primary/30', 
    text: 'text-primary', 
    icon: Info,
    button: 'bg-primary hover:bg-primary/90 shadow-primary/25'
  },
  warning: { 
    bg: 'bg-warning/10', 
    border: 'border-warning/30', 
    text: 'text-warning', 
    icon: AlertTriangle,
    button: 'bg-warning hover:bg-warning/90 shadow-warning/25'
  },
  error: { 
    bg: 'bg-destructive/10', 
    border: 'border-destructive/30', 
    text: 'text-destructive', 
    icon: XCircle,
    button: 'bg-destructive hover:bg-destructive/90 shadow-destructive/25'
  },
  success: { 
    bg: 'bg-success/10', 
    border: 'border-success/30', 
    text: 'text-success', 
    icon: CheckCircle2,
    button: 'bg-success hover:bg-success/90 shadow-success/25'
  },
};

export const AlertBanner: React.FC<AlertBannerProps> = ({
  type,
  message,
  action,
  onDismiss,
  className
}) => {
  const styles = alertStyles[type];
  const Icon = styles.icon;
  
  return (
    <div className={cn(
      'px-4 py-3 rounded-2xl border-2 flex items-center justify-between gap-4',
      styles.bg, styles.border,
      className
    )}>
      <div className={cn('flex items-center gap-2 font-semibold', styles.text)}>
        <Icon className="w-5 h-5" />
        <span>{message}</span>
      </div>
      <div className="flex items-center gap-2">
        {action && (
          <button
            onClick={action.onClick}
            className={cn(
              'px-4 py-2 text-white font-semibold rounded-xl shadow-lg transition-all',
              styles.button
            )}
          >
            {action.label}
          </button>
        )}
        {onDismiss && (
          <button onClick={onDismiss} className="p-1 hover:bg-black/5 rounded-lg transition-colors">
            <XCircle className="w-5 h-5 opacity-50" />
          </button>
        )}
      </div>
    </div>
  );
};

// =============================================================================
// SKELETON COMPONENTS
// =============================================================================

interface SkeletonProps {
  className?: string;
}

export const SkeletonText: React.FC<SkeletonProps> = ({ className }) => (
  <div className={cn(SKELETON.text, className)} />
);

export const SkeletonHeading: React.FC<SkeletonProps> = ({ className }) => (
  <div className={cn(SKELETON.heading, className)} />
);

export const SkeletonAvatar: React.FC<SkeletonProps> = ({ className }) => (
  <div className={cn(SKELETON.avatar, className)} />
);

export const SkeletonCard: React.FC<SkeletonProps> = ({ className }) => (
  <div className={cn(SKELETON.card, className)} />
);

export const SkeletonRow: React.FC<SkeletonProps> = ({ className }) => (
  <div className={cn(SKELETON.row, className)} />
);

// Table skeleton
export const SkeletonTable: React.FC<{ rows?: number }> = ({ rows = 5 }) => (
  <div className="space-y-3">
    <div className="flex gap-4">
      <SkeletonText className="w-24" />
      <SkeletonText className="w-32" />
      <SkeletonText className="w-20" />
      <SkeletonText className="flex-1" />
    </div>
    {Array.from({ length: rows }).map((_, i) => (
      <SkeletonRow key={i} className="w-full" />
    ))}
  </div>
);

// Card list skeleton
export const SkeletonCardList: React.FC<{ count?: number }> = ({ count = 3 }) => (
  <div className="space-y-3">
    {Array.from({ length: count }).map((_, i) => (
      <div key={i} className="bg-card rounded-2xl border-2 border-border/50 p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <SkeletonAvatar className="w-8 h-8" />
            <SkeletonText className="w-32" />
          </div>
          <SkeletonText className="w-16" />
        </div>
        <div className="space-y-2">
          <SkeletonText className="w-full" />
          <SkeletonText className="w-3/4" />
        </div>
      </div>
    ))}
  </div>
);

// =============================================================================
// TOAST NOTIFICATION
// =============================================================================

interface ToastProps {
  message: string;
  type: 'success' | 'error' | 'info';
  onClose?: () => void;
}

export const Toast: React.FC<ToastProps> = ({ message, type, onClose }) => {
  const styles = {
    success: 'bg-success shadow-success/30',
    error: 'bg-destructive shadow-destructive/30',
    info: 'bg-primary shadow-primary/30',
  };
  
  const icons = {
    success: CheckCircle2,
    error: XCircle,
    info: Clock,
  };
  
  const Icon = icons[type];
  
  return (
    <div className={cn(
      'fixed top-4 right-4 z-50 px-4 py-3 rounded-xl shadow-xl',
      'flex items-center gap-2 text-white text-sm font-semibold',
      'transform transition-all duration-300 animate-slide-in-top',
      styles[type]
    )}>
      <Icon className="w-4 h-4" />
      {message}
      {onClose && (
        <button onClick={onClose} className="ml-2 p-0.5 hover:bg-white/20 rounded transition-colors">
          <XCircle className="w-4 h-4" />
        </button>
      )}
    </div>
  );
};

// =============================================================================
// LOADING SPINNER
// =============================================================================

interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export const Spinner: React.FC<SpinnerProps> = ({ size = 'md', className }) => {
  const sizes = {
    sm: 'w-4 h-4',
    md: 'w-6 h-6',
    lg: 'w-8 h-8',
  };
  
  return <Loader2 className={cn(sizes[size], 'animate-spin text-primary', className)} />;
};

// Full page loading
export const LoadingPage: React.FC<{ message?: string }> = ({ message = 'Loading...' }) => (
  <div className="flex items-center justify-center min-h-[400px]">
    <div className="flex flex-col items-center gap-4">
      <Spinner size="lg" />
      <p className="text-muted-foreground font-medium">{message}</p>
    </div>
  </div>
);

// =============================================================================
// CARD COMPONENT
// =============================================================================

interface CardProps {
  children: React.ReactNode;
  className?: string;
  hover?: boolean;
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

export const Card: React.FC<CardProps> = ({ 
  children, 
  className, 
  hover = false,
  padding = 'md'
}) => {
  const paddingStyles = {
    none: '',
    sm: 'p-3',
    md: 'p-4',
    lg: 'p-6',
  };
  
  return (
    <div className={cn(
      hover ? DESIGN_SYSTEM.components.cardInteractive : DESIGN_SYSTEM.components.cardBase,
      paddingStyles[padding],
      className
    )}>
      {children}
    </div>
  );
};

// =============================================================================
// BUTTON COMPONENT
// =============================================================================

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  icon?: React.ElementType;
  iconPosition?: 'left' | 'right';
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'primary',
  size = 'md',
  loading = false,
  icon: Icon,
  iconPosition = 'left',
  disabled,
  className,
  ...props
}) => {
  const sizes = {
    sm: 'px-3 py-1.5 text-sm',
    md: 'px-4 py-2 text-sm',
    lg: 'px-5 py-2.5 text-base',
  };
  
  return (
    <button
      disabled={disabled || loading}
      className={cn(
        DESIGN_SYSTEM.components.buttonBase,
        BUTTON_VARIANTS[variant],
        sizes[size],
        'disabled:opacity-50 disabled:cursor-not-allowed',
        className
      )}
      {...props}
    >
      {loading ? (
        <Spinner size="sm" className="text-current" />
      ) : (
        Icon && iconPosition === 'left' && <Icon className="w-4 h-4" />
      )}
      {children}
      {!loading && Icon && iconPosition === 'right' && <Icon className="w-4 h-4" />}
    </button>
  );
};

// =============================================================================
// INPUT COMPONENT
// =============================================================================

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  icon?: React.ElementType;
}

export const Input: React.FC<InputProps> = ({
  label,
  error,
  icon: Icon,
  className,
  ...props
}) => (
  <div className="space-y-1.5">
    {label && (
      <label className="text-sm font-semibold text-foreground">{label}</label>
    )}
    <div className="relative">
      {Icon && (
        <Icon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
      )}
      <input
        className={cn(
          DESIGN_SYSTEM.components.inputBase,
          Icon && 'pl-10',
          error && 'border-destructive focus:border-destructive focus:ring-destructive/20',
          className
        )}
        {...props}
      />
    </div>
    {error && <p className="text-sm text-destructive font-medium">{error}</p>}
  </div>
);

// =============================================================================
// SELECT COMPONENT
// =============================================================================

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  options: { value: string | number; label: string }[];
}

export const Select: React.FC<SelectProps> = ({
  label,
  error,
  options,
  className,
  ...props
}) => (
  <div className="space-y-1.5">
    {label && (
      <label className="text-sm font-semibold text-foreground">{label}</label>
    )}
    <select
      className={cn(
        DESIGN_SYSTEM.components.inputBase,
        'cursor-pointer',
        error && 'border-destructive focus:border-destructive focus:ring-destructive/20',
        className
      )}
      {...props}
    >
      {options.map(opt => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
    {error && <p className="text-sm text-destructive font-medium">{error}</p>}
  </div>
);

// =============================================================================
// SECTION HEADER
// =============================================================================

interface SectionHeaderProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export const SectionHeader: React.FC<SectionHeaderProps> = ({
  title,
  description,
  action,
  className
}) => (
  <div className={cn('flex items-center justify-between mb-6', className)}>
    <div>
      <h2 className={DESIGN_SYSTEM.typography.h3}>{title}</h2>
      {description && <p className="text-muted-foreground mt-1">{description}</p>}
    </div>
    {action}
  </div>
);