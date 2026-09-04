import { Component, ChangeDetectionStrategy } from '@angular/core';
import { ShellComponent } from './layout/shell/shell.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [ShellComponent],
  template: `<app-shell />`,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class App {}
