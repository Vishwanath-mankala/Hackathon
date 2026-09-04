import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    redirectTo: 'dashboard',
    pathMatch: 'full',
  },
  {
    path: 'dashboard',
    loadComponent: () =>
      import('./pages/dashboard/dashboard.component').then((m) => m.DashboardComponent),
  },
  {
    path: 'feed',
    loadComponent: () =>
      import('./pages/feed-ingestion/feed-ingestion.component').then((m) => m.FeedIngestionComponent),
  },
  {
    path: 'gate',
    loadComponent: () =>
      import('./pages/structural-gate/structural-gate.component').then((m) => m.StructuralGateComponent),
  },
  {
    path: 'recon',
    loadComponent: () =>
      import('./pages/recon-workbench/recon-workbench.component').then((m) => m.ReconWorkbenchComponent),
  },
  {
    path: 'diagnostics',
    loadComponent: () =>
      import('./pages/diagnostics-lab/diagnostics-lab.component').then((m) => m.DiagnosticsLabComponent),
  },
  {
    path: '**',
    redirectTo: 'dashboard',
  },
];
