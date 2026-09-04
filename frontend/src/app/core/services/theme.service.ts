import { Injectable, signal, effect } from '@angular/core';

@Injectable({
  providedIn: 'root'
})
export class ThemeService {
  readonly isDark = signal<boolean>(true);

  constructor() {
    const stored = localStorage.getItem('theme');
    const prefersDark = stored ? stored === 'dark' : true;
    this.isDark.set(prefersDark);
    this.applyTheme(prefersDark);

    effect(() => {
      const dark = this.isDark();
      this.applyTheme(dark);
      localStorage.setItem('theme', dark ? 'dark' : 'light');
    });
  }

  toggle(): void {
    this.isDark.update(v => !v);
  }

  private applyTheme(dark: boolean): void {
    const html = document.documentElement;
    if (dark) {
      html.classList.remove('light');
      html.classList.add('dark');
    } else {
      html.classList.remove('dark');
      html.classList.add('light');
    }
  }
}

