import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { ActionCentreComponent } from './action-centre.component';
import {
  AssetAlert,
  AssetAlertSummary,
  AlertSyncResponse,
  AssignmentRecipient,
  RegistryService,
  ScheduledJobExecution
} from '../../../services/registry.service';

describe('ActionCentreComponent', () => {
  let component: ActionCentreComponent;
  let fixture: ComponentFixture<ActionCentreComponent>;
  let registry: jasmine.SpyObj<RegistryService>;

  const mockAlertSummary: AssetAlertSummary = {
    total_open: 2,
    total_acknowledged: 1,
    total_resolved: 4,
    total_dismissed: 1,
    critical_count: 1,
    warning_count: 2,
    info_count: 0,
    by_type: { warranty_expiry: 2, maintenance_overdue: 1 }
  };

  const mockAlert: AssetAlert = {
    id: 'alert-1',
    company_id: 'company-1',
    alert_type: 'warranty_expiry',
    severity: 'critical',
    status: 'open',
    title: 'Warranty Expiry Alert: ThinkPad X1',
    description: 'Warranty expires in 14 days',
    entity_type: 'asset_service_contract',
    entity_id: 'contract-1',
    entity_reference: 'AST-000001',
    asset_id: 'asset-1',
    due_date: '2026-11-01',
    days_overdue: -14,
    responsible_user_id: null,
    responsible_user_email: null,
    target_route: 'assets',
    acknowledged_at: null,
    acknowledged_by_id: null,
    resolved_at: null,
    resolved_by_id: null,
    resolution_reason: null,
    resolution_notes: null,
    created_at: '2026-10-20T10:00:00Z',
    updated_at: '2026-10-20T10:00:00Z'
  };

  const mockSyncResponse: AlertSyncResponse = {
    synced: true,
    created_count: 1,
    updated_count: 0,
    auto_resolved_count: 0,
    active_count: 3
  };

  const mockJob: ScheduledJobExecution = {
    id: 'job-1',
    job_name: 'scheduled_alert_evaluation',
    status: 'completed',
    started_at: '2026-10-22T08:00:00Z',
    last_heartbeat_at: '2026-10-22T08:00:01Z',
    completed_at: '2026-10-22T08:00:02Z',
    total_companies_processed: 3,
    alerts_created: 1,
    alerts_updated: 0,
    alerts_auto_resolved: 0,
    duration_ms: 2150,
    error_message: null,
    node_id: 'node-test-1',
    created_at: '2026-10-22T08:00:00Z'
  };

  const mockRecipients: AssignmentRecipient[] = [
    { id: 'user-1', email: 'alice@mindzen.com' },
    { id: 'user-2', email: 'bob@mindzen.com' }
  ];

  beforeEach(async () => {
    const spy = jasmine.createSpyObj('RegistryService', [
      'listAlerts',
      'getAlertSummary',
      'getLastAlertJob',
      'syncAlerts',
      'acknowledgeAlert',
      'assignAlert',
      'resolveAlert',
      'dismissAlert',
      'assignmentRecipients'
    ]);

    spy.listAlerts.and.returnValue(of([mockAlert]));
    spy.getAlertSummary.and.returnValue(of(mockAlertSummary));
    spy.getLastAlertJob.and.returnValue(of(mockJob));
    spy.syncAlerts.and.returnValue(of(mockSyncResponse));
    spy.acknowledgeAlert.and.returnValue(of({ ...mockAlert, status: 'acknowledged' }));
    spy.assignAlert.and.returnValue(of({ ...mockAlert, responsible_user_id: 'user-2' }));
    spy.resolveAlert.and.returnValue(of({ ...mockAlert, status: 'resolved' }));
    spy.dismissAlert.and.returnValue(of({ ...mockAlert, status: 'dismissed' }));
    spy.assignmentRecipients.and.returnValue(of(mockRecipients));

    await TestBed.configureTestingModule({
      imports: [ActionCentreComponent],
      providers: [{ provide: RegistryService, useValue: spy }]
    }).compileComponents();

    registry = TestBed.inject(RegistryService) as jasmine.SpyObj<RegistryService>;
    fixture = TestBed.createComponent(ActionCentreComponent);
    component = fixture.componentInstance;
    component.companyId = 'company-1';
    component.canManageAlerts = true;
    fixture.detectChanges();
  });

  it('should create and load initial alerts and summary', () => {
    expect(component).toBeTruthy();
    expect(registry.listAlerts).toHaveBeenCalledWith('company-1', jasmine.objectContaining({ status: 'open' }));
    expect(registry.getAlertSummary).toHaveBeenCalledWith('company-1');
    expect(registry.getLastAlertJob).toHaveBeenCalledWith('company-1');
    expect(component.alerts.length).toBe(1);
    expect(component.alertSummary).toEqual(mockAlertSummary);
    expect(component.lastScheduledJob).toEqual(mockJob);
  });

  it('should emit summaryChange when alert summary is loaded', () => {
    spyOn(component.summaryChange, 'emit');
    component.loadAlerts();
    expect(component.summaryChange.emit).toHaveBeenCalledWith(mockAlertSummary);
  });

  it('should trigger alert synchronization and emit successMessage', () => {
    spyOn(component.successMessage, 'emit');
    component.syncAlertsNow();
    expect(registry.syncAlerts).toHaveBeenCalledWith('company-1');
    expect(component.successMessage.emit).toHaveBeenCalledWith(
      jasmine.stringMatching(/Alert evaluation complete: 1 created/)
    );
  });

  it('should apply filters and reload alerts with selected criteria', () => {
    component.alertStatusFilter = 'acknowledged';
    component.alertSeverityFilter = 'warning';
    component.alertTypeFilter = 'warranty_expiry';
    component.alertSearchQuery = 'AST-000001';

    component.loadAlerts();

    expect(registry.listAlerts).toHaveBeenCalledWith('company-1', {
      status: 'acknowledged',
      severity: 'warning',
      alert_type: 'warranty_expiry',
      search: 'AST-000001',
      auto_sync: false
    });
  });

  it('should open acknowledge modal and submit acknowledgment with notes', () => {
    spyOn(component.successMessage, 'emit');
    component.openAlertModal('acknowledge', mockAlert);
    expect(component.activeAlertModal).toBe('acknowledge');
    expect(component.currentAlert).toBe(mockAlert);

    component.alertNotes = 'Monitoring closely';
    component.submitAlertAcknowledge();

    expect(registry.acknowledgeAlert).toHaveBeenCalledWith('company-1', mockAlert.id, 'Monitoring closely');
    expect(component.activeAlertModal).toBeNull();
    expect(component.successMessage.emit).toHaveBeenCalledWith(jasmine.stringMatching(/acknowledged/));
  });

  it('should open assign modal, load recipients, and submit alert assignment', () => {
    spyOn(component.successMessage, 'emit');
    component.openAlertModal('assign', mockAlert);
    expect(component.activeAlertModal).toBe('assign');
    expect(registry.assignmentRecipients).toHaveBeenCalledWith('company-1');

    component.alertAssigneeId = 'user-2';
    component.submitAlertAssign();

    expect(registry.assignAlert).toHaveBeenCalledWith('company-1', mockAlert.id, 'user-2');
    expect(component.activeAlertModal).toBeNull();
    expect(component.successMessage.emit).toHaveBeenCalledWith(jasmine.stringMatching(/assigned/));
  });

  it('should open resolve modal and submit alert resolution with reason and notes', () => {
    spyOn(component.successMessage, 'emit');
    component.openAlertModal('resolve', mockAlert);
    expect(component.activeAlertModal).toBe('resolve');

    component.alertResolutionReason = 'source_resolved';
    component.alertNotes = 'Renewed contract';
    component.submitAlertResolve();

    expect(registry.resolveAlert).toHaveBeenCalledWith('company-1', mockAlert.id, 'Renewed contract', 'source_resolved');
    expect(component.activeAlertModal).toBeNull();
    expect(component.successMessage.emit).toHaveBeenCalledWith(jasmine.stringMatching(/resolved/));
  });

  it('should open dismiss modal and submit alert dismissal with notes', () => {
    spyOn(component.successMessage, 'emit');
    component.openAlertModal('dismiss', mockAlert);
    expect(component.activeAlertModal).toBe('dismiss');

    component.alertNotes = 'Accepted risk';
    component.submitAlertDismiss();

    expect(registry.dismissAlert).toHaveBeenCalledWith('company-1', mockAlert.id, 'Accepted risk');
    expect(component.activeAlertModal).toBeNull();
    expect(component.successMessage.emit).toHaveBeenCalledWith(jasmine.stringMatching(/dismissed/));
  });

  it('should emit navigateTarget when goToAlertTarget is called', () => {
    spyOn(component.navigateTarget, 'emit');
    component.goToAlertTarget(mockAlert);
    expect(component.navigateTarget.emit).toHaveBeenCalledWith(mockAlert);
  });

  it('should format alert types into user-friendly labels', () => {
    expect(component.formatAlertType('warranty_expiry')).toBe('Warranty Expiry');
    expect(component.formatAlertType('amc_expiry')).toBe('AMC Expiry');
    expect(component.formatAlertType('maintenance_overdue')).toBe('Maintenance SLA');
    expect(component.formatAlertType('verification_discrepancy')).toBe('Physical Discrepancy');
    expect(component.formatAlertType('verification_campaign_due')).toBe('Campaign Deadline');
    expect(component.formatAlertType('fully_depreciated_in_use')).toBe('Fully Depreciated In Service');
    expect(component.formatAlertType('approaching_eol')).toBe('Approaching End of Life');
    expect(component.formatAlertType('purchase_order_overdue')).toBe('PO Delivery Overdue');
    expect(component.formatAlertType('custom_rule')).toBe('custom rule');
  });

  it('should format time ago correctly', () => {
    expect(component.formatTimeAgo(null)).toBe('');
    const now = new Date();
    const twoMinutesAgo = new Date(now.getTime() - 2 * 60 * 1000).toISOString();
    expect(component.formatTimeAgo(twoMinutesAgo)).toBe('2m ago');
    const threeHoursAgo = new Date(now.getTime() - 3 * 3600 * 1000).toISOString();
    expect(component.formatTimeAgo(threeHoursAgo)).toBe('3h ago');
  });

  it('should handle error when alerts fail to load', () => {
    registry.listAlerts.and.returnValue(throwError(() => ({ error: { detail: 'Database error' } })));
    component.loadAlerts();
    expect(component.alertsError).toBe('Database error');
    expect(component.alertsLoading).toBeFalse();
  });
});
