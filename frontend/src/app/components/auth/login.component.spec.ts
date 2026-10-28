import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { AuthService } from '../../services/auth.service';
import { LoginComponent } from './login.component';

describe('LoginComponent', () => {
  let fixture: ComponentFixture<LoginComponent>;
  let component: LoginComponent;
  let authServiceSpy: jasmine.SpyObj<AuthService>;
  let router: Router;

  beforeEach(() => {
    authServiceSpy = jasmine.createSpyObj<AuthService>('AuthService', ['login']);

    TestBed.configureTestingModule({
      imports: [LoginComponent],
      providers: [
        provideRouter([]),
        { provide: AuthService, useValue: authServiceSpy },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              queryParamMap: convertToParamMap({ returnUrl: '/dashboard' })
            }
          }
        }
      ]
    });

    router = TestBed.inject(Router);
    spyOn(router, 'navigateByUrl');
    fixture = TestBed.createComponent(LoginComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('submits credentials and navigates on success', () => {
    authServiceSpy.login.and.returnValue(of({
      id: 'u-1',
      email: 'user@example.invalid',
      system_permissions: [],
      memberships: []
    }));

    component.email = 'user@example.invalid';
    component.password = 'password12345';
    component.submit();
    fixture.detectChanges();

    expect(authServiceSpy.login).toHaveBeenCalledWith('user@example.invalid', 'password12345');
    expect(component.submitting).toBeFalse();
    expect(router.navigateByUrl).toHaveBeenCalledWith('/dashboard');
  });

  it('preserves and navigates to pending QR deep-link returnUrl after successful login', () => {
    const route = TestBed.inject(ActivatedRoute);
    (route.snapshot as any).queryParamMap = convertToParamMap({ returnUrl: '/?lookup=MZ-000016' });

    authServiceSpy.login.and.returnValue(of({
      id: 'u-1',
      email: 'user@example.invalid',
      system_permissions: [],
      memberships: []
    }));

    component.email = 'user@example.invalid';
    component.password = 'password12345';
    component.submit();
    fixture.detectChanges();

    expect(router.navigateByUrl).toHaveBeenCalledWith('/?lookup=MZ-000016');
  });

  it('renders error notice when login fails', () => {
    authServiceSpy.login.and.returnValue(
      throwError(() => new HttpErrorResponse({ status: 401 }))
    );

    component.email = 'user@example.invalid';
    component.password = 'wrong-password';
    component.submit();
    fixture.detectChanges();

    expect(component.submitting).toBeFalse();
    expect(component.errorMessage).toBe('Unable to sign in with those credentials.');
    expect(fixture.nativeElement.textContent).toContain('Unable to sign in with those credentials.');
  });
});
