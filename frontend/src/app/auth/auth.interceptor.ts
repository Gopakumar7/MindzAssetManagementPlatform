import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { DOCUMENT } from '@angular/common';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';

import { AuthService } from '../services/auth.service';

function readCookie(document: Document, name: string): string | null {
  const prefix = `${name}=`;
  const cookie = document.cookie.split('; ').find((item) => item.startsWith(prefix));
  return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : null;
}

export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const document = inject(DOCUMENT);
  const router = inject(Router);
  const auth = inject(AuthService);
  const method = request.method.toUpperCase();
  const unsafe = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method);
  const csrfToken = unsafe && request.url.startsWith('/api/v1/')
    ? readCookie(document, 'mindzen_csrf')
    : null;
  const outgoing = csrfToken
    ? request.clone({ setHeaders: { 'X-CSRF-Token': csrfToken } })
    : request;

  return next(outgoing).pipe(
    catchError((error: unknown) => {
      if (
        error instanceof HttpErrorResponse
        && error.status === 401
        && !request.url.endsWith('/auth/login')
      ) {
        auth.currentUser.set(null);
        void router.navigate(['/login']);
      }
      return throwError(() => error);
    })
  );
};
