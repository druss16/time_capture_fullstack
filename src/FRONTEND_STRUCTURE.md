# Frontend Structure & Design System

This document describes the clean frontend foundation with consistent styling, component patterns, and code organization.

## Directory Structure

```
src/
├── lib/
│   ├── design-system.ts      # Design tokens, colors, spacing, typography
│   ├── api.ts               # API base URLs and endpoints
│   └── utils/
│       ├── date.ts          # Date utilities
│       └── formatting.ts    # Formatting utilities
├── components/
│   ├── common/              # Reusable base components
│   │   ├── Header.tsx       # Page header with icon & user info
│   │   ├── Button.tsx       # Button component with variants
│   │   ├── Card.tsx         # Card & StatsCard components
│   │   ├── Input.tsx        # Input field with icon support
│   │   └── index.ts         # Component exports
│   └── timecard/            # Feature-specific components
│       ├── FilterBar.tsx    # Date/user filters & actions
│       ├── StatsOverview.tsx # Stats cards display
│       ├── ClientCard.tsx   # Client breakdown card
│       ├── EmptyState.tsx   # Empty & loading states
│       └── index.ts         # Component exports
└── pages/
    └── TimecardSummary.tsx  # Main page component
```

## Design System

### Colors & Variants

The design system uses Tailwind CSS with HSL colors defined in `index.css`:

- **Primary**: Navy blue (#1f3a7a) - Used for important actions & highlights
- **Secondary**: Light gray - Used for subtle elements
- **Success**: Green - Used for positive states
- **Warning**: Amber - Used for caution states
- **Destructive**: Red - Used for errors & dangerous actions
- **Muted**: Light gray - Used for disabled/secondary text
- **Accent**: Light blue - Used for hover states

### Spacing

- **Container**: `max-w-[1400px] mx-auto px-8`
- **Section**: `py-8`
- **Gap**: `gap-4` (standard), `gap-8` (large)
- **Radius**: `rounded-lg` (sm), `rounded-xl` (md), `rounded-2xl` (lg)

### Typography

- **Title**: `text-xl font-bold text-foreground`
- **Heading3**: `text-xl font-bold text-foreground`
- **Body**: `text-sm font-medium text-foreground`
- **Small**: `text-xs font-medium text-muted-foreground`
- **Label**: `text-xs font-semibold text-muted-foreground uppercase tracking-wider`

### Transitions

- **Base**: `transition-all`
- **Fast**: `transition-colors duration-200`

## Component Patterns

### Button

```tsx
<Button variant="primary" size="md" icon={<Icon />}>
  Click me
</Button>
```

**Variants**: `primary`, `secondary`, `ghost`
**Sizes**: `sm`, `md`, `lg`

### Card

```tsx
<Card interactive>
  <div>Content here</div>
</Card>
```

**Props**: `children`, `className`, `interactive`

### Input

```tsx
<Input
  type="text"
  label="Full Name"
  icon={<UserIcon />}
  placeholder="Enter name"
  error="This field is required"
/>
```

### StatsCard

```tsx
<StatsCard
  gradient
  icon={<Clock />}
  label="Total Hours"
  value="8.5h"
  trend={<TrendingUp />}
/>
```

## Utility Functions

### Date Utils (`lib/utils/date.ts`)
- `todayIso()` - Get today's date in ISO format (YYYY-MM-DD)
- `formatDate(dateStr)` - Format ISO date to readable format
- `isValidISODate(dateStr)` - Validate ISO date format

### Formatting Utils (`lib/utils/formatting.ts`)
- `fmtHours(n)` - Format number as hours with 2 decimals
- `displayClientName(name)` - Normalize and display client name
- `pluralize(count, singular, plural)` - Pluralize words

## API Configuration

All API endpoints are centralized in `lib/api.ts`:

```tsx
import { API_ENDPOINTS } from "@/lib/api";

// Use endpoints like:
fetch(API_ENDPOINTS.whoami, { credentials: "include" })
fetch(API_ENDPOINTS.timecardsSummaryDay + "?date=2024-01-01")
```

**Available endpoints**:
- `API_ENDPOINTS.whoami` - Get current user info
- `API_ENDPOINTS.timecardsSummaryDay` - Get timecard summary for a day
- `API_ENDPOINTS.timercardsGenerate` - Generate timecard

## Best Practices

1. **Use the design system** - Don't add arbitrary Tailwind classes. Reference `DESIGN_SYSTEM` constants.
2. **Component composition** - Break large components into smaller, reusable pieces.
3. **Type safety** - Define interfaces for props and data structures.
4. **Error handling** - Always handle fetch errors and show user feedback via `ErrorBanner`.
5. **Loading states** - Use `LoadingState` component for async operations.
6. **Empty states** - Show `EmptyState` when no data is available.

## Adding New Components

1. **Base components** → `src/components/common/`
2. **Feature components** → `src/components/[feature]/`
3. **Export from index file** → `src/components/[folder]/index.ts`
4. **Use design system tokens** → Import from `@/lib/design-system`
5. **Type your props** → Define interfaces for all component props

## Styling Guidelines

### Do's ✅
- Use design system tokens: `DESIGN_SYSTEM.colors.primary`
- Use Tailwind utility classes consistently
- Compose classes for reusability
- Use semantic color names: `text-destructive`, `bg-accent`

### Don'ts ❌
- Don't hardcode arbitrary color values
- Don't mix inline styles with Tailwind
- Don't create one-off style objects
- Don't ignore hover/transition states

## Environment Variables

```bash
VITE_API_BASE_URL=https://your-api.com  # Backend API base URL
VITE_AUTH_DISABLED=true                 # Disable auth for development
```

The API base URL is automatically handled in `lib/api.ts` and defaults to `/api` (works with Vite proxy in dev).
