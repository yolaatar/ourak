# Ourak — Frontend Guidelines

## Project
React 18 + Vite, plain CSS modules, no Tailwind, no component library.
This is a research paper discovery tool for a biomedical AI lab.

## Design system

### Colors (dark theme)
--color-bg: #0f1117
--color-surface: #1a1d27
--color-border: #2a2d3a
--color-text-primary: #e4e5e9
--color-text-secondary: #9ca0ad
--color-text-muted: #6b7084
--color-accent: #3b82f6
--color-accent-hover: #60a5fa
--color-success: #22c55e
--color-warning: #f59e0b
--color-danger: #ef4444

### Source badge colors (dark theme — rgba backgrounds)
pubmed: #4ade80 on rgba(34, 197, 94, 0.15)
arxiv: #fb923c on rgba(234, 88, 12, 0.15)
biorxiv: #a78bfa on rgba(124, 58, 237, 0.15)
paperswithcode: #2563eb (blue)
semanticscholar: #6b7280 (gray)

### Typography
Font stack: Inter, system-ui, -apple-system, sans-serif
Base size: 14px
Line height: 1.6
Weights used: 400 (regular), 500 (medium), 600 (semibold)

Scale:
- xs: 11px  — badges, metadata
- sm: 12px  — secondary info, authors
- base: 14px — body, abstracts
- md: 16px  — card titles
- lg: 20px  — page section headers
- xl: 24px  — page titles

### Spacing
Use multiples of 4px.
--space-1: 4px
--space-2: 8px
--space-3: 12px
--space-4: 16px
--space-6: 24px
--space-8: 32px
--space-12: 48px

### Borders + radius
--radius-sm: 4px  — badges, tags
--radius-md: 8px  — cards, inputs
--radius-lg: 12px — modals, panels
--border: 1px solid var(--color-border)

### Shadows
Use sparingly. Only two levels:
--shadow-sm: 0 1px 3px rgba(0,0,0,0.06)  — cards
--shadow-md: 0 4px 12px rgba(0,0,0,0.08) — dropdowns, modals

## Layout rules
- Max content width: 780px, centered
- Page padding: 24px horizontal on desktop, 16px on mobile
- No sidebars in MVP
- Sticky header: 56px tall, white, border-bottom only (no shadow)

## Component patterns

### Cards
White background, --border, --radius-md, --shadow-sm
Padding: 16px
Hover: border-color shifts to #d1d5db, no transform/scale effects
No heavy hover animations — this is a reading tool not a landing page

### Buttons
Primary: accent bg, white text, --radius-md, 8px 16px padding
Secondary: white bg, border, text-primary
Danger: danger color, white text
Height: 36px for regular, 32px for compact
No gradients, no box shadows on buttons

### Inputs + textareas
Border: --border
Border-radius: --radius-md
Padding: 8px 12px
Focus: outline none, border-color: --color-accent, 
  box-shadow: 0 0 0 3px rgba(37,99,235,0.1)
Font: inherit

### Tags / badges
Inline-flex, --radius-sm, 3px 8px padding, 11px font
Colored background at 10-15% opacity with matching text color
Example: pubmed badge = background #dcfce7, color #16a34a

### Loading states
Use a simple pulsing skeleton (opacity 0.5 → 1 animation)
Never use spinners except for button loading states

## CSS architecture
One CSS module per component: ComponentName.module.css
Global variables in src/styles/globals.css
No inline styles except truly dynamic values (e.g. progress bar width)
Class names: camelCase in modules (.paperCard, .authorList)

## File structure
src/
├── pages/          ← Login, Onboarding, Digest
├── components/     ← PaperCard, TopicBadge, FeedbackButtons, etc.
├── styles/
│   └── globals.css ← CSS variables + resets only
├── api.js          ← all fetch calls
└── main.jsx

## Do and don't

DO:
- Keep components small and focused
- Use semantic HTML (article, header, nav, main, section)
- Make it feel like a clean academic tool, not a startup landing page
- Optimize for scannability — researchers skim
- Mobile-responsive from the start (single column on mobile)

DON'T:
- No animations except subtle transitions (200ms ease)
- No gradients
- No heavy drop shadows
- No emoji in UI chrome (only in user-facing content like feedback buttons)
- No placeholder lorem ipsum — use realistic paper titles and author names
- Don't install any UI component library without asking first
- Don't use Tailwind