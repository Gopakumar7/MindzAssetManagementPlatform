import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { BehaviorSubject, of, throwError } from 'rxjs';

import { AuthService, CurrentUser } from '../../services/auth.service';
import {
  Asset,
  AssetAssignment,
  Company,
  CompanyRole,
  GoodsReceipt,
  MaintenanceRequest,
  PurchaseOrder,
  ProcurementSupplier,
  RegistryService,
  VerificationCampaign,
  VerificationExpectedAsset,
  VerificationObservation,
  VerificationDiscrepancy,
  VerificationUnregisteredAsset,
  VerificationDashboardSummary,
  VerificationCampaignReportItem,
  VerificationDiscrepancyReportItem,
  AssetFinancial,
  DepreciationScheduleItem,
  AssetDepreciationEntry,
  AssetDisposal,
  BatchDepreciationResult,
  AssetDepreciationReportItem,
  AssetDisposalReportItem,
  FinancialDashboardMetric,
  AssetAlert,
  AssetAlertSummary,
  AlertSyncResponse,
  InAppNotification,
  NotificationUnreadCount,
  ScheduledJobExecution
} from '../../services/registry.service';

import { RegistryComponent, serializeCsvCell } from './registry.component';

const defaultAlertSummary: AssetAlertSummary = {
  total_open: 0,
  total_acknowledged: 0,
  total_resolved: 0,
  total_dismissed: 0,
  critical_count: 0,
  warning_count: 0,
  info_count: 0,
  by_type: {}
};

const defaultAlertSyncResponse: AlertSyncResponse = {
  synced: true,
  created_count: 0,
  updated_count: 0,
  auto_resolved_count: 0,
  active_count: 0
};

describe('RegistryComponent user access navigation', () => {
  let fixture: ComponentFixture<RegistryComponent>;
  let user: CurrentUser;
  let permissions: Set<string>;
  let registry: jasmine.SpyObj<RegistryService>;

  const company: Company = {
    id: 'company-1',
    code: 'ACME',
    name: 'Acme',
    is_active: true
  };
  const roles: CompanyRole[] = [
    { code: 'read_only_user', name: 'Read-only User', scope: 'company', permissions: ['company.read', 'asset.read'] },
    { code: 'company_administrator', name: 'Company Administrator', scope: 'company', permissions: ['company.members.manage', 'asset.read'] },
    { code: 'ungrantable', name: 'Unassignable', scope: 'company', permissions: ['organization.manage'] }
  ];

  beforeEach(() => {
    user = {
      id: 'admin-1',
      email: 'admin@example.invalid',
      system_permissions: [],
      memberships: []
    };
    permissions = new Set(['company.read', 'company.members.manage', 'asset.read', 'asset.assignment.manage', 'dashboard.read', 'alerts.read', 'alerts.manage']);
    registry = jasmine.createSpyObj<RegistryService>('RegistryService', [
      'companies',
      'listMaster',
      'listNumberRules',
      'companyMembers',
      'companyRoles',
      'listAssets',
      'downloadAssetImportTemplate',
      'previewAssetImport',
      'confirmAssetImport',
      'getAsset',
      'lookupAsset',
      'usages',
      'history',
      'assignments',
      'assignmentRecipients',
      'createAssignment',
      'recordHandover',
      'returnAssignment',
      'transferAssignment',
      'listLocations',
      'suppliers',
      'purchaseOrders',
      'getPurchaseOrder',
      'goodsReceipts',
      'createSupplier',
      'createPurchaseOrder',
      'updatePurchaseOrder',
      'receiveGoods',
      'serviceContracts',
      'createServiceContract',
      'cancelServiceContract',
      'maintenanceUsers',
      'maintenanceRequests',
      'createMaintenanceRequest',
      'updateMaintenanceRequest',
      'dashboard',
      'reportAssetRegister',
      'reportAssetAllocation',
      'reportWarrantyExpiry',
      'reportMaintenance',
      'reportProcurement',
      'listVerificationCampaigns',
      'getVerificationCampaign',
      'createVerificationCampaign',
      'updateVerificationCampaign',
      'transitionVerificationCampaignStatus',
      'getVerificationExpectedAssets',
      'recordVerificationObservation',
      'getVerificationDiscrepancies',
      'resolveVerificationDiscrepancy',
      'recordUnregisteredAsset',
      'getUnregisteredAssets',
      'registerUnregisteredAsset',
      'getVerificationDashboard',
      'reportVerificationCampaigns',
      'reportVerificationDiscrepancies',
      'getAssetFinancial',
      'configureAssetFinancial',
      'editAssetFinancial',
      'adjustAssetFinancial',
      'getDepreciationSchedule',
      'postDepreciation',
      'listDepreciationEntries',
      'postBatchDepreciation',
      'disposeAsset',
      'getAssetDisposal',
      'reportAssetDepreciation',
      'reportAssetDisposals',
      'getFinancialDashboard',
      'listAlerts',
      'getAlertSummary',
      'syncAlerts',
      'acknowledgeAlert',
      'assignAlert',
      'resolveAlert',
      'dismissAlert',
      'getLastAlertJob',
      'getNotifications',
      'getUnreadNotificationCount',
      'markNotificationRead',
      'markAllNotificationsRead'
    ]);

    registry.getLastAlertJob.and.returnValue(of(null));
    registry.getNotifications.and.returnValue(of([]));
    registry.getUnreadNotificationCount.and.returnValue(of({ unread_count: 0 }));
    registry.markNotificationRead.and.returnValue(of({} as any));
    registry.markAllNotificationsRead.and.returnValue(of({ unread_count: 0 }));

    registry.companies.and.returnValue(of([company]));
    registry.listMaster.and.returnValue(of([]));
    registry.listNumberRules.and.returnValue(of([]));
    registry.companyMembers.and.returnValue(of([]));
    registry.companyRoles.and.returnValue(of(roles));
    registry.listAssets.and.returnValue(of({ items: [], total: 0, page: 1, page_size: 15 }));
    registry.getAsset.and.returnValue(of(testAsset));
    registry.lookupAsset.and.returnValue(of(testAsset));
    registry.usages.and.returnValue(of([]));
    registry.history.and.returnValue(of([]));
    registry.assignments.and.returnValue(of([]));
    registry.assignmentRecipients.and.returnValue(of([{ id: 'recipient-1', email: 'person@example.invalid' }]));
    registry.listLocations.and.returnValue(of([]));
    registry.suppliers.and.returnValue(of([]));
    registry.purchaseOrders.and.returnValue(of([]));
    registry.getPurchaseOrder.and.returnValue(of({} as any));
    registry.goodsReceipts.and.returnValue(of([]));
    registry.createSupplier.and.returnValue(of({} as any));
    registry.createPurchaseOrder.and.returnValue(of({} as any));
    registry.updatePurchaseOrder.and.returnValue(of({} as any));
    registry.serviceContracts.and.returnValue(of([]));
    registry.maintenanceUsers.and.returnValue(of([]));
    registry.maintenanceRequests.and.returnValue(of([]));
    registry.dashboard.and.returnValue(of({
      total_assets: 0,
      assets_by_status: {},
      assets_by_category: [],
      assets_by_site: [],
      assets_by_department: [],
      expiring_contracts_count: 0,
      expiring_contracts: [],
      maintenance_summary: { open: 0, in_progress: 0, resolved: 0, closed: 0, total_open_and_in_progress: 0 },
      procurement_summary: { total_purchase_orders: 0, orders_by_status: {}, total_goods_receipts: 0, total_items_received: 0, total_items_rejected: 0 },
      recent_activity: []
    }));
    registry.reportAssetRegister.and.returnValue(of([]));
    registry.reportAssetAllocation.and.returnValue(of([]));
    registry.reportWarrantyExpiry.and.returnValue(of([]));
    registry.reportMaintenance.and.returnValue(of([]));
    registry.reportProcurement.and.returnValue(of([]));
    registry.listVerificationCampaigns.and.returnValue(of([testCampaign]));
    registry.getVerificationCampaign.and.returnValue(of(testCampaign));
    registry.createVerificationCampaign.and.returnValue(of(testCampaign));
    registry.updateVerificationCampaign.and.returnValue(of(testCampaign));
    registry.transitionVerificationCampaignStatus.and.returnValue(of(testCampaign));
    registry.getVerificationExpectedAssets.and.returnValue(of([testExpectedAsset]));
    registry.recordVerificationObservation.and.returnValue(of(testObservation));
    registry.getVerificationDiscrepancies.and.returnValue(of([testDiscrepancy]));
    registry.resolveVerificationDiscrepancy.and.returnValue(of(testDiscrepancy));
    registry.recordUnregisteredAsset.and.returnValue(of(testUnregisteredAsset));
    registry.getUnregisteredAssets.and.returnValue(of([testUnregisteredAsset]));
    registry.registerUnregisteredAsset.and.returnValue(of(testUnregisteredAsset));
    registry.getVerificationDashboard.and.returnValue(of(testDashboardSummary));
    registry.reportVerificationCampaigns.and.returnValue(of([]));
    registry.reportVerificationDiscrepancies.and.returnValue(of([]));
    registry.getAssetFinancial.and.returnValue(of(undefined as any));
    registry.configureAssetFinancial.and.returnValue(of({} as any));
    registry.editAssetFinancial.and.returnValue(of({} as any));
    registry.adjustAssetFinancial.and.returnValue(of({} as any));
    registry.getDepreciationSchedule.and.returnValue(of([]));
    registry.postDepreciation.and.returnValue(of({} as any));
    registry.listDepreciationEntries.and.returnValue(of([]));
    registry.postBatchDepreciation.and.returnValue(of({ period: '2026-10', processed_count: 0, posted_count: 0, skipped_count: 0, total_depreciation_posted: 0, posted_asset_ids: [], skipped: [] }));
    registry.disposeAsset.and.returnValue(of({} as any));
    registry.getAssetDisposal.and.returnValue(of({} as any));
    registry.reportAssetDepreciation.and.returnValue(of([]));
    registry.reportAssetDisposals.and.returnValue(of([]));
    registry.getFinancialDashboard.and.returnValue(of({
      total_capitalised_cost: 0,
      total_accumulated_depreciation: 0,
      total_net_book_value: 0,
      approaching_eol_count: 0,
      fully_depreciated_active_count: 0,
      disposed_count: 0,
      total_disposal_proceeds: 0,
      total_disposal_gain_loss: 0
    }));

    registry.listAlerts.and.returnValue(of([]));
    registry.getAlertSummary.and.returnValue(of(defaultAlertSummary));
    registry.syncAlerts.and.returnValue(of(defaultAlertSyncResponse));
    registry.acknowledgeAlert.and.returnValue(of({} as any));
    registry.assignAlert.and.returnValue(of({} as any));
    registry.resolveAlert.and.returnValue(of({} as any));
    registry.dismissAlert.and.returnValue(of({} as any));

    TestBed.configureTestingModule({
      imports: [RegistryComponent],
      providers: [
        provideHttpClient(),
        provideRouter([]),
        { provide: RegistryService, useValue: registry },
        {
          provide: AuthService,
          useValue: {
            currentUser: signal(user),
            permissions: () => new Set(permissions)
          }
        }
      ]
    });
    fixture = TestBed.createComponent(RegistryComponent);
    fixture.detectChanges();
  });

  it('shows a dedicated Users & Access section to an authorized company administrator', () => {
    const button = Array.from(fixture.nativeElement.querySelectorAll('nav button') as NodeListOf<HTMLButtonElement>)
      .find((item) => item.textContent?.trim() === 'Users & Access');
    expect(button).toBeTruthy();
    button?.click();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('h2')?.textContent).toContain('Users & Access');
    expect(fixture.nativeElement.textContent).toContain('Invite a user');
    const roleOptions = Array.from(fixture.nativeElement.querySelectorAll('select[name="inviteRole"] option') as NodeListOf<HTMLOptionElement>)
      .map((option) => option.value);
    expect(roleOptions).toEqual(['read_only_user', 'company_administrator']);
  });

  it('loads the company-scoped procurement view only for users with read permission', () => {
    permissions = new Set(['company.read', 'asset.read', 'procurement.read']);
    fixture.detectChanges();
    const button = Array.from(fixture.nativeElement.querySelectorAll('nav button') as NodeListOf<HTMLButtonElement>)
      .find((item) => item.textContent?.trim() === 'Procurement');
    expect(button).toBeTruthy();
    button?.click();
    fixture.detectChanges();

    expect(registry.suppliers).toHaveBeenCalledWith(company.id);
    expect(registry.purchaseOrders).toHaveBeenCalledWith(company.id);
    expect(registry.goodsReceipts).toHaveBeenCalledWith(company.id);
    expect(fixture.nativeElement.textContent).toContain('Purchase orders');
    expect(fixture.nativeElement.textContent).not.toContain('Add supplier');

    permissions = new Set(['company.read', 'asset.read']);
    fixture.detectChanges();
    const labels = Array.from(fixture.nativeElement.querySelectorAll('nav button') as NodeListOf<HTMLButtonElement>)
      .map((item) => item.textContent?.trim());
    expect(labels).not.toContain('Procurement');
  });

  it('creates a supplier through the typed procurement API and reports success', () => {
    permissions = new Set(['company.read', 'asset.read', 'procurement.read', 'procurement.manage']);
    const supplier: ProcurementSupplier = {
      id: 'supplier-1',
      company_id: company.id,
      code: 'SUP-1',
      name: 'Demo supplier',
      email: null,
      phone: null,
      notes: null,
      is_active: true,
      created_at: '2026-10-16T00:00:00Z'
    };
    registry.createSupplier.and.returnValue(of(supplier));
    fixture.componentInstance.supplierForm.code = 'SUP-1';
    fixture.componentInstance.supplierForm.name = 'Demo supplier';
    fixture.componentInstance.createSupplier();
    fixture.detectChanges();

    expect(registry.createSupplier).toHaveBeenCalledWith(company.id, jasmine.objectContaining({
      code: 'SUP-1',
      name: 'Demo supplier'
    }));
    expect(fixture.componentInstance.suppliers).toContain(supplier);
    expect(fixture.nativeElement.textContent).toContain('Supplier Demo supplier created.');
  });

  it('records a goods receipt and reports assets registered by the backend', () => {
    permissions = new Set(['company.read', 'asset.read', 'procurement.read', 'procurement.manage']);
    spyOn(window, 'confirm').and.returnValue(true);
    const order: PurchaseOrder = {
      id: 'order-1',
      company_id: company.id,
      supplier_id: 'supplier-1',
      order_number: 'PO-1',
      status: 'open',
      ordered_date: '2026-10-16',
      expected_date: null,
      notes: null,
      created_at: '2026-10-16T00:00:00Z',
      lines: [{
        id: 'line-1',
        company_id: company.id,
        purchase_order_id: 'order-1',
        category_id: 'category-1',
        description: 'Demo laptop',
        quantity_ordered: 1,
        unit_cost: '1250.00'
      }]
    };
    const receipt: GoodsReceipt = {
      id: 'receipt-1',
      company_id: company.id,
      purchase_order_id: order.id,
      receipt_number: 'GRN-1',
      received_date: '2026-10-16',
      delivery_reference: null,
      notes: null,
      created_at: '2026-10-16T00:00:00Z',
      lines: [{
        id: 'receipt-line-1',
        purchase_order_line_id: 'line-1',
        quantity_received: 1,
        quantity_rejected: 0,
        discrepancy_notes: null,
        assets: [{
          id: 'asset-received-1',
          asset_number: 'AST-000001',
          serial_number: 'SERIAL-1',
          status: 'in_stock'
        }]
      }]
    };
    fixture.componentInstance.purchaseOrders = [order];
    fixture.componentInstance.goodsReceiptForm.purchase_order_id = order.id;
    fixture.componentInstance.goodsReceiptForm.purchase_order_line_id = 'line-1';
    fixture.componentInstance.goodsReceiptForm.receipt_number = 'GRN-1';
    registry.receiveGoods.and.returnValue(of(receipt));
    fixture.componentInstance.createGoodsReceipt();
    fixture.detectChanges();

    expect(registry.receiveGoods).toHaveBeenCalledWith(company.id, order.id, jasmine.objectContaining({
      receipt_number: 'GRN-1',
      lines: [jasmine.objectContaining({
        purchase_order_line_id: 'line-1',
        quantity_received: 1
      })]
    }));
    expect(fixture.nativeElement.textContent).toContain('1 asset(s) registered.');
    expect(fixture.componentInstance.purchaseOrders[0].status).toBe('received');
  });

  it('surfaces procurement API errors without reporting a successful write', () => {
    permissions = new Set(['company.read', 'asset.read', 'procurement.read', 'procurement.manage']);
    registry.createSupplier.and.returnValue(throwError(() => ({
      error: { detail: 'Supplier code already exists' }
    })));
    fixture.componentInstance.supplierForm.code = 'DUP';
    fixture.componentInstance.supplierForm.name = 'Duplicate supplier';
    fixture.componentInstance.createSupplier();
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Supplier code already exists');
    expect(fixture.componentInstance.suppliers).toEqual([]);
  });

  it('validates required fields and dates before dispatching createPurchaseOrder', () => {
    permissions = new Set(['company.read', 'asset.read', 'procurement.read', 'procurement.manage']);
    const component = fixture.componentInstance;

    // 0a. No suppliers registered
    component.suppliers = [];
    component.createPurchaseOrder();
    expect(component.errorMessage).toBe('Please register at least one supplier before creating a purchase order.');
    expect(registry.createPurchaseOrder).not.toHaveBeenCalled();

    // 0b. No categories registered
    component.suppliers = [{ id: 'sup-1', company_id: company.id, code: 'SUP1', name: 'Supplier 1', is_active: true, email: null, phone: null, notes: null, created_at: '' }];
    component.categories = [];
    component.createPurchaseOrder();
    expect(component.errorMessage).toBe('Please create at least one asset category before creating a purchase order.');
    expect(registry.createPurchaseOrder).not.toHaveBeenCalled();

    // Setup active category
    component.categories = [{ id: 'cat-1', company_id: company.id, code: 'CAT1', name: 'Laptops', is_active: true }];

    // 1. Missing supplier selection
    component.purchaseOrderForm.supplier_id = '';
    component.createPurchaseOrder();
    expect(component.errorMessage).toBe('Please choose a supplier.');
    expect(registry.createPurchaseOrder).not.toHaveBeenCalled();

    // 2. Missing order number
    component.purchaseOrderForm.supplier_id = 'sup-1';
    component.purchaseOrderForm.order_number = '   ';
    component.createPurchaseOrder();
    expect(component.errorMessage).toBe('Please enter an order number.');
    expect(registry.createPurchaseOrder).not.toHaveBeenCalled();

    // 3. Expected date before ordered date
    component.purchaseOrderForm.order_number = 'PO-001';
    component.purchaseOrderForm.ordered_date = '2026-10-15';
    component.purchaseOrderForm.expected_date = '2026-10-10';
    component.createPurchaseOrder();
    expect(component.errorMessage).toBe('Expected date must be on or after the ordered date.');
    expect(registry.createPurchaseOrder).not.toHaveBeenCalled();

    // 4. Missing category
    component.purchaseOrderForm.expected_date = '2026-10-20';
    component.purchaseOrderForm.category_id = '';
    component.createPurchaseOrder();
    expect(component.errorMessage).toBe('Please choose an asset category for the item.');
    expect(registry.createPurchaseOrder).not.toHaveBeenCalled();

    // 5. Missing description
    component.purchaseOrderForm.category_id = 'cat-1';
    component.purchaseOrderForm.description = '   ';
    component.createPurchaseOrder();
    expect(component.errorMessage).toBe('Please enter an item description.');
    expect(registry.createPurchaseOrder).not.toHaveBeenCalled();

    // 6. Zero or negative quantity
    component.purchaseOrderForm.description = 'Laptops';
    component.purchaseOrderForm.quantity_ordered = 0;
    component.createPurchaseOrder();
    expect(component.errorMessage).toBe('Quantity ordered must be greater than zero.');
    expect(registry.createPurchaseOrder).not.toHaveBeenCalled();

    // 7. Negative unit cost
    component.purchaseOrderForm.quantity_ordered = 5;
    component.purchaseOrderForm.unit_cost = -10;
    component.createPurchaseOrder();
    expect(component.errorMessage).toBe('Unit cost must be zero or a positive amount.');
    expect(registry.createPurchaseOrder).not.toHaveBeenCalled();
  });

  it('parses array-based FastAPI 422 validation errors into readable error message', () => {
    permissions = new Set(['company.read', 'asset.read', 'procurement.read', 'procurement.manage']);
    const component = fixture.componentInstance;
    component.suppliers = [{ id: 'sup-1', company_id: company.id, code: 'SUP1', name: 'Supplier 1', is_active: true, email: null, phone: null, notes: null, created_at: '' }];
    component.categories = [{ id: 'cat-1', company_id: company.id, code: 'CAT1', name: 'Laptops', is_active: true }];
    component.purchaseOrderForm = {
      supplier_id: 'sup-1',
      order_number: 'PO-001',
      ordered_date: '2026-10-15',
      expected_date: '2026-10-20',
      notes: '',
      category_id: 'cat-1',
      description: 'Laptops',
      quantity_ordered: 5,
      unit_cost: 1000
    };

    registry.createPurchaseOrder.and.returnValue(throwError(() => ({
      error: {
        detail: [
          { loc: ['body', 'supplier_id'], msg: 'Input should be a valid UUID, invalid length 5', type: 'uuid_parsing' },
          { loc: ['body', 'lines', 0, 'category_id'], msg: 'Input should be a valid UUID, invalid length 5', type: 'uuid_parsing' }
        ]
      }
    })));

    component.createPurchaseOrder();
    expect(component.errorMessage).toContain('supplier_id: Input should be a valid UUID');
    expect(component.errorMessage).toContain('lines -> 0 -> category_id: Input should be a valid UUID');
  });

  it('hides user management from users without the company membership permission', () => {
    permissions = new Set(['company.read', 'asset.read']);
    fixture.detectChanges();

    const labels = Array.from(fixture.nativeElement.querySelectorAll('nav button') as NodeListOf<HTMLButtonElement>)
      .map((button) => button.textContent?.trim());
    expect(labels).not.toContain('Users & Access');
    expect(fixture.nativeElement.textContent).not.toContain('Invite a user');
  });

  it('lets a system administrator manage users in a selected company without a company membership', () => {
    user.system_permissions = ['company.read', 'company.members.manage', 'system.companies.manage'];
    permissions = new Set(user.system_permissions);
    fixture.detectChanges();

    const labels = Array.from(fixture.nativeElement.querySelectorAll('nav button') as NodeListOf<HTMLButtonElement>)
      .map((button) => button.textContent?.trim());
    expect(labels).toContain('Users & Access');
    expect(user.memberships).toEqual([]);
  });

  it('shows the assignment form and sends a valid assignment through the API client', () => {
    spyOn(window, 'confirm').and.returnValue(true);
    const created: AssetAssignment = {
      ...testAssignment,
      id: 'assignment-1',
      company_id: company.id,
      asset_id: testAsset.id,
      recipient_id: 'recipient-1',
      recipient_email: 'person@example.invalid',
      status: 'active'
    };
    registry.createAssignment.and.returnValue(of(created));
    registry.assignments.and.returnValue(of([]));
    registry.createAssignment.and.callFake(() => {
      registry.assignments.and.returnValue(of([created]));
      registry.getAsset.and.returnValue(of({ ...testAsset, status: 'assigned' }));
      return of(created);
    });

    fixture.componentInstance.openAsset(testAsset);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Assign this in-stock asset');
    fixture.componentInstance.assignmentForm.recipient_id = 'recipient-1';
    fixture.componentInstance.assignmentForm.effective_date = '2026-10-15';
    fixture.componentInstance.assignAsset();
    fixture.detectChanges();

    expect(registry.createAssignment).toHaveBeenCalledWith(company.id, testAsset.id, jasmine.objectContaining({
      recipient_id: 'recipient-1',
      effective_date: '2026-10-15'
    }));
    expect(fixture.nativeElement.textContent).toContain('Current custodian: person@example.invalid');
  });

  it('surfaces assignment API errors and hides assignment controls without permission', () => {
    spyOn(window, 'confirm').and.returnValue(true);
    fixture.componentInstance.openAsset(testAsset);
    fixture.componentInstance.assignmentForm.recipient_id = 'recipient-1';
    registry.createAssignment.and.returnValue(throwError(() => ({
      error: { detail: 'Only in-stock assets can be assigned' }
    })));
    fixture.componentInstance.assignAsset();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Only in-stock assets can be assigned');

    permissions = new Set(['company.read', 'asset.read']);
    fixture.componentInstance.openAsset(testAsset);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).not.toContain('Assign this in-stock asset');
    expect(registry.assignmentRecipients).toHaveBeenCalledTimes(1);
  });

  it('explains that an active company recipient is required before assignment', () => {
    registry.assignmentRecipients.and.returnValue(of([]));
    fixture.componentInstance.openAsset(testAsset);
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain(
      'No active recipients are available. Invite a company user in Users & Access and have them accept the invitation before assigning an asset.'
    );
  });

  it('shows retained handover and return details in historical assignments', () => {
    fixture.componentInstance.openAsset(testAsset);
    fixture.componentInstance.assignmentHistory = [{
      ...testAssignment,
      id: 'assignment-closed',
      company_id: company.id,
      asset_id: testAsset.id,
      recipient_id: 'recipient-1',
      recipient_email: 'previous-recipient@example.invalid',
      status: 'returned',
      reference: 'PHASE3-HISTORY',
      handover_date: '2026-10-15',
      handover_condition: 'Good',
      included_items: 'Laptop and charger',
      acknowledgement: 'Received in good order',
      handover_notes: 'Initial handover',
      ended_at: '2026-10-17T10:00:00Z',
      return_date: '2026-10-17',
      return_condition: 'Fair',
      return_notes: 'Returned to stores',
      issue_details: 'Minor screen mark',
      next_asset_status: 'maintenance'
    }];
    fixture.detectChanges();

    const historyText = fixture.nativeElement.textContent as string;
    expect(historyText).toContain('previous-recipient@example.invalid');
    expect(historyText).toContain('Laptop and charger');
    expect(historyText).toContain('Received in good order');
    expect(historyText).toContain('Initial handover');
    expect(historyText).toContain('Returned Oct 17, 2026 · Next status: maintenance');
    expect(historyText).toContain('Returned to stores');
    expect(historyText).toContain('Minor screen mark');
  });

  it('loads maintenance history in a permission-gated workspace view', () => {
    permissions = new Set(['company.read', 'asset.read', 'maintenance.read']);
    registry.maintenanceRequests.and.returnValue(of([testMaintenanceRequest]));
    registry.maintenanceUsers.and.returnValue(of([{ id: 'support-1', email: 'support@example.invalid' }]));
    registry.listAssets.and.returnValue(of({ items: [testAsset], total: 1, page: 1, page_size: 100 }));
    fixture.detectChanges();
    const button = Array.from(fixture.nativeElement.querySelectorAll('nav button') as NodeListOf<HTMLButtonElement>)
      .find((item) => item.textContent?.trim() === 'Warranty & Maintenance');
    expect(button).toBeTruthy();
    button?.click();
    fixture.detectChanges();

    expect(registry.maintenanceRequests).toHaveBeenCalledWith(company.id, { asset_id: '', status: '' });
    expect(fixture.nativeElement.textContent).toContain('Maintenance request history');
    expect(fixture.nativeElement.textContent).toContain('Laptop will not start');

    permissions = new Set(['company.read', 'asset.read']);
    fixture.detectChanges();
    expect(Array.from(fixture.nativeElement.querySelectorAll('nav button') as NodeListOf<HTMLButtonElement>)
      .map((item) => item.textContent?.trim())).not.toContain('Warranty & Maintenance');
  });

  it('creates a typed maintenance request and refreshes persisted request history', () => {
    permissions = new Set(['company.read', 'asset.read', 'maintenance.read', 'maintenance.manage']);
    const created: MaintenanceRequest = { ...testMaintenanceRequest, id: 'request-new' };
    registry.createMaintenanceRequest.and.returnValue(of(created));
    registry.maintenanceRequests.and.returnValue(of([created]));
    registry.listAssets.and.returnValue(of({ items: [testAsset], total: 1, page: 1, page_size: 100 }));
    const component = fixture.componentInstance;
    component.maintenanceCreateForm = {
      asset_id: testAsset.id,
      title: '  Laptop will not start  ',
      issue_description: '  Power light flashes.  ',
      priority: 'high',
      reported_date: '2026-10-15',
      assignee_id: ''
    };
    component.createMaintenanceRequest();

    expect(registry.createMaintenanceRequest).toHaveBeenCalledWith(company.id, {
      asset_id: testAsset.id,
      title: 'Laptop will not start',
      issue_description: 'Power light flashes.',
      priority: 'high',
      reported_date: '2026-10-15',
      assignee_id: null
    });
    expect(component.successMessage).toContain('Maintenance request created');
    expect(component.maintenanceRequests).toEqual([created]);
  });

  it('loads and displays executive dashboard metrics', () => {
    permissions = new Set(['company.read', 'asset.read', 'dashboard.read']);
    registry.dashboard.and.returnValue(of({
      total_assets: 10,
      assets_by_status: { in_stock: 6, assigned: 4 },
      assets_by_category: [{ category_id: 'cat-1', category_name: 'Laptops', count: 10 }],
      assets_by_site: [{ site_id: 'site-1', site_name: 'HQ', count: 10 }],
      assets_by_department: [{ department_id: 'dept-1', department_name: 'IT', count: 10 }],
      expiring_contracts_count: 2,
      expiring_contracts: [{
        id: 'c-1',
        contract_type: 'warranty',
        reference_number: 'WAR-01',
        provider_name: 'Dell Care',
        asset_id: 'asset-1',
        asset_number: 'AST-000001',
        end_date: '2026-11-10',
        days_remaining: 26
      }],
      maintenance_summary: { open: 1, in_progress: 1, resolved: 0, closed: 0, total_open_and_in_progress: 2 },
      procurement_summary: { total_purchase_orders: 3, orders_by_status: { open: 3 }, total_goods_receipts: 2, total_items_received: 5, total_items_rejected: 0 },
      recent_activity: [{
        id: 'act-1',
        action: 'asset.created',
        entity_type: 'Asset',
        entity_id: 'asset-1',
        actor_id: 'user-1',
        actor_email: 'admin@example.invalid',
        outcome: 'success',
        occurred_at: '2026-10-15T10:00:00Z'
      }]
    }));

    const component = fixture.componentInstance;
    component.setView('dashboard');
    fixture.detectChanges();

    expect(registry.dashboard).toHaveBeenCalledWith(company.id);
    expect(component.dashboardData?.total_assets).toBe(10);
    expect(fixture.nativeElement.textContent).toContain('Total Assets');
    expect(fixture.nativeElement.textContent).toContain('10');
    expect(fixture.nativeElement.textContent).toContain('In Stock');
    expect(fixture.nativeElement.textContent).toContain('Assigned');
    expect(fixture.nativeElement.textContent).toContain('Contracts Expiring (30d)');
    expect(fixture.nativeElement.textContent).toContain('Open Maintenance');
  });

  it('calculates percentages and donut slices correctly and prevents division by zero', () => {
    const component = fixture.componentInstance;

    // Normal calculation
    expect(component.calculatePercentage(6, 10)).toBe(60);
    expect(component.calculatePercentage(4, 10)).toBe(40);
    expect(component.calculatePercentage(0, 10)).toBe(0);

    // Division by zero and edge cases
    expect(component.calculatePercentage(5, 0)).toBe(0);
    expect(component.calculatePercentage(5, undefined)).toBe(0);
    expect(component.calculatePercentage(5, null)).toBe(0);
    expect(component.calculatePercentage(5, -10)).toBe(0);
    expect(component.calculatePercentage(-5, 10)).toBe(0);
    expect(component.calculatePercentage(15, 10)).toBe(100);

    // Donut slices with data
    component.dashboardData = {
      total_assets: 10,
      assets_by_status: { in_stock: 6, assigned: 4 },
      assets_by_category: [],
      assets_by_site: [],
      assets_by_department: [],
      expiring_contracts_count: 0,
      expiring_contracts: [],
      maintenance_summary: { open: 0, in_progress: 0, resolved: 0, closed: 0, total_open_and_in_progress: 0 },
      procurement_summary: { total_purchase_orders: 0, orders_by_status: {}, total_goods_receipts: 0, total_items_received: 0, total_items_rejected: 0 },
      recent_activity: []
    };

    const slices = component.getStatusSlices();
    expect(slices.length).toBe(2);
    expect(slices[0].status).toBe('in_stock');
    expect(slices[0].percentage).toBe(60);
    expect(slices[1].status).toBe('assigned');
    expect(slices[1].percentage).toBe(40);

    const gradient = component.getStatusDonutGradient();
    expect(gradient).toContain('conic-gradient');
    expect(gradient).toContain('60%');

    // Donut slices with zero total assets
    component.dashboardData.total_assets = 0;
    component.dashboardData.assets_by_status = {};
    expect(component.getStatusDonutGradient()).toBe('conic-gradient(#e2e8f0 0% 100%)');
  });

  it('classifies expiry badges and formats labels correctly', () => {
    const component = fixture.componentInstance;

    // Overdue/expired
    expect(component.getExpiryBadgeClass(-5)).toBe('status-expired');
    expect(component.getExpiryLabel(-5)).toBe('5d overdue');

    // Expires today
    expect(component.getExpiryBadgeClass(0)).toBe('status-urgent');
    expect(component.getExpiryLabel(0)).toBe('Expires today');

    // Urgent (1-7 days)
    expect(component.getExpiryBadgeClass(1)).toBe('status-urgent');
    expect(component.getExpiryLabel(1)).toBe('1d left (Urgent)');
    expect(component.getExpiryBadgeClass(7)).toBe('status-urgent');
    expect(component.getExpiryLabel(7)).toBe('7d left (Urgent)');

    // Warning (8-30 days)
    expect(component.getExpiryBadgeClass(8)).toBe('status-expiring_soon');
    expect(component.getExpiryLabel(8)).toBe('8d left');
    expect(component.getExpiryBadgeClass(30)).toBe('status-expiring_soon');
    expect(component.getExpiryLabel(30)).toBe('30d left');
  });

  it('formats audit actions cleanly into readable labels', () => {
    const component = fixture.componentInstance;

    expect(component.formatAuditAction('asset.create')).toBe('Asset Create');
    expect(component.formatAuditAction('asset.assignment.create')).toBe('Asset Assignment Create');
    expect(component.formatAuditAction('maintenance_request.resolve')).toBe('Maintenance Request Resolve');
    expect(component.formatAuditAction('goods_receipt.create')).toBe('Goods Receipt Create');
    expect(component.formatAuditAction(null)).toBe('Activity');
    expect(component.formatAuditAction('')).toBe('Activity');
  });

  it('navigates to assets, reports, maintenance and procurement with correct filters and permissions', () => {
    permissions = new Set(['company.read', 'asset.read', 'maintenance.read', 'procurement.read']);
    const component = fixture.componentInstance;
    component.activeView = 'dashboard';

    // Navigate to assets with status
    component.navigateToAssets('in_stock');
    expect(component.activeView).toBe('assets');
    expect(component.filters.status).toBe('in_stock');
    expect(component.page).toBe(1);

    // Filter by category
    component.activeView = 'dashboard';
    component.filterByCategory('cat-99');
    expect(component.activeView).toBe('assets');
    expect(component.filters.category_id).toBe('cat-99');

    // Filter by department
    component.activeView = 'dashboard';
    component.filterByDepartment('dept-42');
    expect(component.activeView).toBe('assets');
    expect(component.filters.department_id).toBe('dept-42');

    // Navigate to contracts
    component.activeView = 'dashboard';
    component.navigateToContracts();
    expect(component.activeView).toBe('reports');
    expect(component.activeReport).toBe('warranty-expiry');

    // Navigate to maintenance
    component.activeView = 'dashboard';
    component.navigateToMaintenance();
    expect(component.activeView).toBe('maintenance');

    // Navigate to procurement
    component.activeView = 'dashboard';
    component.navigateToProcurement();
    expect(component.activeView).toBe('procurement');

    // Missing permissions guard
    permissions = new Set(['company.read']);
    component.activeView = 'dashboard';
    component.navigateToAssets('in_stock');
    expect(component.activeView).toBe('dashboard'); // Did not navigate
  });

  it('displays genuine zeroes when dashboard returns genuine zero metrics', () => {
    permissions = new Set(['company.read', 'asset.read', 'dashboard.read']);
    registry.dashboard.and.returnValue(of({
      total_assets: 0,
      assets_by_status: {},
      assets_by_category: [],
      assets_by_site: [],
      assets_by_department: [],
      expiring_contracts_count: 0,
      expiring_contracts: [],
      maintenance_summary: { open: 0, in_progress: 0, resolved: 0, closed: 0, total_open_and_in_progress: 0 },
      procurement_summary: { total_purchase_orders: 0, orders_by_status: {}, total_goods_receipts: 0, total_items_received: 0, total_items_rejected: 0 },
      recent_activity: []
    }));

    const component = fixture.componentInstance;
    component.setView('dashboard');
    fixture.detectChanges();

    expect(component.dashboardData?.total_assets).toBe(0);
    expect(component.dashboardError).toBe('');
    expect(fixture.nativeElement.textContent).toContain('0');
  });

  it('handles dashboard error and allows retry', () => {
    permissions = new Set(['company.read', 'asset.read', 'dashboard.read']);
    registry.dashboard.and.returnValue(throwError(() => ({ error: { detail: 'API timeout' } })));

    const component = fixture.componentInstance;
    component.setView('dashboard');
    fixture.detectChanges();

    expect(component.dashboardError).toBe('API timeout');
    expect(fixture.nativeElement.textContent).toContain('API timeout');

    // Test retry
    registry.dashboard.and.returnValue(of({
      total_assets: 1,
      assets_by_status: { in_stock: 1 },
      assets_by_category: [],
      assets_by_site: [],
      assets_by_department: [],
      expiring_contracts_count: 0,
      expiring_contracts: [],
      maintenance_summary: { open: 0, in_progress: 0, resolved: 0, closed: 0, total_open_and_in_progress: 0 },
      procurement_summary: { total_purchase_orders: 0, orders_by_status: {}, total_goods_receipts: 0, total_items_received: 0, total_items_rejected: 0 },
      recent_activity: []
    }));
    component.loadDashboard();
    expect(component.dashboardError).toBe('');
    expect(component.dashboardData?.total_assets).toBe(1);
  });

  it('hides Dashboard tab and defaults landing view to assets when user lacks dashboard.read', () => {
    // Simulate read-only user permissions without dashboard.read
    permissions.clear();
    ['company.read', 'organization.read', 'asset.read', 'asset.history.read', 'procurement.read', 'maintenance.read'].forEach(p => permissions.add(p));

    registry.dashboard.calls.reset();
    const component = fixture.componentInstance;
    component.selectCompany(company.id);
    fixture.detectChanges();

    // Verify active view fell back to 'assets'
    expect(component.activeView).toBe('assets');
    expect(registry.dashboard).not.toHaveBeenCalled();

    // Verify Dashboard tab button is not rendered in navigation
    const buttons: HTMLButtonElement[] = Array.from(fixture.nativeElement.querySelectorAll('.tabs button'));
    const buttonTexts = buttons.map(b => b.textContent?.trim());
    expect(buttonTexts).not.toContain('Dashboard');
    expect(buttonTexts).toContain('Assets');
  });

  it('prevents setView("dashboard") and falls back to assets when user lacks dashboard.read', () => {
    permissions.clear();
    ['company.read', 'asset.read'].forEach(p => permissions.add(p));

    registry.dashboard.calls.reset();
    const component = fixture.componentInstance;
    component.activeView = 'assets';
    component.setView('dashboard');

    expect(component.activeView).toBe('assets');
    expect(registry.dashboard).not.toHaveBeenCalled();
  });

  it('loads operational reports and switches report tabs', () => {
    permissions = new Set(['company.read', 'asset.read', 'maintenance.read', 'procurement.read']);
    registry.reportAssetRegister.and.returnValue(of([{
      id: 'asset-1',
      asset_number: 'AST-000001',
      category_id: 'cat-1',
      category_name: 'Laptops',
      manufacturer: 'Apple',
      model: 'MacBook Pro',
      serial_number: 'SN-001',
      status: 'in_stock',
      site_id: null,
      site_name: null,
      department_id: null,
      department_name: null,
      custodian_name: null,
      acquisition_date: '2026-01-01',
      acquisition_cost: 2000,
      warranty_start: null,
      warranty_end: null
    }]));
    registry.reportAssetAllocation.and.returnValue(of([]));
    registry.reportWarrantyExpiry.and.returnValue(of([]));
    registry.reportMaintenance.and.returnValue(of([]));
    registry.reportProcurement.and.returnValue(of([]));

    const component = fixture.componentInstance;
    component.setView('reports');
    fixture.detectChanges();

    expect(component.activeReport).toBe('asset-register');
    expect(registry.reportAssetRegister).toHaveBeenCalled();

    // Switch to allocation report
    component.selectReport('asset-allocation');
    expect(component.activeReport).toBe('asset-allocation');
    expect(registry.reportAssetAllocation).toHaveBeenCalled();

    // Switch to warranty expiry
    component.selectReport('warranty-expiry');
    expect(component.activeReport).toBe('warranty-expiry');
    expect(registry.reportWarrantyExpiry).toHaveBeenCalled();

    // Switch to maintenance
    component.selectReport('maintenance');
    expect(component.activeReport).toBe('maintenance');
    expect(registry.reportMaintenance).toHaveBeenCalled();

    // Switch to procurement
    component.selectReport('procurement');
    expect(component.activeReport).toBe('procurement');
    expect(registry.reportProcurement).toHaveBeenCalled();
  });

  it('generates CSV report content with UTF-8 BOM, sanitized formula fields, and legitimate values', () => {
    permissions = new Set(['company.read', 'asset.read']);
    fixture.componentInstance.activeReport = 'asset-register';
    fixture.componentInstance.assetRegisterReport = [{
      id: 'asset-sec-1',
      asset_number: 'MZ-000001',
      category_id: 'cat-1',
      category_name: 'Laptops',
      manufacturer: 'Apple',
      model: '=cmd|"/C calc"!A0',
      serial_number: '+SN-EVIL',
      status: 'in_stock',
      site_id: null,
      site_name: 'München, HQ',
      department_id: null,
      department_name: 'IT "Dept"\nFloor 2',
      custodian_name: '@hacker',
      acquisition_date: '2026-01-01',
      acquisition_cost: 1500.50,
      warranty_start: null,
      warranty_end: null
    }];

    const csv = fixture.componentInstance.generateReportCsvContent();
    // 1. Starts with UTF-8 BOM
    expect(csv.startsWith('\uFEFF')).toBeTrue();
    // 2. Formula fields are neutralized with single quote
    expect(csv).toContain("\"'=cmd|\"\"/C calc\"\"!A0\"");
    expect(csv).toContain("\"'+SN-EVIL\"");
    expect(csv).toContain("\"'@hacker\"");
    // 3. Normal fields are preserved with quotes, commas, newlines, and Unicode
    expect(csv).toContain('"MZ-000001"');
    expect(csv).toContain('"München, HQ"');
    expect(csv).toContain('"IT ""Dept""\nFloor 2"');
    // 4. Numeric value is preserved
    expect(csv).toContain('"1500.5"');
  });

  it('calculates line subtotals, line totals, and overall PO summary totals dynamically', () => {
    const component = fixture.componentInstance;
    component.purchaseOrderForm = {
      supplier_id: 'sup-1',
      order_number: 'PO-CALC-1',
      ordered_date: '2026-10-19',
      expected_date: '2026-10-25',
      notes: 'Multi-line calculation test',
      lines: [
        {
          category_id: 'cat-1',
          description: 'Laptops',
          quantity_ordered: 3,
          unit_cost: 1000,
          discount: 100,
          tax_rate: 10,
          tax_amount: 50
        },
        {
          category_id: 'cat-2',
          description: 'Monitors',
          quantity_ordered: 2,
          unit_cost: 500,
          discount: 0,
          tax_rate: 18,
          tax_amount: 100
        }
      ]
    };

    const line0 = component.purchaseOrderForm.lines[0];
    const line1 = component.purchaseOrderForm.lines[1];

    expect(component.poLineSubtotal(line0)).toBe(3000);
    expect(component.poLineTotal(line0)).toBe(2950);

    expect(component.poLineSubtotal(line1)).toBe(1000);
    expect(component.poLineTotal(line1)).toBe(1100);

    expect(component.poTotalQuantity).toBe(5);
    expect(component.poSubtotal).toBe(4000);
    expect(component.poTotalDiscount).toBe(100);
    expect(component.poTotalTax).toBe(150);
    expect(component.poTotalAmount).toBe(4050);
  });

  it('supports adding, editing, and removing PO lines while enforcing at least one line', () => {
    const component = fixture.componentInstance;
    expect(component.purchaseOrderForm.lines.length).toBe(1);

    component.addPoLine();
    expect(component.purchaseOrderForm.lines.length).toBe(2);

    component.addPoLine();
    expect(component.purchaseOrderForm.lines.length).toBe(3);

    // Remove middle line
    component.removePoLine(1);
    expect(component.purchaseOrderForm.lines.length).toBe(2);

    // Remove first line
    component.removePoLine(0);
    expect(component.purchaseOrderForm.lines.length).toBe(1);

    // Attempting to remove the last remaining line must do nothing
    component.removePoLine(0);
    expect(component.purchaseOrderForm.lines.length).toBe(1);
  });

  it('validates each line item in a multi-line PO before dispatching createPurchaseOrder', () => {
    permissions = new Set(['company.read', 'asset.read', 'procurement.read', 'procurement.manage']);
    const component = fixture.componentInstance;
    component.suppliers = [{ id: 'sup-1', company_id: company.id, code: 'SUP1', name: 'Supplier 1', is_active: true, email: null, phone: null, notes: null, created_at: '' }];
    component.categories = [
      { id: 'cat-1', company_id: company.id, code: 'CAT1', name: 'Laptops', is_active: true },
      { id: 'cat-2', company_id: company.id, code: 'CAT2', name: 'Monitors', is_active: true }
    ];

    component.purchaseOrderForm.supplier_id = 'sup-1';
    component.purchaseOrderForm.order_number = 'PO-VAL-MULTI';
    component.purchaseOrderForm.ordered_date = '2026-10-19';

    // Line 1 is valid
    component.purchaseOrderForm.lines[0] = {
      category_id: 'cat-1',
      description: 'Valid Laptop',
      quantity_ordered: 2,
      unit_cost: 1000,
      discount: 0,
      tax_rate: 0,
      tax_amount: 0
    };

    // Add invalid Line 2 (missing category)
    component.addPoLine();
    component.purchaseOrderForm.lines[1] = {
      category_id: '',
      description: 'Missing Category',
      quantity_ordered: 1,
      unit_cost: 100,
      discount: 0,
      tax_rate: 0,
      tax_amount: 0
    };
    component.createPurchaseOrder();
    expect(component.errorMessage).toBe('Please choose an asset category for line #2.');
    expect(registry.createPurchaseOrder).not.toHaveBeenCalled();

    // Line 2 missing description
    component.purchaseOrderForm.lines[1].category_id = 'cat-2';
    component.purchaseOrderForm.lines[1].description = '   ';
    component.createPurchaseOrder();
    expect(component.errorMessage).toBe('Please enter an item description for line #2.');
    expect(registry.createPurchaseOrder).not.toHaveBeenCalled();

    // Line 2 non-positive quantity
    component.purchaseOrderForm.lines[1].description = 'Valid Description';
    component.purchaseOrderForm.lines[1].quantity_ordered = 0;
    component.createPurchaseOrder();
    expect(component.errorMessage).toBe('Quantity ordered for line #2 must be greater than zero.');
    expect(registry.createPurchaseOrder).not.toHaveBeenCalled();

    // Line 2 negative unit cost
    component.purchaseOrderForm.lines[1].quantity_ordered = 3;
    component.purchaseOrderForm.lines[1].unit_cost = -10;
    component.createPurchaseOrder();
    expect(component.errorMessage).toBe('Unit cost for line #2 must be zero or a positive amount.');
    expect(registry.createPurchaseOrder).not.toHaveBeenCalled();
  });

  it('creates a purchase order with multiple lines belonging to distinct asset categories', () => {
    permissions = new Set(['company.read', 'asset.read', 'procurement.read', 'procurement.manage']);
    const component = fixture.componentInstance;
    component.suppliers = [{ id: 'sup-1', company_id: company.id, code: 'SUP1', name: 'Supplier 1', is_active: true, email: null, phone: null, notes: null, created_at: '' }];
    component.categories = [
      { id: 'cat-1', company_id: company.id, code: 'CAT1', name: 'Laptops', is_active: true },
      { id: 'cat-2', company_id: company.id, code: 'CAT2', name: 'Monitors', is_active: true },
      { id: 'cat-3', company_id: company.id, code: 'CAT3', name: 'Peripherals', is_active: true }
    ];

    component.purchaseOrderForm.supplier_id = 'sup-1';
    component.purchaseOrderForm.order_number = 'PO-MULTI-001';
    component.purchaseOrderForm.ordered_date = '2026-10-19';
    component.purchaseOrderForm.expected_date = '2026-10-30';
    component.purchaseOrderForm.lines = [
      { category_id: 'cat-1', description: 'Dell Latitude', quantity_ordered: 5, unit_cost: 1200, discount: 50, tax_rate: 10, tax_amount: 115 },
      { category_id: 'cat-2', description: 'Dell 27-inch 4K', quantity_ordered: 10, unit_cost: 350, discount: 0, tax_rate: 10, tax_amount: 350 },
      { category_id: 'cat-3', description: 'USB-C Docks', quantity_ordered: 5, unit_cost: 150, discount: 25, tax_rate: 10, tax_amount: 72.5 }
    ];

    const createdOrder: PurchaseOrder = {
      id: 'po-101',
      company_id: company.id,
      supplier_id: 'sup-1',
      order_number: 'PO-MULTI-001',
      ordered_date: '2026-10-19',
      expected_date: '2026-10-30',
      status: 'open',
      notes: null,
      created_at: '2026-10-19T00:00:00Z',
      total_quantity: 20,
      subtotal: '10250.00',
      total_amount: '10712.50',
      lines: [
        {
          id: 'line-1',
          company_id: company.id,
          purchase_order_id: 'po-101',
          category_id: 'cat-1',
          description: 'Dell Latitude',
          quantity_ordered: 5,
          unit_cost: '1200.00',
          quantity_received: 0,
          quantity_remaining: 5,
          discount: '50.00',
          tax_rate: '10.00',
          tax_amount: '115.00',
          line_subtotal: '6000.00',
          line_total: '6065.00'
        },
        {
          id: 'line-2',
          company_id: company.id,
          purchase_order_id: 'po-101',
          category_id: 'cat-2',
          description: 'Dell 27-inch 4K',
          quantity_ordered: 10,
          unit_cost: '350.00',
          quantity_received: 0,
          quantity_remaining: 10,
          discount: '0.00',
          tax_rate: '10.00',
          tax_amount: '350.00',
          line_subtotal: '3500.00',
          line_total: '3850.00'
        },
        {
          id: 'line-3',
          company_id: company.id,
          purchase_order_id: 'po-101',
          category_id: 'cat-3',
          description: 'USB-C Docks',
          quantity_ordered: 5,
          unit_cost: '150.00',
          quantity_received: 0,
          quantity_remaining: 5,
          discount: '25.00',
          tax_rate: '10.00',
          tax_amount: '72.50',
          line_subtotal: '750.00',
          line_total: '797.50'
        }
      ]
    };
    registry.createPurchaseOrder.and.returnValue(of(createdOrder));

    component.createPurchaseOrder();

    expect(registry.createPurchaseOrder).toHaveBeenCalledWith(
      company.id,
      jasmine.objectContaining({
        order_number: 'PO-MULTI-001',
        supplier_id: 'sup-1',
        lines: jasmine.arrayContaining([
          jasmine.objectContaining({ category_id: 'cat-1', description: 'Dell Latitude', quantity_ordered: 5, unit_cost: 1200 }),
          jasmine.objectContaining({ category_id: 'cat-2', description: 'Dell 27-inch 4K', quantity_ordered: 10, unit_cost: 350 }),
          jasmine.objectContaining({ category_id: 'cat-3', description: 'USB-C Docks', quantity_ordered: 5, unit_cost: 150 })
        ])
      })
    );
    expect(component.purchaseOrders[0]).toEqual(createdOrder);
    expect(component.successMessage).toContain('Purchase order PO-MULTI-001 created.');
    expect(component.purchaseOrderForm.order_number).toBe('');
    expect(component.purchaseOrderForm.lines.length).toBe(1);
  });

  it('reopens an existing open PO for editing, modifies lines, and saves via updatePurchaseOrder', () => {
    permissions = new Set(['company.read', 'asset.read', 'procurement.read', 'procurement.manage']);
    const component = fixture.componentInstance;
    component.suppliers = [{ id: 'sup-1', company_id: company.id, code: 'SUP1', name: 'Supplier 1', is_active: true, email: null, phone: null, notes: null, created_at: '' }];
    component.categories = [
      { id: 'cat-1', company_id: company.id, code: 'CAT1', name: 'Laptops', is_active: true },
      { id: 'cat-2', company_id: company.id, code: 'CAT2', name: 'Monitors', is_active: true }
    ];

    const existingOrder: PurchaseOrder = {
      id: 'po-edit-1',
      company_id: company.id,
      supplier_id: 'sup-1',
      order_number: 'PO-EDIT-1',
      ordered_date: '2026-10-15',
      expected_date: '2026-10-25',
      status: 'open',
      notes: 'Initial PO note',
      created_at: '2026-10-15T00:00:00Z',
      lines: [
        {
          id: 'line-e1',
          company_id: company.id,
          purchase_order_id: 'po-edit-1',
          category_id: 'cat-1',
          description: 'Original Laptop line',
          quantity_ordered: 2,
          unit_cost: '1000.00',
          quantity_received: 0,
          quantity_remaining: 2,
          discount: '0.00',
          tax_rate: '0.00',
          tax_amount: '0.00',
          line_subtotal: '2000.00',
          line_total: '2000.00'
        }
      ]
    };
    component.purchaseOrders = [existingOrder];

    expect(component.canEditOrder(existingOrder)).toBeTrue();

    // Start editing
    component.editPurchaseOrder(existingOrder);
    expect(component.editingPurchaseOrderId).toBe('po-edit-1');
    expect(component.purchaseOrderForm.order_number).toBe('PO-EDIT-1');
    expect(component.purchaseOrderForm.lines.length).toBe(1);
    expect(component.purchaseOrderForm.lines[0].description).toBe('Original Laptop line');

    // Add a second line
    component.addPoLine();
    component.purchaseOrderForm.lines[1] = {
      category_id: 'cat-2',
      description: 'Added Monitor line',
      quantity_ordered: 4,
      unit_cost: 300,
      discount: 0,
      tax_rate: 0,
      tax_amount: 0
    };

    const updatedOrder: PurchaseOrder = {
      ...existingOrder,
      lines: [
        existingOrder.lines[0],
        {
          id: 'line-e2',
          company_id: company.id,
          purchase_order_id: 'po-edit-1',
          category_id: 'cat-2',
          description: 'Added Monitor line',
          quantity_ordered: 4,
          unit_cost: '300.00',
          quantity_received: 0,
          quantity_remaining: 4,
          discount: '0.00',
          tax_rate: '0.00',
          tax_amount: '0.00',
          line_subtotal: '1200.00',
          line_total: '1200.00'
        }
      ]
    };
    registry.updatePurchaseOrder.and.returnValue(of(updatedOrder));

    component.createPurchaseOrder();

    expect(registry.updatePurchaseOrder).toHaveBeenCalledWith(
      company.id,
      'po-edit-1',
      jasmine.objectContaining({
        order_number: 'PO-EDIT-1',
        lines: jasmine.arrayContaining([
          jasmine.objectContaining({ category_id: 'cat-1', description: 'Original Laptop line' }),
          jasmine.objectContaining({ category_id: 'cat-2', description: 'Added Monitor line', quantity_ordered: 4 })
        ])
      })
    );
    expect(component.editingPurchaseOrderId).toBe('');
    expect(component.successMessage).toContain('Purchase order PO-EDIT-1 updated.');
    expect(component.purchaseOrders[0].lines.length).toBe(2);
  });

  it('cancels PO edit and clears form when cancelPoEdit is invoked', () => {
    const component = fixture.componentInstance;
    component.editingPurchaseOrderId = 'po-edit-99';
    component.purchaseOrderForm.order_number = 'PO-TEMP';

    component.cancelPoEdit();

    expect(component.editingPurchaseOrderId).toBe('');
    expect(component.purchaseOrderForm.order_number).toBe('');
    expect(component.purchaseOrderForm.lines.length).toBe(1);
  });

  it('prevents editing POs that are received or have existing goods receipts', () => {
    permissions = new Set(['company.read', 'asset.read', 'procurement.read', 'procurement.manage']);
    const component = fixture.componentInstance;

    const receivedOrder: PurchaseOrder = {
      id: 'po-rcvd',
      company_id: company.id,
      supplier_id: 'sup-1',
      order_number: 'PO-RCVD',
      ordered_date: '2026-10-10',
      expected_date: null,
      status: 'received',
      notes: null,
      created_at: '',
      lines: []
    };
    expect(component.canEditOrder(receivedOrder)).toBeFalse();

    const openOrderWithReceipt: PurchaseOrder = {
      id: 'po-has-grn',
      company_id: company.id,
      supplier_id: 'sup-1',
      order_number: 'PO-HAS-GRN',
      ordered_date: '2026-10-10',
      expected_date: null,
      status: 'open',
      notes: null,
      created_at: '',
      lines: []
    };
    component.goodsReceipts = [
      {
        id: 'grn-1',
        company_id: company.id,
        purchase_order_id: 'po-has-grn',
        receipt_number: 'GRN-001',
        received_date: '2026-10-15',
        delivery_reference: null,
        notes: null,
        created_at: '',
        lines: []
      }
    ];
    expect(component.canEditOrder(openOrderWithReceipt)).toBeFalse();
  });

  it('auto-populates remaining quantity on line change and rejects over-receipt in goods receipt form', () => {
    permissions = new Set(['company.read', 'asset.read', 'procurement.read', 'procurement.manage']);
    const component = fixture.componentInstance;

    const po: PurchaseOrder = {
      id: 'po-rcv-test',
      company_id: company.id,
      supplier_id: 'sup-1',
      order_number: 'PO-RCV-01',
      ordered_date: '2026-10-15',
      expected_date: null,
      status: 'partially_received',
      notes: null,
      created_at: '',
      lines: [
        {
          id: 'line-alpha',
          company_id: company.id,
          purchase_order_id: 'po-rcv-test',
          category_id: 'cat-1',
          description: 'Laptops',
          quantity_ordered: 10,
          unit_cost: '1000.00',
          quantity_received: 4,
          quantity_remaining: 6,
          discount: '0.00',
          tax_rate: '0.00',
          tax_amount: '0.00',
          line_subtotal: '10000.00',
          line_total: '10000.00'
        },
        {
          id: 'line-beta',
          company_id: company.id,
          purchase_order_id: 'po-rcv-test',
          category_id: 'cat-2',
          description: 'Monitors',
          quantity_ordered: 5,
          unit_cost: '300.00',
          quantity_received: 0,
          quantity_remaining: 5,
          discount: '0.00',
          tax_rate: '0.00',
          tax_amount: '0.00',
          line_subtotal: '1500.00',
          line_total: '1500.00'
        }
      ]
    };
    component.purchaseOrders = [po];
    // Record existing receipt for line-alpha of 4 units
    component.goodsReceipts = [
      {
        id: 'grn-p1',
        company_id: company.id,
        purchase_order_id: 'po-rcv-test',
        receipt_number: 'GRN-001',
        received_date: '2026-10-16',
        delivery_reference: null,
        notes: null,
        created_at: '',
        lines: [
          {
            id: 'grn-l1',
            purchase_order_line_id: 'line-alpha',
            quantity_received: 4,
            quantity_rejected: 0,
            discrepancy_notes: null,
            assets: []
          }
        ]
      }
    ];

    // Select this purchase order for receipt
    component.selectReceiptOrder('po-rcv-test');
    expect(component.goodsReceiptForm.purchase_order_line_id).toBe('line-alpha');
    // Remaining for line-alpha: 10 - 4 = 6
    expect(component.goodsReceiptForm.quantity_received).toBe(6);

    // Switch to line-beta
    component.onReceiptLineChange('line-beta');
    expect(component.goodsReceiptForm.purchase_order_line_id).toBe('line-beta');
    // Remaining for line-beta: 5 - 0 = 5
    expect(component.goodsReceiptForm.quantity_received).toBe(5);

    // Attempt over-receipt for line-beta (trying to receive 6 when only 5 remaining)
    component.goodsReceiptForm.receipt_number = 'GRN-002';
    component.goodsReceiptForm.quantity_received = 6;
    component.goodsReceiptForm.quantity_rejected = 0;
    component.createGoodsReceipt();

    expect(component.errorMessage).toBe(
      'Received quantity must not exceed the remaining ordered quantity, and rejected quantity must not exceed received quantity.'
    );
    expect(registry.receiveGoods).not.toHaveBeenCalled();
  });
});

describe('serializeCsvCell security and formatting', () => {
  it('handles empty and null values safely', () => {
    expect(serializeCsvCell(null)).toBe('""');
    expect(serializeCsvCell(undefined)).toBe('""');
    expect(serializeCsvCell('')).toBe('""');
  });

  it('preserves ordinary positive, negative, zero and decimal numeric values', () => {
    expect(serializeCsvCell(0)).toBe('"0"');
    expect(serializeCsvCell(42)).toBe('"42"');
    expect(serializeCsvCell(-42)).toBe('"-42"');
    expect(serializeCsvCell(1234.56)).toBe('"1234.56"');
    expect(serializeCsvCell(-99.95)).toBe('"-99.95"');
    expect(serializeCsvCell(Infinity)).toBe('""');
    expect(serializeCsvCell(NaN)).toBe('""');
  });

  it('preserves commas, double quotes and embedded newlines according to RFC-4180', () => {
    expect(serializeCsvCell('Value with, comma')).toBe('"Value with, comma"');
    expect(serializeCsvCell('Value with "quotes"')).toBe('"Value with ""quotes"""');
    expect(serializeCsvCell("Line 1\nLine 2")).toBe('"Line 1\nLine 2"');
    expect(serializeCsvCell("Line 1\r\nLine 2")).toBe('"Line 1\r\nLine 2"');
    expect(serializeCsvCell('Mixed: "quoted", with comma and \nnewline')).toBe('"Mixed: ""quoted"", with comma and \nnewline"');
  });

  it('preserves non-ASCII Unicode characters', () => {
    expect(serializeCsvCell('München Büromöbel')).toBe('"München Büromöbel"');
    expect(serializeCsvCell('日本語テスト')).toBe('"日本語テスト"');
    expect(serializeCsvCell('Emoji 💻 & symbols € ™')).toBe('"Emoji 💻 & symbols € ™"');
  });

  it('neutralizes values beginning with each formula character (=, +, -, @)', () => {
    expect(serializeCsvCell('=cmd|"/C calc"!A0')).toBe("\"'=cmd|\"\"/C calc\"\"!A0\"");
    expect(serializeCsvCell('+1+2')).toBe("\"'+1+2\"");
    expect(serializeCsvCell('-2+3')).toBe("\"'-2+3\"");
    expect(serializeCsvCell('@SUM(1,2)')).toBe("\"'@SUM(1,2)\"");
    expect(serializeCsvCell('=1+1')).toBe("\"'=1+1\"");
  });

  it('neutralizes formula characters preceded by whitespace or control characters', () => {
    expect(serializeCsvCell('  =cmd')).toBe("\"'  =cmd\"");
    expect(serializeCsvCell('\t@calc')).toBe("\"'\t@calc\"");
    expect(serializeCsvCell('\r\n+SUM(1,2)')).toBe("\"'\r\n+SUM(1,2)\"");
    expect(serializeCsvCell('   -dangerous')).toBe("\"'   -dangerous\"");
    expect(serializeCsvCell('\x00=payload')).toBe("\"'\x00=payload\"");
    expect(serializeCsvCell('\x1b=calc')).toBe("\"'\x1b=calc\"");
  });

  it('does not neutralize safe text without formula characters', () => {
    expect(serializeCsvCell('MZ-000001')).toBe('"MZ-000001"');
    expect(serializeCsvCell('Dell Latitude 5420')).toBe('"Dell Latitude 5420"');
    expect(serializeCsvCell('user@mindzen.invalid')).toBe('"user@mindzen.invalid"');
  });
});

describe('RegistryComponent Physical Asset Verification', () => {
  let fixture: ComponentFixture<RegistryComponent>;
  let component: RegistryComponent;
  let registry: jasmine.SpyObj<RegistryService>;
  let permissions: Set<string>;

  const company: Company = {
    id: 'company-1',
    code: 'ACME',
    name: 'Acme',
    is_active: true
  };

  beforeEach(() => {
    permissions = new Set(['company.read', 'asset.read', 'verification.read', 'verification.manage']);
    registry = jasmine.createSpyObj<RegistryService>('RegistryService', [
      'companies',
      'listMaster',
      'listNumberRules',
      'companyMembers',
      'companyRoles',
      'listAssets',
      'downloadAssetImportTemplate',
      'previewAssetImport',
      'confirmAssetImport',
      'getAsset',
      'lookupAsset',
      'usages',
      'history',
      'assignments',
      'assignmentRecipients',
      'createAssignment',
      'recordHandover',
      'returnAssignment',
      'transferAssignment',
      'listLocations',
      'suppliers',
      'purchaseOrders',
      'getPurchaseOrder',
      'goodsReceipts',
      'createSupplier',
      'createPurchaseOrder',
      'updatePurchaseOrder',
      'receiveGoods',
      'serviceContracts',
      'createServiceContract',
      'cancelServiceContract',
      'maintenanceUsers',
      'maintenanceRequests',
      'createMaintenanceRequest',
      'updateMaintenanceRequest',
      'dashboard',
      'reportAssetRegister',
      'reportAssetAllocation',
      'reportWarrantyExpiry',
      'reportMaintenance',
      'reportProcurement',
      'listVerificationCampaigns',
      'getVerificationCampaign',
      'createVerificationCampaign',
      'updateVerificationCampaign',
      'transitionVerificationCampaignStatus',
      'getVerificationExpectedAssets',
      'recordVerificationObservation',
      'getVerificationDiscrepancies',
      'resolveVerificationDiscrepancy',
      'recordUnregisteredAsset',
      'getUnregisteredAssets',
      'registerUnregisteredAsset',
      'getVerificationDashboard',
      'reportVerificationCampaigns',
      'reportVerificationDiscrepancies',
      'getAssetFinancial',
      'configureAssetFinancial',
      'editAssetFinancial',
      'adjustAssetFinancial',
      'getDepreciationSchedule',
      'postDepreciation',
      'listDepreciationEntries',
      'postBatchDepreciation',
      'disposeAsset',
      'getAssetDisposal',
      'reportAssetDepreciation',
      'reportAssetDisposals',
      'getFinancialDashboard',
      'listAlerts',
      'getAlertSummary',
      'syncAlerts',
      'acknowledgeAlert',
      'assignAlert',
      'resolveAlert',
      'dismissAlert',
      'getLastAlertJob',
      'getNotifications',
      'getUnreadNotificationCount',
      'markNotificationRead',
      'markAllNotificationsRead'
    ]);

    registry.getLastAlertJob.and.returnValue(of(null));
    registry.getNotifications.and.returnValue(of([]));
    registry.getUnreadNotificationCount.and.returnValue(of({ unread_count: 0 }));
    registry.markNotificationRead.and.returnValue(of({} as any));
    registry.markAllNotificationsRead.and.returnValue(of({ unread_count: 0 }));

    registry.companies.and.returnValue(of([company]));
    registry.listMaster.and.returnValue(of([]));
    registry.listNumberRules.and.returnValue(of([]));
    registry.companyMembers.and.returnValue(of([]));
    registry.companyRoles.and.returnValue(of([]));
    registry.listAssets.and.returnValue(of({ items: [], total: 0, page: 1, page_size: 15 }));
    registry.getAsset.and.returnValue(of(testAsset));
    registry.lookupAsset.and.returnValue(of(testAsset));
    registry.usages.and.returnValue(of([]));
    registry.history.and.returnValue(of([]));
    registry.assignments.and.returnValue(of([]));
    registry.assignmentRecipients.and.returnValue(of([]));
    registry.listLocations.and.returnValue(of([]));
    registry.suppliers.and.returnValue(of([]));
    registry.purchaseOrders.and.returnValue(of([]));
    registry.getPurchaseOrder.and.returnValue(of({} as any));
    registry.goodsReceipts.and.returnValue(of([]));
    registry.serviceContracts.and.returnValue(of([]));
    registry.maintenanceUsers.and.returnValue(of([]));
    registry.maintenanceRequests.and.returnValue(of([]));
    registry.dashboard.and.returnValue(of({} as any));
    registry.reportAssetRegister.and.returnValue(of([]));
    registry.reportAssetAllocation.and.returnValue(of([]));
    registry.reportWarrantyExpiry.and.returnValue(of([]));
    registry.reportMaintenance.and.returnValue(of([]));
    registry.reportProcurement.and.returnValue(of([]));

    registry.listVerificationCampaigns.and.returnValue(of([testCampaign]));
    registry.getVerificationCampaign.and.returnValue(of(testCampaign));
    registry.createVerificationCampaign.and.returnValue(of(testCampaign));
    registry.updateVerificationCampaign.and.returnValue(of(testCampaign));
    registry.transitionVerificationCampaignStatus.and.returnValue(of({ ...testCampaign, status: 'in_progress' }));
    registry.getVerificationExpectedAssets.and.returnValue(of([testExpectedAsset]));
    registry.recordVerificationObservation.and.returnValue(of(testObservation));
    registry.getVerificationDiscrepancies.and.returnValue(of([testDiscrepancy]));
    registry.resolveVerificationDiscrepancy.and.returnValue(of({ ...testDiscrepancy, status: 'resolved' }));
    registry.recordUnregisteredAsset.and.returnValue(of(testUnregisteredAsset));
    registry.getUnregisteredAssets.and.returnValue(of([testUnregisteredAsset]));
    registry.registerUnregisteredAsset.and.returnValue(of({ ...testUnregisteredAsset, status: 'registered', registered_asset_number: 'AST-000099' }));
    registry.getVerificationDashboard.and.returnValue(of(testDashboardSummary));
    registry.reportVerificationCampaigns.and.returnValue(of([{
      campaign_id: 'camp-1',
      campaign_reference: 'VER-2026-Q4',
      campaign_name: 'Q4 IT Verification',
      status: 'in_progress',
      start_date: '2026-10-01',
      end_date: '2026-10-31',
      total_expected: 10,
      total_verified: 8,
      total_missing: 1,
      discrepancy_count: 2,
      unregistered_count: 1,
      completion_percentage: 80.0,
      created_at: '2026-10-01T00:00:00Z',
      completed_at: null
    }]));
    registry.reportVerificationDiscrepancies.and.returnValue(of([{
      discrepancy_id: 'disc-1',
      campaign_reference: 'VER-2026-Q4',
      campaign_name: 'Q4 IT Verification',
      asset_number: 'AST-000001',
      discrepancy_type: 'location_mismatch',
      status: 'pending',
      expected_summary: 'Room 101',
      observed_summary: 'Server Room B',
      notes: 'Moved without transfer',
      resolution_action: null,
      resolution_notes: null,
      resolved_by_name: null,
      resolved_at: null,
      created_at: '2026-10-19T00:00:00Z'
    }]));
    registry.getAssetFinancial.and.returnValue(of(undefined as any));
    registry.configureAssetFinancial.and.returnValue(of({} as any));
    registry.editAssetFinancial.and.returnValue(of({} as any));
    registry.adjustAssetFinancial.and.returnValue(of({} as any));
    registry.getDepreciationSchedule.and.returnValue(of([]));
    registry.postDepreciation.and.returnValue(of({} as any));
    registry.listDepreciationEntries.and.returnValue(of([]));
    registry.postBatchDepreciation.and.returnValue(of({ period: '2026-10', processed_count: 0, posted_count: 0, skipped_count: 0, total_depreciation_posted: 0, posted_asset_ids: [], skipped: [] }));
    registry.disposeAsset.and.returnValue(of({} as any));
    registry.getAssetDisposal.and.returnValue(of({} as any));
    registry.reportAssetDepreciation.and.returnValue(of([]));
    registry.reportAssetDisposals.and.returnValue(of([]));
    registry.getFinancialDashboard.and.returnValue(of({
      total_capitalised_cost: 0,
      total_accumulated_depreciation: 0,
      total_net_book_value: 0,
      approaching_eol_count: 0,
      fully_depreciated_active_count: 0,
      disposed_count: 0,
      total_disposal_proceeds: 0,
      total_disposal_gain_loss: 0
    }));

    registry.listAlerts.and.returnValue(of([]));
    registry.getAlertSummary.and.returnValue(of(defaultAlertSummary));
    registry.syncAlerts.and.returnValue(of(defaultAlertSyncResponse));
    registry.acknowledgeAlert.and.returnValue(of({} as any));
    registry.assignAlert.and.returnValue(of({} as any));
    registry.resolveAlert.and.returnValue(of({} as any));
    registry.dismissAlert.and.returnValue(of({} as any));

    TestBed.configureTestingModule({
      imports: [RegistryComponent],
      providers: [
        provideHttpClient(),
        provideRouter([]),
        { provide: RegistryService, useValue: registry },
        {
          provide: AuthService,
          useValue: {
            currentUser: signal({ id: 'admin-1', email: 'admin@example.invalid', system_permissions: [], memberships: [] }),
            permissions: () => new Set(permissions)
          }
        }
      ]
    });
    fixture = TestBed.createComponent(RegistryComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('navigates to verification view and loads campaigns when permission is granted', () => {
    component.setView('verification');
    expect(component.activeView).toBe('verification');
    expect(registry.listVerificationCampaigns).toHaveBeenCalledWith(component.companyId, {
      status: undefined,
      search: undefined
    });
  });

  it('falls back to assets view if verification.read permission is absent', () => {
    permissions.delete('verification.read');
    component.setView('verification');
    expect(component.activeView).toBe('assets');
  });

  it('selects a campaign and loads expected assets, discrepancies, unregistered items, and dashboard', () => {
    component.selectVerificationCampaign(testCampaign);
    expect(component.selectedCampaign).toBe(testCampaign);
    expect(component.verificationSubView).toBe('expected');
    expect(registry.getVerificationDashboard).toHaveBeenCalledWith(component.companyId, testCampaign.id);
    expect(registry.getVerificationExpectedAssets).toHaveBeenCalledWith(component.companyId, testCampaign.id, jasmine.any(Object));
    expect(registry.getVerificationDiscrepancies).toHaveBeenCalledWith(component.companyId, testCampaign.id, jasmine.any(Object));
    expect(registry.getUnregisteredAssets).toHaveBeenCalledWith(component.companyId, testCampaign.id, undefined);
  });

  it('creates a new verification campaign successfully', () => {
    component.openCreateCampaignModal();
    expect(component.campaignCreateModalOpen).toBeTrue();

    component.campaignCreateForm = {
      campaign_reference: 'VER-2026-TEST',
      name: 'Test Verification',
      description: 'Audit scope',
      start_date: '2026-10-01',
      end_date: '2026-10-31',
      scope_category_ids: ['cat-1'],
      scope_location_ids: ['loc-1']
    };

    component.submitCreateCampaign();
    expect(registry.createVerificationCampaign).toHaveBeenCalledWith(component.companyId, jasmine.objectContaining({
      campaign_reference: 'VER-2026-TEST',
      name: 'Test Verification',
      scope_category_ids: ['cat-1'],
      scope_location_ids: ['loc-1']
    }));
    expect(component.campaignCreateModalOpen).toBeFalse();
    expect(component.successMessage).toContain('created successfully');
  });

  it('transitions campaign status across lifecycle states', () => {
    component.selectedCampaign = { ...testCampaign, status: 'draft' };
    component.transitionCampaignStatus('in_progress');

    expect(registry.transitionVerificationCampaignStatus).toHaveBeenCalledWith(
      component.companyId,
      testCampaign.id,
      'in_progress'
    );
    expect(component.selectedCampaign.status).toBe('in_progress');
    expect(component.successMessage).toContain('status updated to in progress');
  });

  it('records physical observation for an expected asset', () => {
    component.selectedCampaign = { ...testCampaign, status: 'in_progress' };
    component.openRecordObservationModal(testExpectedAsset);
    expect(component.observationModalOpen).toBeTrue();
    expect(component.selectedExpectedAsset).toBe(testExpectedAsset);

    component.observationForm = {
      is_found: true,
      actual_location_id: 'loc-2',
      actual_custodian_id: 'user-2',
      observed_condition: 'good',
      remarks: 'Found in meeting room',
      reference_notes: 'Tag verified'
    };

    component.submitObservation();
    expect(registry.recordVerificationObservation).toHaveBeenCalledWith(
      component.companyId,
      testCampaign.id,
      testExpectedAsset.id,
      jasmine.objectContaining({
        is_found: true,
        actual_location_id: 'loc-2',
        actual_custodian_id: 'user-2',
        observed_condition: 'good',
        remarks: 'Found in meeting room'
      })
    );
    expect(component.observationModalOpen).toBeFalse();
    expect(component.successMessage).toContain('Observation recorded');
  });

  it('resolves a discrepancy with audit notes and triggers asset reload if master updated', () => {
    component.selectedCampaign = { ...testCampaign, status: 'under_review' };
    component.openResolveDiscrepancyModal(testDiscrepancy);
    expect(component.resolveDiscrepancyModalOpen).toBeTrue();
    expect(component.selectedDiscrepancy).toBe(testDiscrepancy);

    component.resolveDiscrepancyForm = {
      resolution_action: 'update_master',
      resolution_notes: 'Approved asset relocation'
    };

    component.submitResolveDiscrepancy();
    expect(registry.resolveVerificationDiscrepancy).toHaveBeenCalledWith(
      component.companyId,
      testCampaign.id,
      testDiscrepancy.id,
      jasmine.objectContaining({
        resolution_action: 'update_master',
        resolution_notes: 'Approved asset relocation'
      })
    );
    expect(component.resolveDiscrepancyModalOpen).toBeFalse();
    expect(component.successMessage).toContain('Discrepancy resolved');
    expect(registry.listAssets).toHaveBeenCalled();
  });

  it('records an unregistered asset discovered in field', () => {
    component.selectedCampaign = { ...testCampaign, status: 'in_progress' };
    component.openRecordUnregisteredModal();
    expect(component.unregisteredModalOpen).toBeTrue();

    component.unregisteredForm = {
      description: 'Found Projector',
      category_id: 'cat-projectors',
      serial_number: 'PRJ-12345',
      site_id: 'site-1',
      location_id: 'loc-1',
      custodian_id: null,
      observed_condition: 'fair',
      remarks: 'Discovered in storage cupboard'
    };

    component.submitRecordUnregistered();
    expect(registry.recordUnregisteredAsset).toHaveBeenCalledWith(
      component.companyId,
      testCampaign.id,
      jasmine.objectContaining({
        description: 'Found Projector',
        category_id: 'cat-projectors'
      })
    );
    expect(component.unregisteredModalOpen).toBeFalse();
    expect(component.successMessage).toContain('discovery recorded');
  });

  it('registers an unregistered asset into the asset registry', () => {
    component.selectedCampaign = { ...testCampaign, status: 'under_review' };
    component.openRegisterUnregisteredModal(testUnregisteredAsset);
    expect(component.registerUnregisteredModalOpen).toBeTrue();
    expect(component.selectedUnregisteredAsset).toBe(testUnregisteredAsset);

    component.registerUnregisteredForm = {
      asset_number: 'AST-000099',
      cost_center_id: 'cc-1',
      responsible_department_id: 'dept-1',
      acquisition_cost: 500,
      acquisition_date: '2026-10-19',
      resolution_notes: 'Registering found projector'
    };

    component.submitRegisterUnregistered();
    expect(registry.registerUnregisteredAsset).toHaveBeenCalledWith(
      component.companyId,
      testCampaign.id,
      testUnregisteredAsset.id,
      jasmine.objectContaining({
        asset_number: 'AST-000099',
        resolution_notes: 'Registering found projector'
      })
    );
    expect(component.registerUnregisteredModalOpen).toBeFalse();
    expect(component.successMessage).toContain('Asset registered as AST-000099');
    expect(registry.listAssets).toHaveBeenCalled();
  });

  it('loads verification campaign report and generates sanitized CSV export', () => {
    component.selectReport('verification-campaigns');
    expect(registry.reportVerificationCampaigns).toHaveBeenCalledWith(component.companyId, jasmine.any(Object));

    const csv = component.generateReportCsvContent();
    expect(csv).toContain('Campaign Ref');
    expect(csv).toContain('VER-2026-Q4');
    expect(csv).toContain('Q4 IT Verification');
  });

  it('loads verification discrepancies report and generates sanitized CSV export', () => {
    component.selectReport('verification-discrepancies');
    expect(registry.reportVerificationDiscrepancies).toHaveBeenCalledWith(component.companyId, jasmine.any(Object));

    const csv = component.generateReportCsvContent();
    expect(csv).toContain('Discrepancy ID');
    expect(csv).toContain('disc-1');
    expect(csv).toContain('location_mismatch');
  });
});


const testAsset: Asset = {
  id: 'asset-1',
  company_id: 'company-1',
  category_id: 'category-1',
  asset_number: 'AST-000001',
  serial_number: null,
  manufacturer: null,
  model: null,
  acquisition_date: null,
  acquisition_cost: null,
  status: 'in_stock',
  site_id: null,
  location_id: null,
  responsible_department_id: null,
  cost_center_id: null,
  custodian_name: null,
  vendor_reference: null,
  invoice_reference: null,
  warranty_start: null,
  warranty_end: null,
  notes: null
};

const testAssignment: AssetAssignment = {
  id: '',
  company_id: '',
  asset_id: '',
  recipient_id: '',
  recipient_email: '',
  responsible_department_id: null,
  location_id: null,
  effective_date: '2026-10-15',
  status: 'active',
  notes: null,
  reference: null,
  handover_date: null,
  handover_condition: null,
  included_items: null,
  acknowledgement: null,
  handover_notes: null,
  ended_at: null,
  return_date: null,
  return_condition: null,
  return_notes: null,
  issue_details: null,
  next_asset_status: null,
  transfer_reason: null,
  previous_assignment_id: null,
  created_at: '2026-10-15T00:00:00Z'
};

const testMaintenanceRequest: MaintenanceRequest = {
  id: 'request-1',
  company_id: 'company-1',
  asset_id: 'asset-1',
  asset_number: 'AST-000001',
  requester_id: 'admin-1',
  requester_email: 'admin@example.invalid',
  assignee_id: null,
  assignee_email: null,
  title: 'Laptop will not start',
  issue_description: 'Power light flashes and it shuts down.',
  priority: 'high',
  status: 'open',
  reported_date: '2026-10-15',
  diagnosis: null,
  work_performed: null,
  resolution_notes: null,
  completed_date: null,
  cost: null,
  created_at: '2026-10-15T00:00:00Z',
  updated_at: '2026-10-15T00:00:00Z'
};

const testCampaign: VerificationCampaign = {
  id: 'camp-1',
  company_id: 'company-1',
  campaign_reference: 'VER-2026-Q4',
  name: 'Q4 IT Verification',
  description: 'Annual verification',
  status: 'draft',
  start_date: '2026-10-01',
  end_date: '2026-10-31',
  scope_category_ids: null,
  scope_location_ids: null,
  created_by_id: 'admin-1',
  created_by_name: 'Admin',
  started_at: null,
  completed_at: null,
  closed_by_id: null,
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z',
  total_expected: 10,
  total_verified: 8,
  total_unverified: 2,
  total_missing: 1,
  total_discrepancies: 2,
  total_unregistered: 1,
  completion_percentage: 80.0
};

const testExpectedAsset: VerificationExpectedAsset = {
  id: 'exp-1',
  company_id: 'company-1',
  campaign_id: 'camp-1',
  asset_id: 'asset-1',
  asset_number: 'AST-000001',
  category_id: 'cat-1',
  category_name: 'Laptops',
  serial_number: 'SN-001',
  model: 'ThinkPad X1',
  manufacturer: 'Lenovo',
  expected_site_id: null,
  site_name: null,
  expected_location_id: null,
  location_name: 'HQ Room 101',
  expected_department_id: null,
  department_name: 'IT',
  expected_custodian_id: null,
  expected_custodian_name: 'John Doe',
  expected_condition: 'good',
  expected_status: 'in_stock',
  is_verified: false,
  observation_id: null,
  observation_found: null,
  has_discrepancy: false,
  discrepancy_types: [],
  created_at: '2026-10-01T00:00:00Z'
};

const testObservation: VerificationObservation = {
  id: 'obs-1',
  company_id: 'company-1',
  campaign_id: 'camp-1',
  expected_asset_id: 'exp-1',
  asset_id: 'asset-1',
  asset_number: 'AST-000001',
  is_found: true,
  actual_site_id: null,
  actual_site_name: null,
  actual_location_id: null,
  actual_location_name: null,
  actual_department_id: null,
  actual_custodian_id: null,
  actual_custodian_name: null,
  observed_condition: 'good',
  verification_date: '2026-10-19',
  verified_by_id: 'admin-1',
  verified_by_name: 'Admin',
  remarks: 'Found in good shape',
  reference_notes: null,
  created_at: '2026-10-19T00:00:00Z'
};

const testDiscrepancy: VerificationDiscrepancy = {
  id: 'disc-1',
  company_id: 'company-1',
  campaign_id: 'camp-1',
  campaign_reference: 'VER-2026-Q4',
  observation_id: 'obs-1',
  expected_asset_id: 'exp-1',
  asset_id: 'asset-1',
  asset_number: 'AST-000001',
  discrepancy_type: 'location_mismatch',
  status: 'pending',
  expected_data: { location_name: 'HQ Room 101' },
  observed_data: { actual_location_name: 'Server Room B' },
  notes: 'Moved without transfer ticket',
  resolution_action: null,
  resolution_notes: null,
  resolved_by_id: null,
  resolved_by_name: null,
  resolved_at: null,
  created_at: '2026-10-19T00:00:00Z'
};

const testUnregisteredAsset: VerificationUnregisteredAsset = {
  id: 'unreg-1',
  company_id: 'company-1',
  campaign_id: 'camp-1',
  observation_id: null,
  discrepancy_id: null,
  serial_number: 'SN-UNREG-99',
  description: 'Unrecorded Dell Display',
  category_id: 'cat-1',
  category_name: 'Displays',
  site_id: null,
  site_name: null,
  location_id: null,
  location_name: 'Floor 3',
  custodian_id: null,
  custodian_name: null,
  observed_condition: 'good',
  remarks: 'Discovered in storage room',
  status: 'discovered',
  registered_asset_id: null,
  registered_asset_number: null,
  created_at: '2026-10-19T00:00:00Z'
};

const testDashboardSummary: VerificationDashboardSummary = {
  campaign_id: 'camp-1',
  campaign_reference: 'VER-2026-Q4',
  campaign_name: 'Q4 IT Verification',
  status: 'in_progress',
  start_date: '2026-10-01',
  end_date: '2026-10-31',
  total_expected: 10,
  total_verified: 8,
  total_unverified: 2,
  total_missing: 1,
  completion_percentage: 80.0,
  discrepancies_by_type: { location_mismatch: 1 },
  unregistered_count: 1,
  pending_resolutions: 1,
  resolved_resolutions: 0
};

const testFinancial: AssetFinancial = {
  id: 'fin-1',
  company_id: 'company-1',
  asset_id: 'asset-1',
  capitalised_cost: 1200.0,
  currency: 'INR',
  depreciation_method: 'straight_line',
  useful_life_months: 24,
  residual_value: 0.0,
  depreciation_start_date: '2026-01-01',
  accumulated_depreciation: 100.0,
  current_book_value: 1100.0,
  financial_status: 'active',
  created_at: '2026-01-15T00:00:00Z',
  updated_at: '2026-01-15T00:00:00Z'
};

const testScheduleItem: DepreciationScheduleItem = {
  period: '2026-01',
  period_start_date: '2026-01-01',
  period_end_date: '2026-01-31',
  depreciation_amount: 50.0,
  accumulated_depreciation: 50.0,
  book_value: 1150.0,
  status: 'posted'
};

const testDeprecEntry: AssetDepreciationEntry = {
  id: 'entry-1',
  company_id: 'company-1',
  asset_id: 'asset-1',
  period: '2026-01',
  period_start_date: '2026-01-01',
  period_end_date: '2026-01-31',
  depreciation_amount: 50.0,
  accumulated_depreciation_after: 50.0,
  book_value_after: 1150.0,
  method: 'straight_line',
  posted_at: '2026-01-31T23:59:59Z',
  posted_by_id: 'admin-1',
  notes: 'First month depreciation'
};

const testDisposal: AssetDisposal = {
  id: 'disp-1',
  company_id: 'company-1',
  asset_id: 'asset-1',
  disposal_date: '2026-06-30',
  disposal_reason: 'end_of_life',
  disposal_method: 'scrap',
  sale_proceeds: 50.0,
  net_book_value_at_disposal: 1100.0,
  gain_loss: -1050.0,
  notes: 'Scrapped after damage',
  disposed_by_id: 'admin-1',
  created_at: '2026-06-30T10:00:00Z'
};

const testFinancialDashboard: FinancialDashboardMetric = {
  total_capitalised_cost: 1200.0,
  total_accumulated_depreciation: 100.0,
  total_net_book_value: 1100.0,
  approaching_eol_count: 1,
  fully_depreciated_active_count: 0,
  disposed_count: 0,
  total_disposal_proceeds: 0.0,
  total_disposal_gain_loss: 0.0
};

const testDeprecReportItem: AssetDepreciationReportItem = {
  asset_id: 'asset-1',
  asset_number: 'AST-000001',
  asset_name: 'Laptop X1',
  category_name: 'Laptops',
  financial_status: 'active',
  acquisition_date: '2026-01-15',
  capitalised_cost: 1200.0,
  currency: 'INR',
  depreciation_method: 'straight_line',
  useful_life_months: 24,
  residual_value: 0.0,
  depreciation_start_date: '2026-01-01',
  accumulated_depreciation: 100.0,
  current_book_value: 1100.0
};

const testDisposalReportItem: AssetDisposalReportItem = {
  asset_id: 'asset-1',
  asset_number: 'AST-000001',
  asset_name: 'Laptop X1',
  category_name: 'Laptops',
  disposal_date: '2026-06-30',
  disposal_reason: 'end_of_life',
  disposal_method: 'scrap',
  sale_proceeds: 50.0,
  net_book_value_at_disposal: 1100.0,
  gain_loss: -1050.0,
  disposed_by_email: 'admin@example.invalid',
  notes: 'Scrapped after damage'
};

describe('RegistryComponent Asset Financial Lifecycle', () => {
  let fixture: ComponentFixture<RegistryComponent>;
  let component: RegistryComponent;
  let registry: jasmine.SpyObj<RegistryService>;
  let permissions: Set<string>;

  const company: Company = {
    id: 'company-1',
    code: 'ACME',
    name: 'Acme',
    is_active: true
  };

  beforeEach(() => {
    permissions = new Set(['company.read', 'asset.read', 'finance.read', 'finance.manage', 'dashboard.read']);
    registry = jasmine.createSpyObj<RegistryService>('RegistryService', [
      'companies',
      'listMaster',
      'listNumberRules',
      'companyMembers',
      'companyRoles',
      'listAssets',
      'downloadAssetImportTemplate',
      'previewAssetImport',
      'confirmAssetImport',
      'getAsset',
      'lookupAsset',
      'usages',
      'history',
      'assignments',
      'assignmentRecipients',
      'createAssignment',
      'recordHandover',
      'returnAssignment',
      'transferAssignment',
      'listLocations',
      'suppliers',
      'purchaseOrders',
      'getPurchaseOrder',
      'goodsReceipts',
      'serviceContracts',
      'maintenanceUsers',
      'maintenanceRequests',
      'dashboard',
      'reportAssetRegister',
      'reportAssetAllocation',
      'reportWarrantyExpiry',
      'reportMaintenance',
      'reportProcurement',
      'listVerificationCampaigns',
      'getVerificationCampaign',
      'createVerificationCampaign',
      'updateVerificationCampaign',
      'transitionVerificationCampaignStatus',
      'getVerificationExpectedAssets',
      'recordVerificationObservation',
      'getVerificationDiscrepancies',
      'resolveVerificationDiscrepancy',
      'recordUnregisteredAsset',
      'getUnregisteredAssets',
      'registerUnregisteredAsset',
      'getVerificationDashboard',
      'reportVerificationCampaigns',
      'reportVerificationDiscrepancies',
      'getAssetFinancial',
      'configureAssetFinancial',
      'editAssetFinancial',
      'adjustAssetFinancial',
      'getDepreciationSchedule',
      'postDepreciation',
      'listDepreciationEntries',
      'postBatchDepreciation',
      'disposeAsset',
      'getAssetDisposal',
      'reportAssetDepreciation',
      'reportAssetDisposals',
      'getFinancialDashboard',
      'listAlerts',
      'getAlertSummary',
      'syncAlerts',
      'acknowledgeAlert',
      'assignAlert',
      'resolveAlert',
      'dismissAlert',
      'getLastAlertJob',
      'getNotifications',
      'getUnreadNotificationCount',
      'markNotificationRead',
      'markAllNotificationsRead'
    ]);

    registry.getLastAlertJob.and.returnValue(of(null));
    registry.getNotifications.and.returnValue(of([]));
    registry.getUnreadNotificationCount.and.returnValue(of({ unread_count: 0 }));
    registry.markNotificationRead.and.returnValue(of({} as any));
    registry.markAllNotificationsRead.and.returnValue(of({ unread_count: 0 }));

    registry.companies.and.returnValue(of([company]));
    registry.listMaster.and.returnValue(of([]));
    registry.listNumberRules.and.returnValue(of([]));
    registry.companyMembers.and.returnValue(of([]));
    registry.companyRoles.and.returnValue(of([]));
    registry.listAssets.and.returnValue(of({ items: [testAsset], total: 1, page: 1, page_size: 15 }));
    registry.getAsset.and.returnValue(of(testAsset));
    registry.lookupAsset.and.returnValue(of(testAsset));
    registry.usages.and.returnValue(of([]));
    registry.history.and.returnValue(of([]));
    registry.assignments.and.returnValue(of([]));
    registry.assignmentRecipients.and.returnValue(of([]));
    registry.listLocations.and.returnValue(of([]));
    registry.suppliers.and.returnValue(of([]));
    registry.purchaseOrders.and.returnValue(of([]));
    registry.getPurchaseOrder.and.returnValue(of({} as any));
    registry.goodsReceipts.and.returnValue(of([]));
    registry.serviceContracts.and.returnValue(of([]));
    registry.maintenanceUsers.and.returnValue(of([]));
    registry.maintenanceRequests.and.returnValue(of([]));
    registry.dashboard.and.returnValue(of({
      total_assets: 1,
      assets_by_status: { in_stock: 1 },
      assets_by_category: [],
      assets_by_site: [],
      assets_by_department: [],
      expiring_contracts_count: 0,
      expiring_contracts: [],
      maintenance_summary: { open: 0, in_progress: 0, resolved: 0, closed: 0, total_open_and_in_progress: 0 },
      procurement_summary: { total_purchase_orders: 0, orders_by_status: {}, total_goods_receipts: 0, total_items_received: 0, total_items_rejected: 0 },
      recent_activity: []
    }));
    registry.reportAssetRegister.and.returnValue(of([]));
    registry.reportAssetAllocation.and.returnValue(of([]));
    registry.reportWarrantyExpiry.and.returnValue(of([]));
    registry.reportMaintenance.and.returnValue(of([]));
    registry.reportProcurement.and.returnValue(of([]));

    registry.listVerificationCampaigns.and.returnValue(of([]));
    registry.getVerificationCampaign.and.returnValue(of({} as any));
    registry.createVerificationCampaign.and.returnValue(of({} as any));
    registry.updateVerificationCampaign.and.returnValue(of({} as any));
    registry.transitionVerificationCampaignStatus.and.returnValue(of({} as any));
    registry.getVerificationExpectedAssets.and.returnValue(of([]));
    registry.recordVerificationObservation.and.returnValue(of({} as any));
    registry.getVerificationDiscrepancies.and.returnValue(of([]));
    registry.resolveVerificationDiscrepancy.and.returnValue(of({} as any));
    registry.recordUnregisteredAsset.and.returnValue(of({} as any));
    registry.getUnregisteredAssets.and.returnValue(of([]));
    registry.registerUnregisteredAsset.and.returnValue(of({} as any));
    registry.getVerificationDashboard.and.returnValue(of({} as any));
    registry.reportVerificationCampaigns.and.returnValue(of([]));
    registry.reportVerificationDiscrepancies.and.returnValue(of([]));

    registry.getAssetFinancial.and.returnValue(of(testFinancial));
    registry.configureAssetFinancial.and.returnValue(of(testFinancial));
    registry.editAssetFinancial.and.returnValue(of(testFinancial));
    registry.adjustAssetFinancial.and.returnValue(of({ ...testFinancial, useful_life_months: 48 }));
    registry.getDepreciationSchedule.and.returnValue(of([testScheduleItem]));
    registry.postDepreciation.and.returnValue(of(testDeprecEntry));
    registry.listDepreciationEntries.and.returnValue(of([testDeprecEntry]));
    registry.postBatchDepreciation.and.returnValue(of({
      period: '2026-02',
      processed_count: 1,
      posted_count: 1,
      skipped_count: 0,
      total_depreciation_posted: 50.0,
      posted_asset_ids: ['asset-1'],
      skipped: []
    }));
    registry.disposeAsset.and.returnValue(of(testDisposal));
    registry.getAssetDisposal.and.returnValue(of(testDisposal));
    registry.reportAssetDepreciation.and.returnValue(of([testDeprecReportItem]));
    registry.reportAssetDisposals.and.returnValue(of([testDisposalReportItem]));
    registry.getFinancialDashboard.and.returnValue(of(testFinancialDashboard));

    registry.listAlerts.and.returnValue(of([]));
    registry.getAlertSummary.and.returnValue(of(defaultAlertSummary));
    registry.syncAlerts.and.returnValue(of(defaultAlertSyncResponse));
    registry.acknowledgeAlert.and.returnValue(of({} as any));
    registry.assignAlert.and.returnValue(of({} as any));
    registry.resolveAlert.and.returnValue(of({} as any));
    registry.dismissAlert.and.returnValue(of({} as any));

    TestBed.configureTestingModule({
      imports: [RegistryComponent],
      providers: [
        provideHttpClient(),
        provideRouter([]),
        { provide: RegistryService, useValue: registry },
        {
          provide: AuthService,
          useValue: {
            currentUser: signal({ id: 'admin-1', email: 'admin@example.invalid', system_permissions: [], memberships: [] }),
            permissions: () => new Set(permissions)
          }
        }
      ]
    });

    fixture = TestBed.createComponent(RegistryComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should load asset financial profile, depreciation schedule, and entries when opening an asset', () => {
    component.openAsset(testAsset);

    expect(registry.getAssetFinancial).toHaveBeenCalledWith('company-1', testAsset.id);
    expect(registry.getDepreciationSchedule).toHaveBeenCalledWith('company-1', testAsset.id);
    expect(registry.listDepreciationEntries).toHaveBeenCalledWith('company-1', testAsset.id);
    expect(component.activeAssetFinancial).toEqual(testFinancial);
    expect(component.activeAssetSchedule.length).toBe(1);
    expect(component.activeAssetDeprecEntries.length).toBe(1);
    expect(component.depreciationPercentage(component.activeAssetFinancial)).toBeGreaterThan(0);
  });

  it('should open configure financial modal and submit new financial profile', () => {
    component.selectedAsset = testAsset;
    component.openConfigureFinancialModal();

    expect(component.configureFinancialModalOpen).toBeTrue();
    expect(component.configureFinancialForm.currency).toBe('INR');

    component.configureFinancialForm.useful_life_months = 36;
    component.submitConfigureFinancial();

    expect(registry.configureAssetFinancial).toHaveBeenCalledWith('company-1', testAsset.id, jasmine.objectContaining({
      useful_life_months: 36
    }));
    expect(component.configureFinancialModalOpen).toBeFalse();
    expect(component.successMessage).toContain('Financial profile configured');
  });

  it('should open adjust financial modal and submit prospective adjustment', () => {
    component.selectedAsset = testAsset;
    component.activeAssetFinancial = testFinancial;
    component.openAdjustFinancialModal();

    expect(component.adjustFinancialModalOpen).toBeTrue();

    component.adjustFinancialForm.useful_life_months = 48;
    component.adjustFinancialForm.notes = 'Extended operational warranty';
    component.submitAdjustFinancial();

    expect(registry.adjustAssetFinancial).toHaveBeenCalledWith('company-1', testAsset.id, jasmine.objectContaining({
      useful_life_months: 48,
      notes: 'Extended operational warranty'
    }));
    expect(component.adjustFinancialModalOpen).toBeFalse();
    expect(component.successMessage).toContain('adjusted prospectively');
  });

  it('should post monthly depreciation entry', () => {
    registry.postDepreciation.and.returnValue(of({ ...testDeprecEntry, period: '2026-02' }));
    component.selectedAsset = testAsset;
    component.activeAssetFinancial = testFinancial;
    component.openPostDepreciationModal('2026-02');

    expect(component.postDepreciationModalOpen).toBeTrue();
    expect(component.postDepreciationForm.period).toBe('2026-02');

    component.submitPostDepreciation();

    expect(registry.postDepreciation).toHaveBeenCalledWith('company-1', testAsset.id, jasmine.objectContaining({
      period: '2026-02'
    }));
    expect(component.postDepreciationModalOpen).toBeFalse();
    expect(component.successMessage).toContain('Depreciation posted for period 2026-02');
  });

  it('should execute batch depreciation run across company assets', () => {
    component.openBatchDepreciationModal();

    expect(component.batchDepreciationModalOpen).toBeTrue();

    component.batchDepreciationForm.period = '2026-02';
    component.submitBatchDepreciation();

    expect(registry.postBatchDepreciation).toHaveBeenCalledWith('company-1', jasmine.objectContaining({
      period: '2026-02'
    }));
    expect(component.batchDepreciationResult?.posted_count).toBe(1);
    expect(component.successMessage).toContain('Batch run for 2026-02');
  });

  it('should open dispose asset modal and submit disposal', () => {
    component.selectedAsset = testAsset;
    component.activeAssetFinancial = testFinancial;
    component.openDisposeAssetModal();

    expect(component.disposeAssetModalOpen).toBeTrue();

    component.disposeAssetForm.sale_proceeds = 50.0;
    component.submitDisposeAsset();

    expect(registry.disposeAsset).toHaveBeenCalledWith('company-1', testAsset.id, jasmine.objectContaining({
      sale_proceeds: 50.0
    }));
    expect(component.disposeAssetModalOpen).toBeFalse();
    expect(component.successMessage).toContain('disposed');
  });

  it('should load financial dashboard metrics on dashboard view', () => {
    component.setView('dashboard');

    expect(registry.getFinancialDashboard).toHaveBeenCalledWith('company-1');
    expect(component.financialDashboard).toEqual(testFinancialDashboard);
  });

  it('should load asset-depreciation and asset-disposals reports and generate valid CSV', () => {
    component.selectReport('asset-depreciation');

    expect(registry.reportAssetDepreciation).toHaveBeenCalledWith('company-1', jasmine.any(Object));
    expect(component.assetDepreciationReport.length).toBe(1);

    const depCsv = component.generateReportCsvContent();
    expect(depCsv).toContain('AST-000001');
    expect(depCsv).toContain('Capitalised Cost');

    component.selectReport('asset-disposals');

    expect(registry.reportAssetDisposals).toHaveBeenCalledWith('company-1', jasmine.any(Object));
    expect(component.assetDisposalReport.length).toBe(1);

    const dispCsv = component.generateReportCsvContent();
    expect(dispCsv).toContain('AST-000001');
    expect(dispCsv).toContain('NBV at Disposal');
  });
});

const testAlert: AssetAlert = {
  id: 'alert-1',
  company_id: 'company-1',
  alert_type: 'warranty_expiry',
  severity: 'warning',
  status: 'open',
  title: 'Warranty Expiring Soon',
  description: 'Warranty expires in 15 days',
  entity_type: 'asset_service_contract',
  entity_id: 'contract-1',
  entity_reference: 'WAR-001',
  asset_id: 'asset-1',
  due_date: '2026-11-05',
  days_overdue: 0,
  responsible_user_id: null,
  target_route: 'assets',
  acknowledged_at: null,
  acknowledged_by_id: null,
  resolved_at: null,
  resolved_by_id: null,
  resolution_reason: null,
  resolution_notes: null,
  created_at: '2026-10-19T10:00:00Z',
  updated_at: '2026-10-19T10:00:00Z'
};

const testAlertSummary: AssetAlertSummary = {
  total_open: 3,
  total_acknowledged: 1,
  total_resolved: 2,
  total_dismissed: 0,
  critical_count: 1,
  warning_count: 2,
  info_count: 1,
  by_type: {
    warranty_expiry: 1,
    maintenance_overdue: 1,
    verification_discrepancy: 1,
    approaching_eol: 1
  }
};

describe('RegistryComponent Asset Lifecycle Alerts and Action Centre', () => {
  let fixture: ComponentFixture<RegistryComponent>;
  let component: RegistryComponent;
  let registry: jasmine.SpyObj<RegistryService>;
  let permissions: Set<string>;

  const company: Company = {
    id: 'company-1',
    code: 'ACME',
    name: 'Acme',
    is_active: true
  };

  beforeEach(() => {
    permissions = new Set([
      'company.read',
      'asset.read',
      'alerts.read',
      'alerts.manage',
      'maintenance.read',
      'verification.read',
      'procurement.read'
    ]);

    registry = jasmine.createSpyObj<RegistryService>('RegistryService', [
      'companies',
      'listMaster',
      'listNumberRules',
      'companyMembers',
      'companyRoles',
      'listAssets',
      'downloadAssetImportTemplate',
      'previewAssetImport',
      'confirmAssetImport',
      'getAsset',
      'lookupAsset',
      'usages',
      'history',
      'assignments',
      'assignmentRecipients',
      'createAssignment',
      'recordHandover',
      'returnAssignment',
      'transferAssignment',
      'listLocations',
      'suppliers',
      'purchaseOrders',
      'getPurchaseOrder',
      'goodsReceipts',
      'serviceContracts',
      'maintenanceUsers',
      'maintenanceRequests',
      'dashboard',
      'reportAssetRegister',
      'reportAssetAllocation',
      'reportWarrantyExpiry',
      'reportMaintenance',
      'reportProcurement',
      'listVerificationCampaigns',
      'getVerificationCampaign',
      'createVerificationCampaign',
      'updateVerificationCampaign',
      'transitionVerificationCampaignStatus',
      'getVerificationExpectedAssets',
      'recordVerificationObservation',
      'getVerificationDiscrepancies',
      'resolveVerificationDiscrepancy',
      'recordUnregisteredAsset',
      'getUnregisteredAssets',
      'registerUnregisteredAsset',
      'getVerificationDashboard',
      'reportVerificationCampaigns',
      'reportVerificationDiscrepancies',
      'getAssetFinancial',
      'configureAssetFinancial',
      'editAssetFinancial',
      'adjustAssetFinancial',
      'getDepreciationSchedule',
      'postDepreciation',
      'listDepreciationEntries',
      'postBatchDepreciation',
      'disposeAsset',
      'getAssetDisposal',
      'reportAssetDepreciation',
      'reportAssetDisposals',
      'getFinancialDashboard',
      'listAlerts',
      'getAlertSummary',
      'syncAlerts',
      'acknowledgeAlert',
      'assignAlert',
      'resolveAlert',
      'dismissAlert',
      'getLastAlertJob',
      'getNotifications',
      'getUnreadNotificationCount',
      'markNotificationRead',
      'markAllNotificationsRead'
    ]);

    registry.getLastAlertJob.and.returnValue(of(null));
    registry.getNotifications.and.returnValue(of([]));
    registry.getUnreadNotificationCount.and.returnValue(of({ unread_count: 0 }));
    registry.markNotificationRead.and.returnValue(of({} as any));
    registry.markAllNotificationsRead.and.returnValue(of({ unread_count: 0 }));

    registry.companies.and.returnValue(of([company]));
    registry.listMaster.and.returnValue(of([]));
    registry.listNumberRules.and.returnValue(of([]));
    registry.companyMembers.and.returnValue(of([]));
    registry.companyRoles.and.returnValue(of([]));
    registry.listAssets.and.returnValue(of({ items: [testAsset], total: 1, page: 1, page_size: 15 }));
    registry.getAsset.and.returnValue(of(testAsset));
    registry.lookupAsset.and.returnValue(of(testAsset));
    registry.usages.and.returnValue(of([]));
    registry.history.and.returnValue(of([]));
    registry.assignments.and.returnValue(of([]));
    registry.assignmentRecipients.and.returnValue(of([{ id: 'user-2', email: 'tech@mindzen.invalid' }]));
    registry.listLocations.and.returnValue(of([]));
    registry.suppliers.and.returnValue(of([]));
    registry.purchaseOrders.and.returnValue(of([]));
    registry.getPurchaseOrder.and.returnValue(of({} as any));
    registry.goodsReceipts.and.returnValue(of([]));
    registry.serviceContracts.and.returnValue(of([]));
    registry.maintenanceUsers.and.returnValue(of([]));
    registry.maintenanceRequests.and.returnValue(of([]));
    registry.dashboard.and.returnValue(of({} as any));
    registry.reportAssetRegister.and.returnValue(of([]));
    registry.reportAssetAllocation.and.returnValue(of([]));
    registry.reportWarrantyExpiry.and.returnValue(of([]));
    registry.reportMaintenance.and.returnValue(of([]));
    registry.reportProcurement.and.returnValue(of([]));
    registry.listVerificationCampaigns.and.returnValue(of([]));
    registry.getVerificationCampaign.and.returnValue(of({} as any));
    registry.createVerificationCampaign.and.returnValue(of({} as any));
    registry.updateVerificationCampaign.and.returnValue(of({} as any));
    registry.transitionVerificationCampaignStatus.and.returnValue(of({} as any));
    registry.getVerificationExpectedAssets.and.returnValue(of([]));
    registry.recordVerificationObservation.and.returnValue(of({} as any));
    registry.getVerificationDiscrepancies.and.returnValue(of([]));
    registry.resolveVerificationDiscrepancy.and.returnValue(of({} as any));
    registry.recordUnregisteredAsset.and.returnValue(of({} as any));
    registry.getUnregisteredAssets.and.returnValue(of([]));
    registry.registerUnregisteredAsset.and.returnValue(of({} as any));
    registry.getVerificationDashboard.and.returnValue(of({} as any));
    registry.reportVerificationCampaigns.and.returnValue(of([]));
    registry.reportVerificationDiscrepancies.and.returnValue(of([]));
    registry.getAssetFinancial.and.returnValue(of(undefined as any));
    registry.configureAssetFinancial.and.returnValue(of({} as any));
    registry.editAssetFinancial.and.returnValue(of({} as any));
    registry.adjustAssetFinancial.and.returnValue(of({} as any));
    registry.getDepreciationSchedule.and.returnValue(of([]));
    registry.postDepreciation.and.returnValue(of({} as any));
    registry.listDepreciationEntries.and.returnValue(of([]));
    registry.postBatchDepreciation.and.returnValue(of({ period: '2026-10', processed_count: 0, posted_count: 0, skipped_count: 0, total_depreciation_posted: 0, posted_asset_ids: [], skipped: [] }));
    registry.disposeAsset.and.returnValue(of({} as any));
    registry.getAssetDisposal.and.returnValue(of({} as any));
    registry.reportAssetDepreciation.and.returnValue(of([]));
    registry.reportAssetDisposals.and.returnValue(of([]));
    registry.getFinancialDashboard.and.returnValue(of({} as any));

    registry.listAlerts.and.returnValue(of([testAlert]));
    registry.getAlertSummary.and.returnValue(of(testAlertSummary));
    registry.syncAlerts.and.returnValue(of({
      synced: true,
      created_count: 1,
      updated_count: 0,
      auto_resolved_count: 0,
      active_count: 1
    }));
    registry.acknowledgeAlert.and.returnValue(of({ ...testAlert, status: 'acknowledged' }));
    registry.assignAlert.and.returnValue(of({ ...testAlert, responsible_user_id: 'user-2' }));
    registry.resolveAlert.and.returnValue(of({ ...testAlert, status: 'resolved', resolution_reason: 'manual_resolution' }));
    registry.dismissAlert.and.returnValue(of({ ...testAlert, status: 'dismissed' }));

    TestBed.configureTestingModule({
      imports: [RegistryComponent],
      providers: [
        provideHttpClient(),
        provideRouter([]),
        { provide: RegistryService, useValue: registry },
        {
          provide: AuthService,
          useValue: {
            currentUser: signal({ id: 'admin-1', email: 'admin@example.invalid', system_permissions: [], memberships: [] }),
            permissions: () => new Set(permissions)
          }
        }
      ]
    });

    fixture = TestBed.createComponent(RegistryComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should display Action Centre tab badge with critical count when critical alerts exist', () => {
    const badge = fixture.nativeElement.querySelector('.alerts-tab-btn .tab-badge');
    expect(badge).toBeTruthy();
    expect(badge.textContent.trim()).toBe('1');
    expect(badge.classList).toContain('badge-critical');
  });

  it('should load alerts and summary when switching to alerts view', () => {
    component.setView('alerts');
    fixture.detectChanges();
    expect(component.activeView).toBe('alerts');
    expect(registry.listAlerts).toHaveBeenCalledWith('company-1', jasmine.objectContaining({ status: 'open' }));
    expect(component.alerts.length).toBe(1);
    expect(component.alerts[0].id).toBe('alert-1');
    expect(component.alertSummary).toEqual(testAlertSummary);
  });

  it('should trigger alert synchronization and update alert list and success message', () => {
    component.setView('alerts');
    component.syncAlertsNow();

    expect(registry.syncAlerts).toHaveBeenCalledWith('company-1');
    expect(component.successMessage).toContain('Alert evaluation complete');
    expect(registry.listAlerts).toHaveBeenCalled();
  });

  it('should apply filters and reload alerts with selected criteria', () => {
    component.setView('alerts');
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
    component.openAlertModal('acknowledge', testAlert);
    expect(component.activeAlertModal).toBe('acknowledge');
    expect(component.currentAlert).toBe(testAlert);

    component.alertNotes = 'Awaiting renewal quote';
    component.submitAlertAcknowledge();

    expect(registry.acknowledgeAlert).toHaveBeenCalledWith('company-1', testAlert.id, 'Awaiting renewal quote');
    expect(component.activeAlertModal).toBeNull();
    expect(component.successMessage).toContain('acknowledged');
  });

  it('should open assign modal and submit alert assignment to a user', () => {
    component.openAlertModal('assign', testAlert);
    expect(component.activeAlertModal).toBe('assign');

    component.alertAssigneeId = 'user-2';
    component.submitAlertAssign();

    expect(registry.assignAlert).toHaveBeenCalledWith('company-1', testAlert.id, 'user-2');
    expect(component.activeAlertModal).toBeNull();
    expect(component.successMessage).toContain('assigned');
  });

  it('should open resolve modal and submit alert resolution with reason and notes', () => {
    component.openAlertModal('resolve', testAlert);
    expect(component.activeAlertModal).toBe('resolve');

    component.alertResolutionReason = 'manual_resolution';
    component.alertNotes = 'Contract renewal executed';
    component.submitAlertResolve();

    expect(registry.resolveAlert).toHaveBeenCalledWith('company-1', testAlert.id, 'Contract renewal executed', 'manual_resolution');
    expect(component.activeAlertModal).toBeNull();
    expect(component.successMessage).toContain('resolved');
  });

  it('should open dismiss modal and submit alert dismissal with reason', () => {
    component.openAlertModal('dismiss', testAlert);
    expect(component.activeAlertModal).toBe('dismiss');

    component.alertNotes = 'Risk accepted by operations';
    component.submitAlertDismiss();

    expect(registry.dismissAlert).toHaveBeenCalledWith('company-1', testAlert.id, 'Risk accepted by operations');
    expect(component.activeAlertModal).toBeNull();
    expect(component.successMessage).toContain('dismissed');
  });

  it('should route to the appropriate application entity when clicking alert target', () => {
    // Asset target
    component.goToAlertTarget({ ...testAlert, target_route: 'assets', asset_id: testAsset.id });
    expect(component.activeView).toBe('assets');
    expect(registry.getAsset).toHaveBeenCalledWith('company-1', testAsset.id);

    // Maintenance target
    component.goToAlertTarget({ ...testAlert, target_route: 'maintenance' });
    expect(component.activeView).toBe('maintenance');

    // Verification target
    component.goToAlertTarget({ ...testAlert, target_route: 'verification' });
    expect(component.activeView).toBe('verification');

    // Procurement target
    component.goToAlertTarget({ ...testAlert, target_route: 'procurement' });
    expect(component.activeView).toBe('procurement');
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
    expect(component.formatAlertType('custom_type')).toBe('custom type');
  });

  describe('Action Centre Single-Owner HTTP Request Deduplication (F-01)', () => {
    it('should produce exactly one initial set of alert-list, summary and last-job requests when entering alerts view', () => {
      registry.listAlerts.calls.reset();
      registry.getAlertSummary.calls.reset();
      registry.getLastAlertJob.calls.reset();

      component.setView('alerts');
      fixture.detectChanges();

      expect(component.activeView).toBe('alerts');
      expect(component.actionCentre).toBeDefined();
      expect(registry.listAlerts.calls.count()).toBe(1);
      expect(registry.getAlertSummary.calls.count()).toBe(1);
      expect(registry.getLastAlertJob.calls.count()).toBe(1);
      expect(registry.listAlerts).toHaveBeenCalledWith('company-1', jasmine.objectContaining({ status: 'open' }));
    });

    it('should delegate to ActionCentreComponent when parent loadAlerts is called without duplicate requests', () => {
      component.setView('alerts');
      fixture.detectChanges();

      registry.listAlerts.calls.reset();
      registry.getAlertSummary.calls.reset();
      registry.getLastAlertJob.calls.reset();

      component.loadAlerts();

      expect(registry.listAlerts.calls.count()).toBe(1);
      expect(registry.getAlertSummary.calls.count()).toBe(1);
      expect(registry.getLastAlertJob.calls.count()).toBe(1);
    });

    it('should refresh alerts exactly once for the new company on company change', () => {
      component.setView('alerts');
      fixture.detectChanges();

      registry.listAlerts.calls.reset();
      registry.getAlertSummary.calls.reset();
      registry.getLastAlertJob.calls.reset();

      component.companyId = 'company-2';
      component.loadAlerts();
      fixture.detectChanges();

      const comp2AlertCalls = registry.listAlerts.calls.allArgs().filter(args => args[0] === 'company-2');
      expect(comp2AlertCalls.length).toBe(1);

      const comp2SummaryCalls = registry.getAlertSummary.calls.allArgs().filter(args => args[0] === 'company-2');
      expect(comp2SummaryCalls.length).toBe(1);

      const comp2JobCalls = registry.getLastAlertJob.calls.allArgs().filter(args => args[0] === 'company-2');
      expect(comp2JobCalls.length).toBe(1);
    });

    it('should execute explicit syncAlertsNow via delegation and refresh once', () => {
      component.setView('alerts');
      fixture.detectChanges();

      registry.syncAlerts.calls.reset();
      registry.listAlerts.calls.reset();

      component.syncAlertsNow();

      expect(registry.syncAlerts.calls.count()).toBe(1);
      expect(registry.syncAlerts).toHaveBeenCalledWith('company-1');
      expect(registry.listAlerts.calls.count()).toBe(1);
    });

    it('should update parent summary and tab badge when child emits summaryChange', () => {
      component.setView('alerts');
      fixture.detectChanges();

      const updatedSummary: AssetAlertSummary = {
        total_open: 5,
        total_acknowledged: 2,
        total_resolved: 10,
        total_dismissed: 1,
        critical_count: 4,
        warning_count: 1,
        info_count: 0,
        by_type: { warranty_expiry: 4, maintenance_overdue: 1 }
      };

      component.actionCentre!.summaryChange.emit(updatedSummary);
      fixture.detectChanges();

      expect(component.alertSummary).toEqual(updatedSummary);
      const badge = fixture.nativeElement.querySelector('.alerts-tab-btn .tab-badge');
      expect(badge).toBeTruthy();
      expect(badge.textContent.trim()).toBe('4');
      expect(badge.classList).toContain('badge-critical');
    });

    it('should safely execute loadAlerts fallback when ActionCentre child is not mounted', () => {
      component.setView('dashboard');
      fixture.detectChanges();

      expect(component.actionCentre).toBeUndefined();

      registry.listAlerts.calls.reset();
      registry.getAlertSummary.calls.reset();
      registry.getLastAlertJob.calls.reset();

      expect(() => component.loadAlerts()).not.toThrow();
      expect(registry.listAlerts.calls.count()).toBe(1);
      expect(registry.getAlertSummary.calls.count()).toBe(1);
      expect(component.alerts.length).toBe(1);
    });
  });

  describe('Scheduled Automation and Notifications', () => {
    const mockNotifications: InAppNotification[] = [
      {
        id: 'notif-1',
        company_id: 'company-1',
        recipient_user_id: 'user-1',
        notification_type: 'alert_critical',
        title: 'Critical Warranty Expiry: AST-001',
        message: 'Warranty contract expired 10 days ago',
        severity: 'critical',
        entity_type: 'asset_alert',
        entity_id: 'alert-1',
        target_route: 'alerts',
        status: 'unread',
        read_at: null,
        created_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
        updated_at: new Date(Date.now() - 5 * 60 * 1000).toISOString()
      },
      {
        id: 'notif-2',
        company_id: 'company-1',
        recipient_user_id: 'user-1',
        notification_type: 'alert_assigned',
        title: 'Alert Assigned: PO Overdue',
        message: 'You have been assigned to handle this alert',
        severity: 'warning',
        entity_type: 'asset_alert',
        entity_id: 'alert-2',
        target_route: 'procurement',
        status: 'read',
        read_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
        created_at: new Date(Date.now() - 120 * 60 * 1000).toISOString(),
        updated_at: new Date(Date.now() - 60 * 60 * 1000).toISOString()
      }
    ];

    it('should load unread notification count on initialization', () => {
      registry.getUnreadNotificationCount.and.returnValue(of({ unread_count: 3 }));
      component.loadNotificationCount();
      expect(component.unreadNotificationCount).toBe(3);
      expect(registry.getUnreadNotificationCount).toHaveBeenCalledWith('company-1');
    });

    it('should toggle notification panel and fetch notifications', () => {
      registry.getNotifications.and.returnValue(of(mockNotifications));
      expect(component.showNotificationPanel).toBeFalse();

      component.toggleNotificationPanel();
      expect(component.showNotificationPanel).toBeTrue();
      expect(component.notifications.length).toBe(2);
      expect(component.unreadNotificationCount).toBe(1);

      component.toggleNotificationPanel();
      expect(component.showNotificationPanel).toBeFalse();
    });

    it('should filter notifications by unread vs all', () => {
      component.notifications = [...mockNotifications];
      component.setNotificationFilter('unread');
      expect(component.filteredNotifications.length).toBe(1);
      expect(component.filteredNotifications[0].id).toBe('notif-1');

      component.setNotificationFilter('all');
      expect(component.filteredNotifications.length).toBe(2);
    });

    it('should mark notification as read and decrement unread counter', () => {
      const targetNotif = { ...mockNotifications[0] };
      component.notifications = [targetNotif];
      component.unreadNotificationCount = 1;

      registry.markNotificationRead.and.returnValue(
        of({ ...targetNotif, status: 'read', read_at: '2026-10-19T21:00:00Z' })
      );

      component.markNotificationAsRead(targetNotif);
      expect(registry.markNotificationRead).toHaveBeenCalledWith(targetNotif.id);
      expect(targetNotif.status).toBe('read');
      expect(targetNotif.read_at).toBe('2026-10-19T21:00:00Z');
      expect(component.unreadNotificationCount).toBe(0);
    });

    it('should mark all notifications as read', () => {
      component.notifications = [
        { ...mockNotifications[0], status: 'unread' },
        { ...mockNotifications[1], status: 'unread' }
      ];
      component.unreadNotificationCount = 2;

      registry.markAllNotificationsRead.and.returnValue(of({ unread_count: 0 }));

      component.markAllNotificationsRead();
      expect(registry.markAllNotificationsRead).toHaveBeenCalledWith('company-1');
      expect(component.unreadNotificationCount).toBe(0);
      expect(component.notifications.every((n) => n.status === 'read')).toBeTrue();
    });

    it('should navigate to target route without altering or resolving underlying alert', () => {
      component.showNotificationPanel = true;
      component.goToNotificationTarget(mockNotifications[0]);

      expect(component.showNotificationPanel).toBeFalse();
      expect(component.activeView).toBe('alerts');
      expect(registry.resolveAlert).not.toHaveBeenCalled();
      expect(registry.acknowledgeAlert).not.toHaveBeenCalled();
      expect(registry.dismissAlert).not.toHaveBeenCalled();

      // Navigation to assets
      component.goToNotificationTarget({ ...mockNotifications[0], target_route: 'assets' });
      expect(component.activeView).toBe('assets');

      // Navigation to procurement
      component.goToNotificationTarget({ ...mockNotifications[0], target_route: 'procurement' });
      expect(component.activeView).toBe('procurement');

      // Navigation to maintenance
      component.goToNotificationTarget({ ...mockNotifications[0], target_route: 'maintenance' });
      expect(component.activeView).toBe('maintenance');

      // Navigation to verification
      component.goToNotificationTarget({ ...mockNotifications[0], target_route: 'verification' });
      expect(component.activeView).toBe('verification');
    });

    it('should load and record last scheduled job execution', () => {
      const mockJob: ScheduledJobExecution = {
        id: 'job-exec-1',
        job_name: 'alert_lifecycle_sync',
        status: 'completed',
        started_at: '2026-10-19T20:00:00Z',
        last_heartbeat_at: '2026-10-19T20:01:00Z',
        completed_at: '2026-10-19T20:01:05Z',
        duration_ms: 65000,
        total_companies_processed: 3,
        alerts_created: 2,
        alerts_updated: 5,
        alerts_auto_resolved: 1,
        error_message: null,
        node_id: 'prod-worker-1',
        created_at: '2026-10-19T20:00:00Z'
      };

      registry.getLastAlertJob.and.returnValue(of(mockJob));
      component.loadLastAlertJob();

      expect(registry.getLastAlertJob).toHaveBeenCalledWith('company-1');
      expect(component.lastScheduledJob).toEqual(mockJob);
      expect(component.lastScheduledJob?.status).toBe('completed');
      expect(component.lastScheduledJob?.total_companies_processed).toBe(3);
    });

    it('should format relative timestamps accurately', () => {
      expect(component.formatTimeAgo(null)).toBe('');
      expect(component.formatTimeAgo(new Date().toISOString())).toBe('just now');

      const fiveMinsAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString();
      expect(component.formatTimeAgo(fiveMinsAgo)).toBe('5m ago');

      const twoHoursAgo = new Date(Date.now() - 2 * 3600 * 1000).toISOString();
      expect(component.formatTimeAgo(twoHoursAgo)).toBe('2h ago');

      const threeDaysAgo = new Date(Date.now() - 3 * 86400 * 1000).toISOString();
      expect(component.formatTimeAgo(threeDaysAgo)).toBe('3d ago');
    });
  });

  describe('Bulk Asset Import Integration', () => {
    it('should toggle bulk import visibility with toggleBulkImport()', () => {
      expect(component.showBulkImport).toBeFalse();
      component.toggleBulkImport();
      expect(component.showBulkImport).toBeTrue();
      component.toggleBulkImport();
      expect(component.showBulkImport).toBeFalse();
    });

    it('should handle onBulkImportSuccess by setting success message and reloading assets', () => {
      spyOn(component, 'loadAssets');
      component.onBulkImportSuccess({ count: 5, assetNumbers: ['AST-001', 'AST-002'] });

      expect(component.successMessage).toBe('Successfully imported 5 assets.');
      expect(component.loadAssets).toHaveBeenCalled();
    });

    it('should render bulk import button and component when permission is held and view is assets', () => {
      permissions.add('asset.create');
      component.setView('assets');
      component.showBulkImport = true;
      fixture.detectChanges();

      const btn = fixture.nativeElement.querySelector('.bulk-import-btn');
      expect(btn).toBeTruthy();
      expect(btn.textContent.trim()).toBe('Close Bulk Import');

      const importComp = fixture.nativeElement.querySelector('app-asset-import');
      expect(importComp).toBeTruthy();
    });
  });

  describe('Superuser Company & User Access Management', () => {
    it('should return all company roles for superusers regardless of company-level permissions', () => {
      permissions.clear();
      permissions.add('company.read');
      component.companyRoles = [
        { scope: 'company', code: 'company_administrator', name: 'Company Administrator', permissions: ['company.members.manage', 'asset.create'] },
        { scope: 'company', code: 'read_only_user', name: 'Read-only User', permissions: ['company.read'] }
      ];
      expect(component.assignableCompanyRoles.map(r => r.code)).toEqual(['read_only_user']);

      permissions.add('system.companies.manage');
      expect(component.assignableCompanyRoles.map(r => r.code)).toEqual(['company_administrator', 'read_only_user']);
    });

    it('should switch company scope on onInviteCompanyChange', () => {
      spyOn(component, 'selectCompany');
      component.onInviteCompanyChange('company-2');
      expect(component.selectCompany).toHaveBeenCalledWith('company-2');
    });
  });

  describe('Asset Label Generation & Printing (Phase 9C Task 2)', () => {
    const testAssets: Asset[] = [
      {
        id: 'asset-1',
        company_id: 'company-1',
        asset_number: 'AST-0001',
        category_id: 'cat-1',
        status: 'in_stock',
        model: 'Latitude 7420',
        serial_number: 'SN-001'
      } as Asset,
      {
        id: 'asset-2',
        company_id: 'company-1',
        asset_number: 'AST-0002',
        category_id: 'cat-2',
        status: 'in_use',
        model: 'Precision 5550',
        serial_number: 'SN-002'
      } as Asset
    ];

    beforeEach(() => {
      component.companyId = 'company-1';
      component.company = { id: 'company-1', name: 'MindZen Corp', code: 'MZ', is_active: true };
      component.assets = [...testAssets];
      component.categories = [
        { id: 'cat-1', company_id: 'company-1', code: 'LAPTOP', name: 'Laptops', is_active: true },
        { id: 'cat-2', company_id: 'company-1', code: 'WORKSTATION', name: 'Workstations', is_active: true }
      ];
      component.selectedAssetIds.clear();
      component.showLabelModal = false;
      component.labelAssets = [];
    });

    it('should toggle individual asset selection', () => {
      expect(component.isAssetSelected('asset-1')).toBeFalse();
      component.toggleAssetSelection('asset-1');
      expect(component.isAssetSelected('asset-1')).toBeTrue();
      expect(component.selectedAssetsCount).toBe(1);

      component.toggleAssetSelection('asset-1');
      expect(component.isAssetSelected('asset-1')).toBeFalse();
      expect(component.selectedAssetsCount).toBe(0);
    });

    it('should toggle select all assets on current page', () => {
      expect(component.isAllAssetsOnPageSelected).toBeFalse();
      component.toggleSelectAll(true);
      expect(component.isAllAssetsOnPageSelected).toBeTrue();
      expect(component.selectedAssetsCount).toBe(2);

      component.toggleSelectAll(false);
      expect(component.isAllAssetsOnPageSelected).toBeFalse();
      expect(component.selectedAssetsCount).toBe(0);
    });

    it('should clear all selected assets', () => {
      component.toggleSelectAll(true);
      expect(component.selectedAssetsCount).toBe(2);
      component.clearAssetSelection();
      expect(component.selectedAssetsCount).toBe(0);
    });

    it('should open single asset label modal', () => {
      component.openLabelModal(testAssets[0]);
      expect(component.showLabelModal).toBeTrue();
      expect(component.labelAssets.length).toBe(1);
      expect(component.labelAssets[0].asset_number).toBe('AST-0001');

      component.closeLabelModal();
      expect(component.showLabelModal).toBeFalse();
      expect(component.labelAssets.length).toBe(0);
    });

    it('should open bulk label modal for selected assets', () => {
      component.toggleAssetSelection('asset-1');
      component.toggleAssetSelection('asset-2');
      component.openBulkLabelModal();

      expect(component.showLabelModal).toBeTrue();
      expect(component.labelAssets.length).toBe(2);
    });

    it('should build categoryMap correctly from master categories', () => {
      const map = component.categoryMap;
      expect(map['cat-1']).toBe('Laptops');
      expect(map['cat-2']).toBe('Workstations');
    });

    it('should clear selection when switching company', () => {
      component.toggleSelectAll(true);
      expect(component.selectedAssetsCount).toBe(2);

      component.selectCompany('company-2');
      expect(component.selectedAssetsCount).toBe(0);
    });
  });

  describe('QR Deep-Link Asset Lookup (Phase 9C Task 2.1)', () => {
    let router: Router;
    let queryParamMapSubject: BehaviorSubject<any>;

    const targetAsset: Asset = {
      id: 'asset-deep-link-1',
      company_id: 'company-1',
      asset_number: 'MZ-000016',
      category_id: 'cat-laptop',
      status: 'in_stock',
      model: 'ThinkPad T14s',
      serial_number: 'SN-TP-1234',
      manufacturer: 'Lenovo',
      acquisition_date: '2026-01-10',
      acquisition_cost: '1450.00',
      site_id: null,
      location_id: null,
      responsible_department_id: null,
      cost_center_id: null,
      custodian_name: null,
      vendor_reference: null,
      invoice_reference: null,
      warranty_start: null,
      warranty_end: null,
      notes: null
    };

    beforeEach(() => {
      router = TestBed.inject(Router);
      spyOn(router, 'navigate').and.returnValue(Promise.resolve(true));

      queryParamMapSubject = new BehaviorSubject(convertToParamMap({}));
      const route = TestBed.inject(ActivatedRoute);
      spyOnProperty(route, 'queryParamMap', 'get').and.returnValue(queryParamMapSubject.asObservable());
      component.initLookupSubscription();

      component.companyId = 'company-1';
      component.company = { id: 'company-1', name: 'MindZen Corp', code: 'MZ', is_active: true };
      component.loading = false;
      permissions.add('asset.read');
      registry.lookupAsset.and.returnValue(of(targetAsset));
      registry.getAsset.and.returnValue(of(targetAsset));
    });

    it('should look up asset and open details when valid ?lookup= code is received', () => {
      spyOn(component, 'openAsset').and.callThrough();

      queryParamMapSubject.next(convertToParamMap({ lookup: 'MZ-000016' }));

      expect(registry.lookupAsset).toHaveBeenCalledWith('company-1', 'MZ-000016');
      expect(component.openAsset).toHaveBeenCalledWith(targetAsset);
      expect(component.selectedAsset?.asset_number).toBe('MZ-000016');
      expect(component.activeView).toBe('assets');
      expect(router.navigate).toHaveBeenCalledWith([], {
        relativeTo: jasmine.any(Object),
        queryParams: { lookup: null },
        queryParamsHandling: 'merge',
        replaceUrl: true
      });
    });

    it('should show error and remove parameter when asset is not found (404)', () => {
      registry.lookupAsset.and.returnValue(
        throwError(() => new HttpErrorResponse({
          status: 404,
          error: { detail: "Asset with code 'UNKNOWN-999' not found" }
        }))
      );

      queryParamMapSubject.next(convertToParamMap({ lookup: 'UNKNOWN-999' }));

      expect(registry.lookupAsset).toHaveBeenCalledWith('company-1', 'UNKNOWN-999');
      expect(component.errorMessage).toContain('UNKNOWN-999');
      expect(component.errorMessage).toContain('was not found or is not accessible');
      expect(router.navigate).toHaveBeenCalledWith([], {
        relativeTo: jasmine.any(Object),
        queryParams: { lookup: null },
        queryParamsHandling: 'merge',
        replaceUrl: true
      });
    });

    it('should reject empty or whitespace lookup code without calling lookupAsset', () => {
      queryParamMapSubject.next(convertToParamMap({ lookup: '   ' }));

      expect(registry.lookupAsset).not.toHaveBeenCalled();
      expect(component.errorMessage).toBe('Lookup code cannot be empty.');
      expect(router.navigate).toHaveBeenCalled();
    });

    it('should reject control characters or excessively long lookup codes', () => {
      queryParamMapSubject.next(convertToParamMap({ lookup: 'bad\x00code' }));

      expect(registry.lookupAsset).not.toHaveBeenCalled();
      expect(component.errorMessage).toBe('Invalid lookup code provided.');
      expect(router.navigate).toHaveBeenCalled();
    });

    it('should enforce asset.read permission and show error without calling API if unauthorized', () => {
      permissions.delete('asset.read');

      queryParamMapSubject.next(convertToParamMap({ lookup: 'MZ-000016' }));

      expect(registry.lookupAsset).not.toHaveBeenCalled();
      expect(component.errorMessage).toContain('permission');
      expect(router.navigate).toHaveBeenCalled();
    });

    it('should prevent duplicate API requests when lookup parameter is repeated', () => {
      queryParamMapSubject.next(convertToParamMap({ lookup: 'MZ-000016' }));
      expect(registry.lookupAsset).toHaveBeenCalledTimes(1);

      queryParamMapSubject.next(convertToParamMap({ lookup: 'MZ-000016' }));
      expect(registry.lookupAsset).toHaveBeenCalledTimes(1);
    });

    it('should wait for company initialization and process pending lookup once company context is ready', () => {
      component.companyId = '';
      component.loading = true;

      queryParamMapSubject.next(convertToParamMap({ lookup: 'MZ-000016' }));
      expect(registry.lookupAsset).not.toHaveBeenCalled();

      component.companyId = 'company-1';
      component.loading = true; // Even if loading is true from loadAssets(), lookup should proceed!
      component.processPendingLookup();

      expect(registry.lookupAsset).toHaveBeenCalledWith('company-1', 'MZ-000016');
      expect(component.selectedAsset?.asset_number).toBe('MZ-000016');
    });

    it('should process lookup during selectCompany lifecycle even when loadAssets sets loading to true', () => {
      component.companyId = '';
      component.activeView = 'dashboard';
      component.selectedAsset = undefined;

      // Mock listMaster, listNumberRules, listAssets for selectCompany
      registry.listMaster.and.returnValue(of([]));
      registry.listNumberRules.and.returnValue(of([]));
      registry.listAssets.and.returnValue(of({ items: [], total: 0, page: 1, page_size: 25 }));
      registry.lookupAsset.and.returnValue(of(targetAsset));

      queryParamMapSubject.next(convertToParamMap({ lookup: 'MZ-000016' }));
      expect(registry.lookupAsset).not.toHaveBeenCalled();
      expect(component.activeView).toBe('assets');

      // Now trigger selectCompany
      component.selectCompany('company-1');

      expect(registry.lookupAsset).toHaveBeenCalledWith('company-1', 'MZ-000016');
      expect((component.selectedAsset as Asset | undefined)?.asset_number).toBe('MZ-000016');
      expect(component.activeView).toBe('assets');
      expect(router.navigate).toHaveBeenCalledWith([], {
        relativeTo: jasmine.any(Object),
        queryParams: { lookup: null },
        queryParamsHandling: 'merge',
        replaceUrl: true
      });
    });

    it('should display error and stay on assets view if lookup fails during selectCompany', () => {
      component.companyId = '';
      component.activeView = 'dashboard';
      component.selectedAsset = undefined;

      registry.listMaster.and.returnValue(of([]));
      registry.listNumberRules.and.returnValue(of([]));
      registry.listAssets.and.returnValue(of({ items: [], total: 0, page: 1, page_size: 25 }));
      registry.lookupAsset.and.returnValue(
        throwError(() => new HttpErrorResponse({
          status: 404,
          error: { detail: "Asset with code 'NOTFOUND-01' not found" }
        }))
      );

      queryParamMapSubject.next(convertToParamMap({ lookup: 'NOTFOUND-01' }));
      component.selectCompany('company-1');

      expect(registry.lookupAsset).toHaveBeenCalledWith('company-1', 'NOTFOUND-01');
      expect(component.errorMessage).toContain('NOTFOUND-01');
      expect(component.activeView).toBe('assets');
      expect(component.selectedAsset).toBeUndefined();
      expect(router.navigate).toHaveBeenCalledWith([], {
        relativeTo: jasmine.any(Object),
        queryParams: { lookup: null },
        queryParamsHandling: 'merge',
        replaceUrl: true
      });
    });

    it('should reset processedLookupCode when lookup param is cleared so subsequent lookup works', () => {
      queryParamMapSubject.next(convertToParamMap({ lookup: 'MZ-000016' }));
      expect(registry.lookupAsset).toHaveBeenCalledTimes(1);

      // Simulate router clearing param
      queryParamMapSubject.next(convertToParamMap({}));

      // Simulate scanning/opening the same asset again
      queryParamMapSubject.next(convertToParamMap({ lookup: 'MZ-000016' }));
      expect(registry.lookupAsset).toHaveBeenCalledTimes(2);
    });
  });
});
