import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  EventEmitter,
  Input,
  OnChanges,
  OnInit,
  Output,
  SimpleChanges
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import {
  AssetAlert,
  AssetAlertSummary,
  AssignmentRecipient,
  RegistryService,
  ScheduledJobExecution
} from '../../../services/registry.service';

@Component({
  selector: 'app-action-centre',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './action-centre.component.html'
})
export class ActionCentreComponent implements OnInit, OnChanges {
  @Input() companyId = '';
  @Input() canManageAlerts = false;
  @Input() initialSummary: AssetAlertSummary | null = null;

  @Output() navigateTarget = new EventEmitter<AssetAlert>();
  @Output() summaryChange = new EventEmitter<AssetAlertSummary>();
  @Output() alertsChange = new EventEmitter<AssetAlert[]>();
  @Output() successMessage = new EventEmitter<string>();
  @Output() errorMessage = new EventEmitter<string>();

  private lastLoadedCompanyId = '';

  alerts: AssetAlert[] = [];
  alertSummary: AssetAlertSummary | null = null;
  alertsLoading = false;
  alertsSyncing = false;
  alertsError: string | null = null;
  alertStatusFilter = 'open';
  alertSeverityFilter = '';
  alertTypeFilter = '';
  alertSearchQuery = '';

  lastScheduledJob: ScheduledJobExecution | null = null;
  alertAssignees: AssignmentRecipient[] = [];

  activeAlertModal: 'acknowledge' | 'assign' | 'resolve' | 'dismiss' | null = null;
  currentAlert: AssetAlert | null = null;
  alertNotes = '';
  alertAssigneeId = '';
  alertResolutionReason = 'manual_resolution';
  alertActionLoading = false;

  constructor(
    private readonly registry: RegistryService,
    private readonly changeDetector: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    if (this.initialSummary) {
      this.alertSummary = this.initialSummary;
    }
    if (this.companyId) {
      this.loadAlerts();
    }
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['companyId'] && !changes['companyId'].firstChange && this.companyId) {
      if (this.lastLoadedCompanyId !== this.companyId) {
        this.loadAlerts();
      }
    }
  }

  loadAlerts(autoSync = false): void {
    if (!this.companyId) return;
    this.lastLoadedCompanyId = this.companyId;
    this.alertsLoading = true;
    this.alertsError = null;
    this.loadLastAlertJob();
    const filters = {
      status: this.alertStatusFilter || undefined,
      severity: this.alertSeverityFilter || undefined,
      alert_type: this.alertTypeFilter || undefined,
      search: this.alertSearchQuery || undefined,
      auto_sync: autoSync
    };
    forkJoin({
      alerts: this.registry.listAlerts(this.companyId, filters),
      summary: this.registry.getAlertSummary(this.companyId)
    }).subscribe({
      next: ({ alerts, summary }) => {
        this.alerts = alerts;
        this.alertSummary = summary;
        this.alertsLoading = false;
        this.summaryChange.emit(summary);
        this.alertsChange.emit(alerts);
        this.changeDetector.markForCheck();
      },
      error: (err) => {
        this.alertsError = err?.error?.detail || 'Failed to load alerts';
        this.alertsLoading = false;
        this.changeDetector.markForCheck();
      }
    });
  }

  loadLastAlertJob(): void {
    if (!this.companyId) return;
    this.registry.getLastAlertJob(this.companyId).subscribe({
      next: (job) => {
        this.lastScheduledJob = job;
        this.changeDetector.markForCheck();
      },
      error: () => {}
    });
  }

  syncAlertsNow(): void {
    if (!this.companyId || this.alertsSyncing) return;
    this.alertsSyncing = true;
    this.alertsError = null;
    this.registry.syncAlerts(this.companyId).subscribe({
      next: (res) => {
        this.alertsSyncing = false;
        this.successMessage.emit(
          `Alert evaluation complete: ${res.created_count} created, ${res.updated_count} updated, ${res.auto_resolved_count} auto-resolved. Active: ${res.active_count}`
        );
        this.loadAlerts();
        this.changeDetector.markForCheck();
      },
      error: (err) => {
        this.alertsSyncing = false;
        this.alertsError = err?.error?.detail || 'Failed to sync alerts';
        this.changeDetector.markForCheck();
      }
    });
  }

  openAlertModal(modal: 'acknowledge' | 'assign' | 'resolve' | 'dismiss', alert: AssetAlert): void {
    this.activeAlertModal = modal;
    this.currentAlert = alert;
    this.alertNotes = '';
    this.alertAssigneeId = alert.responsible_user_id || '';
    this.alertResolutionReason = 'manual_resolution';
    if (modal === 'assign' && (!this.alertAssignees || !this.alertAssignees.length) && this.companyId) {
      this.registry.assignmentRecipients(this.companyId).subscribe({
        next: (users) => {
          this.alertAssignees = users;
          this.changeDetector.markForCheck();
        }
      });
    }
  }

  closeAlertModal(): void {
    this.activeAlertModal = null;
    this.currentAlert = null;
    this.alertNotes = '';
    this.alertAssigneeId = '';
    this.alertActionLoading = false;
  }

  submitAlertAcknowledge(): void {
    if (!this.companyId || !this.currentAlert) return;
    this.alertActionLoading = true;
    this.registry.acknowledgeAlert(this.companyId, this.currentAlert.id, this.alertNotes).subscribe({
      next: (updated) => {
        this.alertActionLoading = false;
        this.successMessage.emit(`Alert '${updated.title}' acknowledged.`);
        this.closeAlertModal();
        this.loadAlerts();
      },
      error: (err) => {
        this.alertActionLoading = false;
        this.errorMessage.emit(err?.error?.detail || 'Failed to acknowledge alert');
        this.changeDetector.markForCheck();
      }
    });
  }

  submitAlertAssign(): void {
    if (!this.companyId || !this.currentAlert || !this.alertAssigneeId) return;
    this.alertActionLoading = true;
    this.registry.assignAlert(this.companyId, this.currentAlert.id, this.alertAssigneeId).subscribe({
      next: (updated) => {
        this.alertActionLoading = false;
        this.successMessage.emit(`Alert '${updated.title}' assigned.`);
        this.closeAlertModal();
        this.loadAlerts();
      },
      error: (err) => {
        this.alertActionLoading = false;
        this.errorMessage.emit(err?.error?.detail || 'Failed to assign alert');
        this.changeDetector.markForCheck();
      }
    });
  }

  submitAlertResolve(): void {
    if (!this.companyId || !this.currentAlert) return;
    this.alertActionLoading = true;
    this.registry.resolveAlert(this.companyId, this.currentAlert.id, this.alertNotes, this.alertResolutionReason).subscribe({
      next: (updated) => {
        this.alertActionLoading = false;
        this.successMessage.emit(`Alert '${updated.title}' resolved.`);
        this.closeAlertModal();
        this.loadAlerts();
      },
      error: (err) => {
        this.alertActionLoading = false;
        this.errorMessage.emit(err?.error?.detail || 'Failed to resolve alert');
        this.changeDetector.markForCheck();
      }
    });
  }

  submitAlertDismiss(): void {
    if (!this.companyId || !this.currentAlert) return;
    this.alertActionLoading = true;
    this.registry.dismissAlert(this.companyId, this.currentAlert.id, this.alertNotes).subscribe({
      next: (updated) => {
        this.alertActionLoading = false;
        this.successMessage.emit(`Alert '${updated.title}' dismissed.`);
        this.closeAlertModal();
        this.loadAlerts();
      },
      error: (err) => {
        this.alertActionLoading = false;
        this.errorMessage.emit(err?.error?.detail || 'Failed to dismiss alert');
        this.changeDetector.markForCheck();
      }
    });
  }

  goToAlertTarget(alert: AssetAlert): void {
    this.navigateTarget.emit(alert);
  }

  formatAlertType(type: string): string {
    switch (type) {
      case 'warranty_expiry': return 'Warranty Expiry';
      case 'amc_expiry': return 'AMC Expiry';
      case 'maintenance_overdue': return 'Maintenance SLA';
      case 'verification_discrepancy': return 'Physical Discrepancy';
      case 'verification_campaign_due': return 'Campaign Deadline';
      case 'fully_depreciated_in_use': return 'Fully Depreciated In Service';
      case 'approaching_eol': return 'Approaching End of Life';
      case 'purchase_order_overdue': return 'PO Delivery Overdue';
      default: return (type || '').replace(/_/g, ' ');
    }
  }

  formatTimeAgo(dateStr: string | null): string {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    const now = new Date();
    const diffSec = Math.floor((now.getTime() - date.getTime()) / 1000);
    if (diffSec < 60) return 'just now';
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  }
}
