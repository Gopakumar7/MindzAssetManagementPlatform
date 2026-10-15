import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { authInterceptor } from '../auth/auth.interceptor';
import { AuthService, CurrentUser } from './auth.service';

describe('AuthService', () => {
  let auth: AuthService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
        provideRouter([])
      ]
    });
    auth = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    document.cookie = 'mindzen_csrf=; Max-Age=0; path=/';
  });

  it('loads the current user after login and exposes the assigned permissions', () => {
    const expectedUser: CurrentUser = {
      id: 'user-1',
      email: 'user@example.invalid',
      system_permissions: [],
      memberships: [{
        company_id: 'company-1',
        company_code: 'ACME',
        company_name: 'Acme',
        role_code: 'asset_manager',
        role_name: 'Asset Manager',
        permissions: ['asset.read', 'asset.create']
      }]
    };
    let received: CurrentUser | undefined;
    auth.login('user@example.invalid', 'long-enough-password').subscribe((user) => {
      received = user;
    });

    http.expectOne('/api/v1/auth/login').flush({ status: 'authenticated' });
    http.expectOne('/api/v1/auth/me').flush(expectedUser);

    expect(received).toEqual(expectedUser);
    expect(auth.currentUser()).toEqual(expectedUser);
    expect(auth.permissions('company-1')).toEqual(new Set(['asset.read', 'asset.create']));
    expect(auth.permissions('another-company').size).toBe(0);
  });

  it('sends the CSRF cookie value as a header for unsafe API requests', () => {
    document.cookie = 'mindzen_csrf=test-csrf-value; path=/';
    auth.logout().subscribe();

    const request = http.expectOne('/api/v1/auth/logout');
    expect(request.request.headers.get('X-CSRF-Token')).toBe('test-csrf-value');
    request.flush(null);
  });
});
