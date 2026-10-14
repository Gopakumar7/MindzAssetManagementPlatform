import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { AppComponent } from './app.component';
import { routes } from './app.routes';

describe('AppComponent', () => {
  let httpTestingController: HttpTestingController;
  let router: Router;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [
        provideHttpClient(withXhr()),
        provideHttpClientTesting(),
        provideRouter(routes)
      ]
    });
    httpTestingController = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
  });

  afterEach(() => {
    httpTestingController.verify();
  });

  it('creates the router-based application root', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('router-outlet')).toBeTruthy();
  });

  it('loads the status page through the application router', async () => {
    const fixture = TestBed.createComponent(AppComponent);
    await router.navigateByUrl('/status');
    fixture.detectChanges();

    const healthRequest = httpTestingController.expectOne('/api/v1/health');
    expect(healthRequest.request.method).toBe('GET');
    healthRequest.flush({ status: 'ok', service: 'mindzen-alcm', version: '0.1.0' });
    fixture.detectChanges();

    const readinessRequest = httpTestingController.expectOne('/api/v1/health/ready');
    expect(readinessRequest.request.method).toBe('GET');
    readinessRequest.flush({
      status: 'ready',
      database: { available: true, message: 'database connection is healthy' }
    });
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('h1')?.textContent).toContain('System status');
    expect(fixture.nativeElement.textContent).toContain('Database readiness');
    expect(fixture.nativeElement.textContent).toContain('ready');
  });
});
