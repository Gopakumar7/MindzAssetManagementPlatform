import { ChangeDetectionStrategy, Component } from '@angular/core';
import { Router, RouterLink, RouterOutlet } from '@angular/router';

import { AuthService } from './services/auth.service';

@Component({
  selector: 'app-root',
  imports: [RouterLink, RouterOutlet],
  template: `
    <header class="global-header">
      <a class="brand" routerLink="/">MindZen ALCM / ITAM</a>
      <nav aria-label="Application">
        <a routerLink="/status">Status</a>
        @if (auth.currentUser(); as user) {
          <span>{{ user.email }}</span>
          <button type="button" (click)="logout()">Sign out</button>
        } @else {
          <a routerLink="/login">Sign in</a>
        }
      </nav>
    </header>
    <router-outlet />
  `,
  styles: [`
    .global-header { min-height: 3.75rem; display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 0 1.5rem; border-bottom: 1px solid #e2e8f0; background: #fff; }
    .global-header nav { display: flex; align-items: center; gap: 1rem; }
    .global-header a { color: #24446b; text-decoration: none; font-weight: 600; }
    .global-header button { border: 0; background: transparent; color: #24446b; cursor: pointer; font: inherit; }
    .brand { letter-spacing: .02em; }
  `],
  changeDetection: ChangeDetectionStrategy.Eager
})
export class AppComponent {
  constructor(readonly auth: AuthService, private readonly router: Router) {}

  logout(): void {
    this.auth.logout().subscribe({
      next: () => void this.router.navigate(['/login']),
      error: () => void this.router.navigate(['/login'])
    });
  }
}
