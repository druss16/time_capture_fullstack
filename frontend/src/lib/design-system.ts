/**
 * design-system.ts - Premium SaaS Design System
 * Inspired by Laurel AI's clean, professional aesthetic
 * 
 * UPDATES:
 * - Added CLIENT_COLORS for alternating client cards
 * - Added ROLE_COLORS for role badges
 * - Added SKELETON styles for loading states
 * - Added cn() helper for class merging
 * - Improved STATUS_COLORS with dot indicators
 * - Darker text for better readability
 */

// =============================================================================
// HELPER FUNCTION
// =============================================================================

/** Combine class names, filtering out falsy values */
export const cn = (...classes: (string | undefined | null | false)[]) => 
  classes.filter(Boolean).join(' ');

// =============================================================================
// MAIN DESIGN SYSTEM
// =============================================================================

export const DESIGN_SYSTEM = {
  // Typography - using Plus Jakarta Sans
  typography: {
    // Headings - with tracking-tight for premium feel
    h1: "text-4xl font-extrabold tracking-tight text-foreground",
    h2: "text-3xl font-bold tracking-tight text-foreground",
    h3: "text-2xl font-bold tracking-tight text-foreground",
    h4: "text-xl font-semibold text-foreground",
    h5: "text-lg font-semibold text-foreground",
    h6: "text-base font-semibold text-foreground",
    
    // Body text - DARKER for readability
    body: "text-base text-foreground",
    bodySmall: "text-sm text-foreground",
    small: "text-sm text-muted-foreground",
    tiny: "text-xs text-muted-foreground",
    
    // Special
    label: "text-sm font-semibold text-foreground",
    caption: "text-xs font-medium text-muted-foreground uppercase tracking-wider",
  },

  // Colors - semantic color classes
  colors: {
    // Backgrounds
    background: "bg-background",
    card: "bg-card",
    cardHover: "bg-card hover:bg-muted/50",
    muted: "bg-muted",
    
    // Text - using foreground for darker, more readable text
    text: "text-foreground",
    textMuted: "text-muted-foreground",
    textPrimary: "text-primary",
    textSuccess: "text-success",
    textWarning: "text-warning",
    textDestructive: "text-destructive",
    
    // Interactive states
    hover: "hover:bg-muted/50",
    active: "bg-primary/10",
  },

  // Border radius - larger for modern feel
  radius: {
    none: "rounded-none",
    sm: "rounded-lg",      // 0.5rem
    md: "rounded-xl",      // 0.75rem  
    lg: "rounded-2xl",     // 1rem
    xl: "rounded-3xl",     // 1.5rem
    full: "rounded-full",
  },

  // Shadows - soft and diffused
  shadows: {
    none: "shadow-none",
    sm: "shadow-sm",
    md: "shadow-md",
    lg: "shadow-lg",
    xl: "shadow-xl",
    // Interactive shadow on hover
    hover: "shadow-sm hover:shadow-lg transition-shadow duration-300",
    // Premium card shadow
    card: "shadow-sm shadow-black/5",
    // Elevated shadow
    elevated: "shadow-xl shadow-black/10",
  },

  // Spacing - generous for breathing room
  spacing: {
    container: "max-w-7xl mx-auto px-4 sm:px-6 lg:px-8",
    containerNarrow: "max-w-4xl mx-auto px-4 sm:px-6 lg:px-8",
    containerWide: "max-w-screen-2xl mx-auto px-4 sm:px-6 lg:px-8",
    section: "py-8 sm:py-12",
    card: "p-6 sm:p-8",
    cardCompact: "p-4 sm:p-5",
  },

  // Borders - thicker (border-2) for more intentional look
  borders: {
    default: "border-2 border-border",
    subtle: "border border-border/50",
    primary: "border-2 border-primary",
    transparent: "border-2 border-transparent",
  },

  // Transitions
  transitions: {
    base: "transition-all duration-200 ease-out",
    fast: "transition-all duration-150 ease-out",
    slow: "transition-all duration-300 ease-out",
    spring: "transition-all duration-500 ease-[cubic-bezier(0.34,1.56,0.64,1)]",
  },

  // Layout patterns
  layout: {
    // Flex patterns
    flexCenter: "flex items-center justify-center",
    flexBetween: "flex items-center justify-between",
    flexStart: "flex items-center justify-start",
    flexEnd: "flex items-center justify-end",
    flexCol: "flex flex-col",
    flexColCenter: "flex flex-col items-center justify-center",
    
    // Grid patterns
    grid2: "grid grid-cols-1 sm:grid-cols-2 gap-4",
    grid3: "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4",
    grid4: "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4",
    gridAuto: "grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4",
  },

  // Component specific patterns
  components: {
    // Card variations - using border-2 for thicker borders
    cardBase: "bg-card rounded-2xl border-2 border-border/50 shadow-sm",
    cardInteractive: "bg-card rounded-2xl border-2 border-border/50 shadow-sm hover:shadow-lg hover:border-primary/30 hover:-translate-y-0.5 transition-all duration-300",
    cardElevated: "bg-card rounded-2xl shadow-xl shadow-black/5",
    cardGradient: "bg-gradient-to-br from-card to-muted/30 rounded-2xl border-2 border-border/50",
    
    // Input variations
    inputBase: "w-full px-4 py-3 rounded-xl bg-muted/50 border-2 border-border/50 text-sm font-medium transition-all focus:bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none",
    inputCompact: "w-full px-3 py-2 rounded-lg bg-muted/50 border-2 border-border/50 text-sm transition-all focus:bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none",
    
    // Button variations
    buttonBase: "inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl font-semibold text-sm transition-all duration-200 active:scale-[0.98] focus:outline-none focus:ring-2 focus:ring-offset-2",
    buttonIcon: "inline-flex items-center justify-center w-10 h-10 rounded-xl transition-all duration-200 active:scale-[0.98] focus:outline-none focus:ring-2 focus:ring-offset-2",
  },
} as const;

// =============================================================================
// BUTTON VARIANTS
// =============================================================================

export const BUTTON_VARIANTS = {
  primary: `
    bg-primary text-primary-foreground
    hover:bg-primary/90
    focus:ring-primary
    shadow-lg shadow-primary/25 hover:shadow-xl hover:shadow-primary/30
  `.trim().replace(/\s+/g, ' '),
  
  secondary: `
    bg-card text-foreground border-2 border-border
    hover:bg-muted hover:border-primary/20
    focus:ring-primary
  `.trim().replace(/\s+/g, ' '),
  
  ghost: `
    bg-transparent text-muted-foreground
    hover:bg-muted hover:text-foreground
    focus:ring-primary
  `.trim().replace(/\s+/g, ' '),
  
  destructive: `
    bg-destructive text-destructive-foreground
    hover:bg-destructive/90
    focus:ring-destructive
    shadow-lg shadow-destructive/25
  `.trim().replace(/\s+/g, ' '),
  
  success: `
    bg-success text-success-foreground
    hover:bg-success/90
    focus:ring-success
    shadow-lg shadow-success/25
  `.trim().replace(/\s+/g, ' '),
  
  outline: `
    bg-transparent text-primary border-2 border-primary
    hover:bg-primary hover:text-primary-foreground
    focus:ring-primary
  `.trim().replace(/\s+/g, ' '),
  
  link: `
    bg-transparent text-primary underline-offset-4
    hover:underline
    p-0
  `.trim().replace(/\s+/g, ' '),
} as const;

// =============================================================================
// BADGE VARIANTS
// =============================================================================

export const BADGE_VARIANTS = {
  default: "bg-muted text-muted-foreground",
  primary: "bg-primary/10 text-primary",
  secondary: "bg-secondary/10 text-secondary",
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  destructive: "bg-destructive/10 text-destructive",
  info: "bg-info/10 text-info",
  purple: "bg-purple/10 text-purple",
} as const;

// =============================================================================
// STATUS COLORS - With dot indicators for visual clarity
// =============================================================================

export const STATUS_COLORS = {
  draft: { 
    bg: "bg-muted", 
    text: "text-muted-foreground", 
    border: "border-muted",
    dot: "bg-slate-400"
  },
  pending: { 
    bg: "bg-warning/10", 
    text: "text-warning", 
    border: "border-warning/30",
    dot: "bg-amber-500"
  },
  submitted: { 
    bg: "bg-info/10", 
    text: "text-info", 
    border: "border-info/30",
    dot: "bg-blue-500"
  },
  approved: { 
    bg: "bg-success/10", 
    text: "text-success", 
    border: "border-success/30",
    dot: "bg-emerald-500"
  },
  rejected: { 
    bg: "bg-destructive/10", 
    text: "text-destructive", 
    border: "border-destructive/30",
    dot: "bg-red-500"
  },
  locked: { 
    bg: "bg-primary/10", 
    text: "text-primary", 
    border: "border-primary/30",
    dot: "bg-purple-500"
  },
  billed: { 
    bg: "bg-primary/10", 
    text: "text-primary", 
    border: "border-primary/30",
    dot: "bg-teal-500"
  },
} as const;

// Helper to get status color
export const getStatusColor = (status: keyof typeof STATUS_COLORS) => 
  STATUS_COLORS[status] || STATUS_COLORS.draft;

// =============================================================================
// ROLE COLORS - For user role badges
// =============================================================================

export const ROLE_COLORS = {
  owner: "bg-amber-500 text-white",
  admin: "bg-primary text-primary-foreground",
  manager: "bg-purple-500 text-white",
  member: "bg-muted text-muted-foreground",
} as const;

// Helper to get role color
export const getRoleColor = (role: keyof typeof ROLE_COLORS) => 
  ROLE_COLORS[role] || ROLE_COLORS.member;

// =============================================================================
// CLIENT COLORS - Alternating colors for client cards (like Laurel)
// =============================================================================

export const CLIENT_COLORS = [
  { bg: "bg-teal-50", border: "border-teal-200", accent: "bg-teal-100", text: "text-teal-700", hours: "text-teal-600" },
  { bg: "bg-amber-50", border: "border-amber-200", accent: "bg-amber-100", text: "text-amber-700", hours: "text-amber-600" },
  { bg: "bg-purple-50", border: "border-purple-200", accent: "bg-purple-100", text: "text-purple-700", hours: "text-purple-600" },
  { bg: "bg-rose-50", border: "border-rose-200", accent: "bg-rose-100", text: "text-rose-700", hours: "text-rose-600" },
  { bg: "bg-sky-50", border: "border-sky-200", accent: "bg-sky-100", text: "text-sky-700", hours: "text-sky-600" },
  { bg: "bg-emerald-50", border: "border-emerald-200", accent: "bg-emerald-100", text: "text-emerald-700", hours: "text-emerald-600" },
  { bg: "bg-indigo-50", border: "border-indigo-200", accent: "bg-indigo-100", text: "text-indigo-700", hours: "text-indigo-600" },
  { bg: "bg-orange-50", border: "border-orange-200", accent: "bg-orange-100", text: "text-orange-700", hours: "text-orange-600" },
] as const;

// Helper to get client color by index (cycles through colors)
export const getClientColor = (index: number) => 
  CLIENT_COLORS[index % CLIENT_COLORS.length];

// =============================================================================
// CATEGORY COLORS - For time tracking categories
// =============================================================================

export const CATEGORY_COLORS: Record<string, { bg: string; text: string; accent: string }> = {
  "Tax Preparation": { bg: "bg-blue-50", text: "text-blue-700", accent: "bg-blue-500" },
  "Tax Planning": { bg: "bg-indigo-50", text: "text-indigo-700", accent: "bg-indigo-500" },
  "Tax Research": { bg: "bg-violet-50", text: "text-violet-700", accent: "bg-violet-500" },
  "Tax Compliance": { bg: "bg-purple-50", text: "text-purple-700", accent: "bg-purple-500" },
  "Audit/Assurance": { bg: "bg-purple-50", text: "text-purple-700", accent: "bg-purple-500" },
  "Accounting/Bookkeeping": { bg: "bg-teal-50", text: "text-teal-700", accent: "bg-teal-500" },
  "Financial Statement Prep": { bg: "bg-cyan-50", text: "text-cyan-700", accent: "bg-cyan-500" },
  "Advisory/Consulting": { bg: "bg-amber-50", text: "text-amber-700", accent: "bg-amber-500" },
  "Advisory/Financial Planning": { bg: "bg-amber-50", text: "text-amber-700", accent: "bg-amber-500" },
  "Software Development": { bg: "bg-emerald-50", text: "text-emerald-700", accent: "bg-emerald-500" },
  "Research/AI Assistance": { bg: "bg-lime-50", text: "text-lime-700", accent: "bg-lime-500" },
  "Email/Communication": { bg: "bg-sky-50", text: "text-sky-700", accent: "bg-sky-500" },
  "Meetings": { bg: "bg-rose-50", text: "text-rose-700", accent: "bg-rose-500" },
  "Administration": { bg: "bg-slate-50", text: "text-slate-700", accent: "bg-slate-500" },
  "Documentation": { bg: "bg-stone-50", text: "text-stone-700", accent: "bg-stone-500" },
  "Review": { bg: "bg-zinc-50", text: "text-zinc-700", accent: "bg-zinc-500" },
  "Payroll Services": { bg: "bg-green-50", text: "text-green-700", accent: "bg-green-500" },
  "Idle": { bg: "bg-gray-100", text: "text-gray-500", accent: "bg-gray-400" },
  "Uncategorized": { bg: "bg-gray-100", text: "text-gray-500", accent: "bg-gray-400" },
  // Default fallback
  default: { bg: "bg-muted", text: "text-muted-foreground", accent: "bg-muted-foreground" },
};

// Helper to get category color
export const getCategoryColor = (category: string) => {
  return CATEGORY_COLORS[category] || CATEGORY_COLORS.default;
};

// =============================================================================
// SKELETON STYLES - For loading states
// =============================================================================

export const SKELETON = {
  base: "bg-muted rounded animate-pulse",
  text: "h-4 bg-muted rounded animate-pulse",
  textSm: "h-3 bg-muted rounded animate-pulse",
  heading: "h-6 bg-muted rounded animate-pulse",
  avatar: "w-10 h-10 bg-muted rounded-full animate-pulse",
  card: "h-24 bg-muted rounded-2xl animate-pulse",
  row: "h-12 bg-muted rounded-xl animate-pulse",
  button: "h-10 w-24 bg-muted rounded-xl animate-pulse",
} as const;

// =============================================================================
// ANIMATIONS
// =============================================================================

export const ANIMATIONS = {
  fadeIn: "animate-fade-in",
  slideUp: "animate-slide-up",
  slideInRight: "animate-slide-in-right",
  slideInTop: "animate-slide-in-top",
  scaleIn: "animate-scale-in",
  staggerChildren: "stagger-children",
} as const;

// =============================================================================
// TYPE EXPORTS
// =============================================================================

export type ButtonVariant = keyof typeof BUTTON_VARIANTS;
export type BadgeVariant = keyof typeof BADGE_VARIANTS;
export type StatusType = keyof typeof STATUS_COLORS;
export type RoleType = keyof typeof ROLE_COLORS;