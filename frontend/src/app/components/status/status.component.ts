import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { finalize } from 'rxjs';

import { HealthResponse, HealthService, ReadinessResponse } from '../../services/health.service';

@Component({
  selector: 'app-status',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './status.component.html',
  styleUrl: './status.component.scss'
})
export class StatusComponent implements OnInit {
  health?: HealthResponse;
  readiness?: ReadinessResponse;
  loading = true;
  errorMessage = '';

  constructor(private readonly healthService: HealthService) {}

  ngOnInit(): void {
    this.healthService
      .getHealth()
      .pipe(
        finalize(() => {
          this.loading = false;
        })
      )
      .subscribe({
        next: (response) => {
          this.health = response;
          this.loadReadiness();
        },
        error: (error) => {
          this.errorMessage = error?.error?.detail ?? 'Unable to reach the backend service.';
        }
      });
  }

  private loadReadiness(): void {
    this.healthService.getReadiness().subscribe({
      next: (response) => {
        this.readiness = response;
      },
      error: (error) => {
        this.readiness = {
          status: 'not_ready',
          database: {
            available: false,
            message: error?.error?.detail?.database?.message ?? error?.message ?? 'Database is unavailable.'
          }
        };
      }
    });
  }
}
