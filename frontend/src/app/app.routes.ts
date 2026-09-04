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
    path: 'gate',
    loadComponent: () =>
      import('./pages/structural-gate/structural-gate.component').then((m) => m.StructuralGateComponent),
  },
  {
    path: 'anomalies',
    loadComponent: () =>
      import('./pages/anomaly-queue/anomaly-queue.component').then((m) => m.AnomalyQueueComponent),
  },
  {
    path: 'recon',
    loadComponent: () =>
      import('./pages/recon-workbench/recon-workbench.component').then((m) => m.ReconWorkbenchComponent),
  },
  {
    path: 'estimator',
    loadComponent: () =>
      import('./pages/time-estimator/time-estimator.component').then((m) => m.TimeEstimatorComponent),
  },
  // Backward-compatible redirects
  {
    path: 'feed',
    redirectTo: 'gate',
    pathMatch: 'full',
  },
  {
    path: 'diagnostics',
    redirectTo: 'estimator',
    pathMatch: 'full',
  },
  {
    path: '**',
    redirectTo: 'dashboard',
  },
];
