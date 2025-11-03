# Frontend Structure & Design System

This document describes the clean frontend foundation with consistent styling, component patterns, and code organization.

## Directory Structure

```
frontend/src/
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
├── pages/
│   ├── TimecardSummary.tsx  # Main timecard page (refactored)
│   └── ... other pages
├── index.css                # Tailwind & design tokens (HSL colors)
└── main.tsx                 # App entry point
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

## Best Practices for New Pages

1. **Import from components/common** for reusable UI:
```tsx
import { Header, Button, Card, Input } from "@/components/common";
```

2. **Use design system constants**:
```tsx
import { DESIGN_SYSTEM } from "@/lib/design-system";
<div className={DESIGN_SYSTEM.spacing.container}>
```

3. **Use utility functions**:
```tsx
import { todayIso, fmtHours, displayClientName } from "@/lib/utils";
```

4. **Centralize API calls**:
```tsx
import { API_ENDPOINTS } from "@/lib/api";
fetch(API_ENDPOINTS.endpoint)
```

5. **Create feature-specific components**:
```
components/
  ├── common/
  └── [feature-name]/
      ├── Component1.tsx
      ├── Component2.tsx
      └── index.ts
```

## Creating a New Page

### Step 1: Create the page file
```tsx
// frontend/src/pages/MyNewPage.tsx
import { Header } from "@/components/common";
import { DESIGN_SYSTEM } from "@/lib/design-system";

export default function MyNewPage() {
  return (
    <div className="min-h-screen bg-background">
      <Header
        title="My Page"
        subtitle="Page description"
        icon={<SomeIcon />}
      />
      <div className={DESIGN_SYSTEM.spacing.container + " " + DESIGN_SYSTEM.spacing.section}>
        {/* Your content here */}
      </div>
    </div>
  );
}
```

### Step 2: Create feature components (optional)
```tsx
// frontend/src/components/myfeature/MyComponent.tsx
import { DESIGN_SYSTEM } from "@/lib/design-system";

export const MyComponent: React.FC = () => {
  return <div className={DESIGN_SYSTEM.radius.md}>Content</div>;
};
```

### Step 3: Export from index (optional)
```tsx
// frontend/src/components/myfeature/index.ts
export { MyComponent } from "./MyComponent";
```

### Step 4: Import and use
```tsx
import { MyComponent } from "@/components/myfeature";
```

## CSS Basis for All Pages

The CSS foundation is already set up in `frontend/src/index.css` with:

- **Tailwind CSS** - Utility-first CSS framework
- **HSL Color Variables** - Centralized color scheme (light & dark modes)
- **Base Styles** - Default border colors, body styles
- **Design System Integration** - All colors match the design system constants

When you create a new page, you automatically inherit:
- All Tailwind utilities
- All CSS variables (colors, shadows, etc.)
- All design system defaults
- Full dark mode support

## Environment Variables

```bash
VITE_API_BASE_URL=https://your-api.com  # Backend API base URL
VITE_AUTH_DISABLED=true                 # Disable auth for development
```

The API base URL is automatically handled in `lib/api.ts` and defaults to `/api` (works with Vite proxy in dev).

## Adding Styling to New Components

Don't hardcode styles. Use these approaches:

### ✅ Good Approaches

1. **Use design system tokens**:
```tsx
className={`p-6 ${DESIGN_SYSTEM.radius.lg} ${DESIGN_SYSTEM.colors.primary}`}
```

2. **Use Tailwind utilities**:
```tsx
className="p-6 rounded-2xl text-foreground hover:shadow-lg transition-all"
```

3. **Combine both**:
```tsx
className={`${DESIGN_SYSTEM.spacing.container} flex items-center gap-4`}
```

### ❌ Avoid

- Hardcoded colors: `bg-[#1f3a7a]` ❌
- Inline styles: `style={{color: 'navy'}}` ❌
- One-off utilities: `bg-primary/50` (use the tokens instead)

## Dark Mode Support

The design system automatically supports dark mode. Just use the color classes and they'll adapt:

```tsx
<div className="bg-card text-foreground">
  This automatically changes in dark mode!
</div>
```

CSS variables are defined for both light and dark modes in `index.css`.

## Responsive Design

Use Tailwind's responsive breakpoints:

```tsx
<div className="grid grid-cols-1 md:grid-cols-3 gap-4">
  {/* 1 column on mobile, 3 columns on desktop */}
</div>
```

Common breakpoints:
- `sm:` - 640px
- `md:` - 768px
- `lg:` - 1024px
- `xl:` - 1280px
