export const DESIGN_SYSTEM = {
  colors: {
    primary: "from-primary to-primary/80",
    card: "bg-card border border-border",
    accent: "bg-accent/50",
    destructive: "bg-destructive/10 border border-destructive/20 text-destructive",
    muted: "bg-muted/30",
    hover: "hover:shadow-md hover:bg-accent/50 transition-all",
  },
  spacing: {
    section: "py-8",
    container: "max-w-[1400px] mx-auto px-8",
    gap: "gap-4",
    large: "gap-8",
  },
  radius: {
    sm: "rounded-lg",
    md: "rounded-xl",
    lg: "rounded-2xl",
  },
  typography: {
    title: "text-xl font-bold text-foreground",
    subtitle: "text-xs text-muted-foreground",
    heading3: "text-xl font-bold text-foreground",
    body: "text-sm font-medium text-foreground",
    small: "text-xs font-medium text-muted-foreground",
    label: "text-xs font-semibold text-muted-foreground uppercase tracking-wider",
  },
  shadows: {
    card: "shadow-lg shadow-primary/25",
    hover: "hover:shadow-lg transition-all",
  },
  transitions: {
    base: "transition-all",
    fast: "transition-colors duration-200",
  },
} as const;

export const BUTTON_VARIANTS = {
  primary:
    "bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50 font-semibold shadow-lg shadow-primary/25",
  secondary:
    "border border-border bg-card hover:bg-accent disabled:opacity-50",
  ghost: "hover:bg-accent/50 disabled:opacity-50",
} as const;
