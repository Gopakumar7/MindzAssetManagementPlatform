import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { AuthService } from '../../services/auth.service';
import { InvitationComponent } from './invitation.component';

describe('InvitationComponent', () => {
  let fixture: ComponentFixture<InvitationComponent>;
  let component: InvitationComponent;
  let authServiceSpy: jasmine.SpyObj<AuthService>;

  beforeEach(() => {
    authServiceSpy = jasmine.createSpyObj<AuthService>('AuthService', ['acceptInvitation']);

    TestBed.configureTestingModule({
      imports: [InvitationComponent],
      providers: [
        provideRouter([]),
        { provide: AuthService, useValue: authServiceSpy },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              queryParamMap: convertToParamMap({ token: 'test-token-123' })
            }
          }
        }
      ]
    });

    fixture = TestBed.createComponent(InvitationComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('initializes with token from route query param', () => {
    expect(component.token).toBe('test-token-123');
    expect(component.accepted).toBeFalse();
  });

  it('renders success notice and hide form upon successful invitation acceptance', () => {
    authServiceSpy.acceptInvitation.and.returnValue(of(undefined));

    component.password = 'valid-password-123';
    component.submit();
    fixture.detectChanges();

    expect(authServiceSpy.acceptInvitation).toHaveBeenCalledWith('test-token-123', 'valid-password-123');
    expect(component.submitting).toBeFalse();
    expect(component.accepted).toBeTrue();
    expect(component.message).toContain('Invitation accepted');
    expect(fixture.nativeElement.textContent).toContain('Invitation accepted. You can now sign in.');
    expect(fixture.nativeElement.textContent).toContain('Continue to sign in');
  });

  it('renders error notice when invitation is invalid or already used (400)', () => {
    authServiceSpy.acceptInvitation.and.returnValue(
      throwError(() => new HttpErrorResponse({ status: 400, error: { detail: 'Invitation already accepted' } }))
    );

    component.password = 'valid-password-123';
    component.submit();
    fixture.detectChanges();

    expect(component.submitting).toBeFalse();
    expect(component.accepted).toBeFalse();
    expect(component.errorMessage).toContain('This invitation is invalid, expired, or has already been used.');
    expect(fixture.nativeElement.textContent).toContain('This invitation is invalid, expired, or has already been used.');
  });
});
