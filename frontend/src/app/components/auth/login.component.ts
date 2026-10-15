import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-login',
  imports: [FormsModule, RouterLink],
  template: `
    <main class="auth-page">
      <section class="auth-card">
        <p class="eyebrow">MindZen · ALCM / ITAM</p>
        <h1>Sign in</h1>
        <p class="muted">Use your invited account to access assigned company records.</p>
        @if (errorMessage) {
          <div class="notice error" role="alert">{{ errorMessage }}</div>
        }
        <form class="form-grid" (ngSubmit)="submit()">
          <label>Email address<input type="email" name="email" [(ngModel)]="email" required autocomplete="username"></label>
          <label>Password<input type="password" name="password" [(ngModel)]="password" required autocomplete="current-password"></label>
          <button class="primary" type="submit" [disabled]="submitting">Sign in</button>
        </form>
        <p class="muted">Have a company invitation? <a routerLink="/invite">Accept it here</a>.</p>
        <a routerLink="/status">Service status</a>
      </section>
    </main>
  `,
  styles: [`
    .auth-page { min-height: 70vh; display: grid; place-items: center; padding: 2rem 1rem; }
    .auth-card { width: min(100%, 28rem); display: grid; gap: 1rem; padding: 2rem; border: 1px solid #dbe3ee; border-radius: 1rem; background: white; box-shadow: 0 1rem 2.5rem #172b4d12; }
    .auth-card h1, .auth-card p { margin: 0; }
    .auth-card .form-grid { display: grid; gap: 1rem; }
    .auth-card label { display: grid; gap: .35rem; }
    .auth-card input { padding: .7rem; border: 1px solid #cbd5e1; border-radius: .45rem; }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class LoginComponent {
  email = '';
  password = '';
  errorMessage = '';
  submitting = false;

  constructor(
    private readonly auth: AuthService,
    private readonly router: Router,
    private readonly route: ActivatedRoute
  ) {}

  submit(): void {
    this.submitting = true;
    this.errorMessage = '';
    this.auth.login(this.email.trim(), this.password).subscribe({
      next: () => {
        this.submitting = false;
        const returnUrl = this.route.snapshot.queryParamMap.get('returnUrl');
        void this.router.navigateByUrl(returnUrl?.startsWith('/') ? returnUrl : '/');
      },
      error: (error: unknown) => {
        this.submitting = false;
        this.errorMessage = error instanceof HttpErrorResponse && error.status === 429
          ? 'Too many attempts. Please wait before trying again.'
          : 'Unable to sign in with those credentials.';
      }
    });
  }
}
