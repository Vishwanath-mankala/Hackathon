---
system: Vanguard Ledger Reconciliation Console
version: 2.0
typography:
  sans: IBM Plex Sans
  mono: IBM Plex Mono
  body: 13px
  heading: 18px
  page-title: 20px
  case: sentence
shapes:
  radius: 0
  corners: square
depth:
  method: hairline borders
  shadow: none
themes:
  - light
  - dark
---

# Reconciliation Console Design System

An instrument-grade interface for bank reconciliation analysts working long shifts under audit pressure. Every decision optimizes for scan-ability of dense tabular data, not visual personality. Color encodes confidence, not decoration.

## 1. Principles

- **Color means confidence.** The tier waterfall uses one hue stepping down. Amber and red are reserved exclusively for items needing human attention.
- **Zero radius.** Square corners on every surface — buttons, inputs, cards, table cells, badges. Instrument-grade, not consumer-app.
- **Hairline depth.** 1px borders separate surfaces. No shadows anywhere.
- **Dual themed.** Light and dark themes tuned independently. No pure black, no pure white — slightly tinted neutrals reduce glare fatigue.
- **The table is the hero.** It occupies the majority of the viewport at all times.

## 2. Color system

### Light theme

| Token               | Hex       | Use                                     |
|---------------------|-----------|-----------------------------------------|
| bg-canvas           | #EEF0F2   | App background                          |
| bg-surface          | #FFFFFF   | Tables, panels                          |
| bg-surface-sunken   | #F5F6F8   | Row alternation, input backgrounds      |
| border-default      | #D3D8DD   | Hairline dividers, table gridlines      |
| border-strong       | #AEB6BE   | Focused/active borders                  |
| text-primary        | #14181D   | Body text, figures                      |
| text-secondary      | #5B6570   | Labels, metadata                        |
| accent-action       | #1B4B8F   | Primary buttons, links, active nav      |
| tier-1-exact        | #1B4B8F   | Tier 1: exact match (deepest)           |
| tier-2-date         | #3E76B0   | Tier 2: date tolerance                  |
| tier-3-reference    | #6FA0C9   | Tier 3: reference overlap               |
| tier-4-amount       | #A9C4DE   | Tier 4: amount tolerance (lightest)     |
| status-amber        | #9A6A15   | Ambiguous cluster, needs review         |
| status-red          | #A3312A   | Anomaly, escalation, gate failure       |
| status-green        | #2C7A4B   | Resolved, reconciled, batch passed      |

### Dark theme

| Token               | Hex       | Use                                     |
|---------------------|-----------|-----------------------------------------|
| bg-canvas           | #14171B   | App background                          |
| bg-surface          | #1B1F24   | Tables, panels                          |
| bg-surface-sunken   | #20252B   | Row alternation, input backgrounds      |
| border-default      | #2C333A   | Hairline dividers, table gridlines      |
| border-strong       | #4A5560   | Focused/active borders                  |
| text-primary        | #E7EAED   | Body text, figures                      |
| text-secondary      | #9AA5B1   | Labels, metadata                        |
| accent-action       | #6C9FDB   | Primary buttons, links, active nav      |
| tier-1-exact        | #6C9FDB   | Tier 1: exact match                     |
| tier-2-date         | #5588BF   | Tier 2: date tolerance                  |
| tier-3-reference    | #3F6C93   | Tier 3: reference overlap               |
| tier-4-amount       | #2E4E68   | Tier 4: amount tolerance                |
| status-amber        | #C99A3F   | Ambiguous cluster, needs review         |
| status-red          | #C4534B   | Anomaly, escalation, gate failure       |
| status-green        | #4E9E71   | Resolved, reconciled, batch passed      |

## 3. Typography

- **UI text**: IBM Plex Sans at 400/500/600. Body 13px, section headers 16-18px, page title 20px.
- **Data**: IBM Plex Mono with tabular figures (`font-feature-settings: "tnum" 1, "zero" 1`). All amounts, dates, IDs, reference codes, batch filenames.
- **Case**: Sentence case only. Never all-caps for labels.
- **Emphasis**: Use weight (medium, not bold) for emphasis. Never bold single words within sentences.

## 4. Layout

- 56px icon-only nav rail, left-docked
- Single-line instrument header strip (batch info, health, theme toggle)
- Full-width workspace for table content
- Docked detail drawer (not modal) for row inspection

## 5. Components

### Buttons
- Primary: `bg-accent-action text-white font-medium` — square, no gradient, no glow
- Surface: `bg-surface border border-border-default text-text-primary font-medium`
- Destructive: `bg-status-red text-white font-medium`

### Inputs
- `bg-surface-sunken border border-border-default font-mono text-[13px]`
- Focus: `border-border-strong`

### Tables
- Headers: `bg-surface-sunken text-[12px] text-text-secondary font-medium` — sentence case
- Rows: alternate `bg-surface` / `bg-surface-sunken`, `h-[36px]`
- Amounts: `font-mono text-right` always
- Gridlines: 1px solid border-default on all cells

### Status badges
- Square color swatch (w-2 h-2) + plain text
- Color maps to tier confidence or status severity
- No rounded pills, no glowing dots

### Tier legend
- Compact horizontal strip docked above transaction table
- Square swatches in tier order (1-4), then amber, then red
- Doubles as clickable filter

### Toasts
- Square, no backdrop-blur
- 2px left-border in semantic color
- Plain text: state what happened, what to do. No exclamation points.

## 6. Rules

- No emoji anywhere
- No shadows for depth
- No gradients (text or background)
- No rounded corners on any element
- No all-caps labels or tracking-wider
- No eyebrow/kicker badges above headings
- No stat-card hero patterns
- Amber and red never used decoratively — only for items needing human attention
