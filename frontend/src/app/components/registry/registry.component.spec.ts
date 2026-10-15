import { provideHttpClient } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

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
  RegistryService
} from '../../services/registry.service';
import { RegistryComponent, serializeCsvCell } from './registry.component';

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
    permissions = new Set(['company.read', 'company.members.manage', 'asset.read', 'asset.assignment.manage']);
    registry = jasmine.createSpyObj<RegistryService>('RegistryService', [
      'companies',
      'listMaster',
      'listNumberRules',
      'companyMembers',
      'companyRoles',
      'listAssets',
      'getAsset',
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
      'goodsReceipts',
      'createSupplier',
      'createPurchaseOrder',
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
      'reportProcurement'
    ]);
    registry.companies.and.returnValue(of([company]));
    registry.listMaster.and.returnValue(of([]));
    registry.listNumberRules.and.returnValue(of([]));
    registry.companyMembers.and.returnValue(of([]));
    registry.companyRoles.and.returnValue(of(roles));
    registry.listAssets.and.returnValue(of({ items: [], total: 0, page: 1, page_size: 15 }));
    registry.getAsset.and.returnValue(of(testAsset));
    registry.usages.and.returnValue(of([]));
    registry.history.and.returnValue(of([]));
    registry.assignments.and.returnValue(of([]));
    registry.assignmentRecipients.and.returnValue(of([{ id: 'recipient-1', email: 'person@example.invalid' }]));
    registry.listLocations.and.returnValue(of([]));
    registry.suppliers.and.returnValue(of([]));
    registry.purchaseOrders.and.returnValue(of([]));
    registry.goodsReceipts.and.returnValue(of([]));
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
    permissions = new Set(['company.read', 'asset.read']);
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
    expect(fixture.nativeElement.textContent).toContain('Contracts Expiring (30d)');
    expect(fixture.nativeElement.textContent).toContain('Open Maintenance');
  });

  it('displays genuine zeroes when dashboard returns genuine zero metrics', () => {
    permissions = new Set(['company.read', 'asset.read']);
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
    permissions = new Set(['company.read', 'asset.read']);
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
