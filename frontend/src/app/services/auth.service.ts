import { HttpClient } from '@angular/common/http';
import { Injectable, signal } from '@angular/core';
import { Observable, of, switchMap, tap } from 'rxjs';

export interface Membership {
  company_id: string;
  company_code: string;
  company_name: string;
  role_code: string;
  role_name: string;
  permissions: string[];
}

export interface CurrentUser {
  id: string;
  email: string;
  system_permissions: string[];
  memberships: Membership[];
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  readonly currentUser = signal<CurrentUser | null>(null);

  constructor(private readonly http: HttpClient) {}

  loadCurrentUser(): Observable<CurrentUser> {
    const current = this.currentUser();
    if (current) {
      return of(current);
    }
    return this.http.get<CurrentUser>('/api/v1/auth/me').pipe(
      tap((user) => this.currentUser.set(user))
    );
  }

  login(email: string, password: string): Observable<CurrentUser> {
    return this.http.post('/api/v1/auth/login', { email, password }).pipe(
      switchMap(() => this.http.get<CurrentUser>('/api/v1/auth/me')),
      tap((user) => this.currentUser.set(user))
    );
  }

  logout(): Observable<void> {
    return this.http.post<void>('/api/v1/auth/logout', {}).pipe(
      tap(() => this.currentUser.set(null))
    );
  }

  acceptInvitation(token: string, password: string): Observable<void> {
    return this.http.post<void>('/api/v1/auth/invitations/accept', { token, password });
  }

  permissions(companyId: string): Set<string> {
    const user = this.currentUser();
    const companyPermissions = user?.memberships.find((membership) => membership.company_id === companyId)?.permissions ?? [];
    return new Set([...(user?.system_permissions ?? []), ...companyPermissions]);
  }
}
