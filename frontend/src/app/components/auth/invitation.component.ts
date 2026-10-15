import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-invitation',
  imports: [FormsModule, RouterLink],
  template: `
    <main class="auth-page">
      <section class="auth-card">
        <p class="eyebrow">MindZen · ALCM / ITAM</p>
        <h1>Accept invitation</h1>
        <p class="muted">Choose a password to activate your account and company membership.</p>
        @if (message) {
          <div class="notice success" role="status">{{ message }}</div>
        }
        @if (errorMessage) {
          <div class="notice error" role="alert">{{ errorMessage }}</div>
        }
        @if (!accepted) {
          <form class="form-grid" (ngSubmit)="submit()">
            <label>Invitation token<input name="token" [(ngModel)]="token" required autocomplete="one-time-code"></label>
            <label>Password (12 characters minimum)<input type="password" name="password" [(ngModel)]="password" required minlength="12" autocomplete="new-password"></label>
            <button class="primary" type="submit" [disabled]="submitting || !token">Accept invitation</button>
          </form>
        } @else {
          <a routerLink="/login">Continue to sign in</a>
        }
      </section>
    </main>
  `,
  styles: [`
    .auth-page { min-height: 70vh; display: grid; place-items: center; padding: 2rem 1rem; }
    .auth-card { width: min(100%, 30rem); display: grid; gap: 1rem; padding: 2rem; border: 1px solid #dbe3ee; border-radius: 1rem; background: white; }
    .auth-card h1, .auth-card p { margin: 0; }
    .auth-card .form-grid { display: grid; gap: 1rem; }
    .auth-card label { display: grid; gap: .35rem; }
    .auth-card input { padding: .7rem; border: 1px solid #cbd5e1; border-radius: .45rem; }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class InvitationComponent {
  token: string;
  password = '';
  errorMessage = '';
  message = '';
  accepted = false;
  submitting = false;

  constructor(authRoute: ActivatedRoute, private readonly auth: AuthService) {
    this.token = authRoute.snapshot.queryParamMap.get('token') ?? '';
  }

  submit(): void {
    this.submitting = true;
    this.errorMessage = '';
    this.auth.acceptInvitation(this.token.trim(), this.password).subscribe({
      next: () => {
        this.submitting = false;
        this.accepted = true;
        this.message = 'Invitation accepted. You can now sign in.';
        this.password = '';
      },
      error: (error: unknown) => {
        this.submitting = false;
        this.errorMessage = error instanceof HttpErrorResponse && error.status === 400
          ? 'This invitation is invalid, expired, or has already been used.'
          : 'The invitation could not be accepted. Please try again.';
      }
    });
  }
}
