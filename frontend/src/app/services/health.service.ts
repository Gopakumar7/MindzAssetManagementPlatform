import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

export interface DatabaseHealthResponse {
  available: boolean;
  message: string;
}

export interface ReadinessResponse {
  status: string;
  database: DatabaseHealthResponse;
}

@Injectable({
  providedIn: 'root'
})
export class HealthService {
  private readonly apiBaseUrl = environment.apiBaseUrl;

  constructor(private readonly http: HttpClient) {}

  getHealth(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>(`${this.apiBaseUrl}/health`);
  }

  getReadiness(): Observable<ReadinessResponse> {
    return this.http.get<ReadinessResponse>(`${this.apiBaseUrl}/health/ready`);
  }
}
