---
name: frontend-generator
description: Generates clean, performant, and maintainable modern Angular (v17+) and Tailwind CSS enterprise frontend code with Standalone components, Signals, inject() DI, OnPush change detection, and native control flow (@if/@for/@defer).
---

# Frontend Generator (Angular v17+ & Tailwind CSS)

## Overview
This skill guides the scaffolding, generation, and refinement of enterprise-grade, high-performance **Angular (v17+)** and **Tailwind CSS** frontend applications. It ensures strict compliance with modern Angular standards, signal-based reactivity, standalone component architectures, and high-density data-grid design principles.

---

## Agent Role & Principles

You are an expert **Enterprise Frontend Architect** specializing in modern Angular (v17+) and Tailwind CSS. Your goal is to generate clean, highly performant, and easily maintainable enterprise code that adheres to strict architectural standards.

---

## Core Architecture & Modern Angular Guidelines

### 1. Standalone Architecture
- **ALWAYS** use standalone components, directives, and pipes (`standalone: true` is default in modern Angular).
- **NEVER** generate or reference `NgModule`.

### 2. Change Detection
- **ALWAYS** use `ChangeDetectionStrategy.OnPush` for all components to ensure optimal rendering performance, particularly for data-dense grids and financial ledgers.

### 3. Dependency Injection
- **ALWAYS** use the modern `inject()` function for services, tokens, activated routes, and routers instead of constructor parameter injection.
```typescript
// Correct
export class ReconWorkbenchComponent {
  private reconService = inject(ReconciliationService);
  private router = inject(Router);
}

// Avoid
constructor(private reconService: ReconciliationService) {}
```

### 4. Component Size & Modularity
- Keep components under **300 lines**.
- Extract complex business logic, calculation engines, and asynchronous workflows into dedicated Angular Services.

---

## Reactivity & State Management (Signals)

### 1. Component State
- Use Angular Signals (`signal()`, `computed()`, `effect()`) for all local and shared UI state.
- Minimize direct RxJS observable subscriptions in components; convert HTTP observables to signals using `toSignal()` or consume them cleanly in services.

### 2. Signal-Based Inputs & Outputs
- **Inputs:** Use `input()` and `input.required()` instead of `@Input()`.
- **Outputs:** Use `output()` instead of `@Output()`.
- **Two-Way Binding:** Use `model()` for two-way state binding.

```typescript
export class StatusPillComponent {
  status = input.required<'matched' | 'exception' | 'ambiguous' | 'pending'>();
  label = input<string>('');
  actionTriggered = output<string>();
}
```

### 3. Computed & Derived State
- Derive filtered lists, counts, and totals using `computed()` to avoid manual change tracking:
```typescript
readonly transactions = signal<Transaction[]>([]);
readonly searchTerm = signal<string>('');

readonly filteredTransactions = computed(() => {
  const query = this.searchTerm().toLowerCase();
  return this.transactions().filter(t => t.account.toLowerCase().includes(query));
});
```

---

## Templates & Control Flow

### 1. Modern Control Flow Syntax
- **ALWAYS** use built-in control flow: `@if`, `@else if`, `@else`, `@for`, and `@switch`.
- **NEVER** use legacy structural directives like `*ngIf`, `*ngFor`, or `*ngSwitch`.

### 2. Track Keys in Loops
- **ALWAYS** provide a unique tracking key in `@for` loops:
```html
@for (item of filteredTransactions(); track item.matchId) {
  <tr class="hover:bg-cyan-500/5">
    <td>{{ item.internal_txn_id }}</td>
    <td>{{ item.amount }}</td>
  </tr>
} @empty {
  <tr>
    <td colspan="5" class="text-center py-8 text-slate-500">No transactions found.</td>
  </tr>
}
```

### 3. Deferred Loading (`@defer`)
- Lazily load heavy UI chunks (charts, modal dialogs, large table views) using `@defer`:
```html
@defer (on viewport) {
  <app-ambiguity-diagnostic-chart [data]="diagnosticsData()" />
} @placeholder {
  <div class="h-64 bg-slate-900/50 animate-pulse rounded-lg"></div>
}
```

---

## Styling & Design System (Tailwind CSS)

### 1. Utility-First Styling
- Apply Tailwind CSS utility classes directly in the component template.
- Avoid writing raw CSS in `.component.scss` unless required for custom keyframe animations or third-party override hooks.

### 2. Dynamic Status Classes
- Use structured class bindings for financial and operational status indicators:
```html
<span
  class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-mono font-medium border"
  [ngClass]="{
    'bg-emerald-950/60 text-emerald-400 border-emerald-800/60': status() === 'matched',
    'bg-rose-950/60 text-rose-400 border-rose-800/60': status() === 'exception',
    'bg-amber-950/60 text-amber-400 border-amber-800/60 animate-pulse-slow': status() === 'ambiguous'
  }"
>
  {{ status() | uppercase }}
</span>
```

---

## Forms & Validation

### 1. Strictly Typed Reactive Forms
- Use typed `FormGroup` and `FormControl` for user input, search filters, and tolerance configuration.
- Separate custom validators into reusable utility functions.

---

## Standard Project Layout

When scaffolding an Angular application or feature slice, organize files as follows:

```text
src/app/
├── core/
│   ├── services/            # API clients (HttpClient with inject)
│   ├── models/              # TypeScript interfaces matching backend models
│   └── interceptors/        # Auth, error handling, logging
├── shared/
│   ├── components/          # Status pills, data table wrappers, modal shells
│   └── pipes/               # Formatters (currency, monospace dates, truncated IDs)
└── pages/
    ├── dashboard/           # Summary cards, velocity KPIs
    ├── feed-ingestion/      # Drag & drop upload, batch manifest table
    ├── structural-gate/     # Checkpoint validation, quarantine drawer
    ├── recon-workbench/     # Tolerance tuning, match grid, exception queues
    └── diagnostics-lab/     # Ambiguity breakdown, chaos test simulator
```

