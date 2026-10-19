import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, ElementRef, OnInit, ViewChild, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import {
  Asset,
  AssetAllocationReportItem,
  AssetAssignment,
  AssetHistory,
  AssetPage,
  AssetRegisterReportItem,
  AssignmentRecipient,
  CompanyMember,
  CompanyRole,
  Company,
  DashboardData,
  DepartmentUsage,
  AssetServiceContract,
  GoodsReceipt,
  Invitation,
  MasterRecord,
  MaintenancePriority,
  MaintenanceReportItem,
  MaintenanceRequest,
  MaintenanceStatus,
  NumberRule,
  ProcurementReportItem,
  ProcurementSupplier,
  PurchaseOrder,
  RegistryService,
  WarrantyExpiryReportItem,
  VerificationCampaign,
  VerificationCampaignCreate,
  VerificationCampaignUpdate,
  VerificationExpectedAsset,
  VerificationObservation,
  VerificationObservationCreate,
  VerificationDiscrepancy,
  VerificationDiscrepancyResolveRequest,
  VerificationUnregisteredAsset,
  VerificationUnregisteredAssetCreate,
  VerificationUnregisteredAssetRegister,
  VerificationDashboardSummary,
  VerificationCampaignReportItem,
  VerificationDiscrepancyReportItem
} from '../../services/registry.service';
import { AuthService } from '../../services/auth.service';

type ViewName = 'dashboard' | 'assets' | 'reports' | 'departments' | 'sites' | 'categories' | 'cost-centers' | 'company' | 'users-access' | 'procurement' | 'maintenance' | 'verification';
type MasterKind = 'departments' | 'sites' | 'categories' | 'cost-centers';
export type ReportType = 'asset-register' | 'asset-allocation' | 'warranty-expiry' | 'maintenance' | 'procurement' | 'verification-campaigns' | 'verification-discrepancies';

/**
 * Serializes a single cell value for CSV export according to RFC-4180.
 *
 * Security mitigation (CWE-1236: Improper Neutralization of Formula Elements in a CSV File):
 * Untrusted text values beginning with formula trigger characters ('=', '+', '-', '@'),
 * including cases preceded by whitespace or ASCII control characters (\x00-\x1f, \x7f),
 * are prepended with a single quote (') to neutralize formula execution in spreadsheet
 * applications (such as Microsoft Excel, LibreOffice, or Google Sheets).
 *
 * NOTE: While prepending a single quote is the standard OWASP-recommended mitigation for CSV
 * injection, it is not a universal guarantee across every spreadsheet application or version.
 *
 * Legitimate finite numeric values (typeof number) are preserved without prefixing.
 * Double quotes within text are escaped by doubling (" -> "").
 * Null, undefined, and empty string values are returned as empty quotes ("").
 */
export function serializeCsvCell(value: unknown): string {
  if (value === null || value === undefined) {
    return '""';
  }

  if (typeof value === 'number') {
    if (!Number.isFinite(value)) {
      return '""';
    }
    return `"${value}"`;
  }

  if (typeof value === 'boolean') {
    return `"${value}"`;
  }

  let str = String(value);
  if (str === '') {
    return '""';
  }

  const trimmedLeading = str.replace(/^[\s\x00-\x1f\x7f]+/, '');
  if (trimmedLeading.length > 0 && /^[=+@-]$/.test(trimmedLeading.charAt(0))) {
    str = "'" + str;
  }

  return `"${str.replace(/"/g, '""')}"`;
}

@Component({
    selector: 'app-registry',
    imports: [CommonModule, FormsModule, RouterLink],
    changeDetection: ChangeDetectionStrategy.Eager,
    templateUrl: './registry.component.html'
})
export class RegistryComponent implements OnInit {
  @ViewChild('assetDetail') private assetDetail?: ElementRef<HTMLElement>;

  companies: Company[] = [];
  companyId = '';
  company?: Company;
  creatingCompany = false;
  activeView: ViewName = 'dashboard';
  loading = false;
  saving = false;
  errorMessage = '';
  successMessage = '';

  dashboardData?: DashboardData;
  dashboardLoading = false;
  dashboardError = '';

  activeReport: ReportType = 'asset-register';
  reportsLoading = false;
  reportsError = '';
  reportSearch = '';
  reportStatusFilter = '';
  reportCategoryFilter = '';
  reportSiteFilter = '';
  reportDepartmentFilter = '';
  reportSupplierFilter = '';
  reportCoverageStatusFilter = '';
  reportPriorityFilter = '';

  assetRegisterReport: AssetRegisterReportItem[] = [];
  assetAllocationReport: AssetAllocationReportItem[] = [];
  warrantyExpiryReport: WarrantyExpiryReportItem[] = [];
  maintenanceReport: MaintenanceReportItem[] = [];
  procurementReport: ProcurementReportItem[] = [];
  verificationCampaignReport: VerificationCampaignReportItem[] = [];
  verificationDiscrepancyReport: VerificationDiscrepancyReportItem[] = [];
  reportDiscrepancyTypeFilter = '';
  reportCampaignFilter = '';

  allLocations: MasterRecord[] = [];

  // Verification state
  verificationCampaigns: VerificationCampaign[] = [];
  selectedCampaign?: VerificationCampaign;
  campaignDashboard?: VerificationDashboardSummary;
  campaignExpectedAssets: VerificationExpectedAsset[] = [];
  campaignDiscrepancies: VerificationDiscrepancy[] = [];
  campaignUnregisteredAssets: VerificationUnregisteredAsset[] = [];
  verificationLoading = false;
  verificationSubView: 'expected' | 'discrepancies' | 'unregistered' = 'expected';
  verificationStatusFilter = 'all';
  verificationSearch = '';
  expectedSearch = '';
  expectedVerifiedFilter: boolean | undefined = undefined;
  expectedCategoryFilter = '';
  expectedLocationFilter = '';
  discrepancyTypeFilter = 'all';
  discrepancyStatusFilter = 'all';
  unregisteredStatusFilter = 'all';

  // Verification modals and forms
  campaignCreateModalOpen = false;
  campaignCreateForm: VerificationCampaignCreate = {
    campaign_reference: '',
    name: '',
    description: '',
    start_date: this.today(),
    end_date: this.today(),
    scope_category_ids: [],
    scope_location_ids: []
  };

  observationModalOpen = false;
  selectedExpectedAsset?: VerificationExpectedAsset;
  observationForm: VerificationObservationCreate = {
    is_found: true,
    actual_location_id: '',
    actual_custodian_id: '',
    observed_condition: 'good',
    remarks: '',
    reference_notes: ''
  };

  resolveDiscrepancyModalOpen = false;
  selectedDiscrepancy?: VerificationDiscrepancy;
  resolveDiscrepancyForm: VerificationDiscrepancyResolveRequest = {
    resolution_action: 'update_master',
    resolution_notes: ''
  };

  unregisteredModalOpen = false;
  unregisteredForm: VerificationUnregisteredAssetCreate = {
    description: '',
    category_id: '',
    serial_number: '',
    site_id: '',
    location_id: '',
    custodian_id: '',
    observed_condition: 'good',
    remarks: ''
  };

  registerUnregisteredModalOpen = false;
  selectedUnregisteredAsset?: VerificationUnregisteredAsset;
  registerUnregisteredForm: VerificationUnregisteredAssetRegister = {
    asset_number: '',
    cost_center_id: '',
    responsible_department_id: '',
    acquisition_cost: null,
    acquisition_date: this.today(),
    resolution_notes: ''
  };


  departments: MasterRecord[] = [];
  sites: MasterRecord[] = [];
  locations: MasterRecord[] = [];
  categories: MasterRecord[] = [];
  costCenters: MasterRecord[] = [];
  numberRules: NumberRule[] = [];
  assets: Asset[] = [];
  members: CompanyMember[] = [];
  companyRoles: CompanyRole[] = [];
  invitation?: Invitation;
  inviteEmail = '';
  inviteRoleCode = '';
  totalAssets = 0;
  page = 1;
  readonly pageSize = 15;
  selectedAsset?: Asset;
  selectedUsages: DepartmentUsage[] = [];
  assetHistory: AssetHistory[] = [];
  assignmentHistory: AssetAssignment[] = [];
  assignmentRecipients: AssignmentRecipient[] = [];
  assignmentRecipientsLoading = false;
  assignmentSiteId = '';
  transferSiteId = '';
  assignmentLocations: MasterRecord[] = [];
  transferLocations: MasterRecord[] = [];
  suppliers: ProcurementSupplier[] = [];
  purchaseOrders: PurchaseOrder[] = [];
  goodsReceipts: GoodsReceipt[] = [];
  procurementLoading = false;
  serviceContracts: AssetServiceContract[] = [];
  contractsLoading = false;
  maintenanceRequests: MaintenanceRequest[] = [];
  maintenanceAssets: Asset[] = [];
  maintenanceUsers: AssignmentRecipient[] = [];
  maintenanceLoading = false;
  selectedMaintenanceRequest?: MaintenanceRequest;
  maintenanceFilters: { asset_id: string; status: MaintenanceStatus | '' } = { asset_id: '', status: '' };
  maintenanceCreateForm = {
    asset_id: '',
    title: '',
    issue_description: '',
    priority: 'normal' as MaintenancePriority,
    reported_date: this.today(),
    assignee_id: ''
  };
  maintenanceUpdateForm = {
    status: 'open' as MaintenanceStatus,
    assignee_id: '',
    diagnosis: '',
    work_performed: '',
    resolution_notes: '',
    completed_date: '',
    cost: null as number | null
  };
  contractForm = {
    contract_type: 'warranty' as 'warranty' | 'amc',
    provider_name: '',
    reference_number: '',
    start_date: this.today(),
    end_date: this.today(),
    coverage_description: '',
    support_contact: '',
    notes: ''
  };
  supplierForm = { code: '', name: '', email: '', phone: '', notes: '' };
  editingPurchaseOrderId = '';
  private _purchaseOrderForm: any = this.initPurchaseOrderForm();
  get purchaseOrderForm(): any {
    return this._purchaseOrderForm;
  }
  set purchaseOrderForm(val: any) {
    if (!val) {
      this._purchaseOrderForm = this.initPurchaseOrderForm();
      return;
    }
    if (val.lines && Object.getOwnPropertyDescriptor(val, 'category_id')?.get) {
      this._purchaseOrderForm = val;
      return;
    }
    this._purchaseOrderForm = this.initPurchaseOrderForm(val);
  }
  goodsReceiptForm = {
    purchase_order_id: '',
    purchase_order_line_id: '',
    receipt_number: '',
    received_date: this.today(),
    delivery_reference: '',
    notes: '',
    quantity_received: 1,
    quantity_rejected: 0,
    serial_numbers: '',
    discrepancy_notes: ''
  };

  filters = { search: '', category_id: '', status: '', site_id: '', location_id: '', department_id: '' };
  companyForm = { code: '', name: '', number_prefix: 'AST', is_active: true };
  masterForm = { code: '', name: '', description: '', address: '', details: '', is_active: true };
  selectedSiteId = '';
  editingMasterId = '';
  editingLocationId = '';
  ruleForm = { category_id: '', prefix: 'AST', separator: '-', padding: 6 };
  assetForm: Partial<Asset> = {
    category_id: '',
    serial_number: '',
    manufacturer: '',
    model: '',
    status: 'in_stock',
    site_id: '',
    location_id: '',
    responsible_department_id: '',
    cost_center_id: '',
    custodian_name: '',
    notes: ''
  };
  assetEditForm: Partial<Asset> = {};
  usageForm = { department_id: '', purpose: '' };
  assignmentForm = {
    recipient_id: '',
    effective_date: this.today(),
    responsible_department_id: '',
    location_id: '',
    notes: '',
    reference: ''
  };
  handoverForm = {
    handover_date: this.today(),
    condition: '',
    included_items: '',
    acknowledgement: '',
    notes: ''
  };
  returnForm = {
    return_date: this.today(),
    condition: '',
    notes: '',
    issue_details: '',
    next_asset_status: 'in_stock' as 'in_stock' | 'maintenance'
  };
  transferForm = {
    recipient_id: '',
    effective_date: this.today(),
    reason: '',
    responsible_department_id: '',
    location_id: '',
    reference: '',
    condition: '',
    included_items: '',
    acknowledgement: '',
    notes: ''
  };

  constructor(
    private readonly registry: RegistryService,
    private readonly changeDetector: ChangeDetectorRef,
    readonly auth: AuthService
  ) {}

  ngOnInit(): void {
    this.loading = true;
    this.registry.companies().subscribe({
      next: (companies) => {
        this.companies = companies;
        this.loading = false;
        if (companies.length > 0) {
          this.selectCompany(companies[0].id);
        }
      },
      error: (error) => this.fail(error)
    });
  }

  viewMaintenanceForSelectedAsset(): void {
    if (!this.selectedAsset) return;
    this.maintenanceFilters = { asset_id: this.selectedAsset.id, status: '' };
    this.selectedMaintenanceRequest = undefined;
    this.setView('maintenance');
  }

  openMaintenanceAsset(request: MaintenanceRequest): void {
    const asset = this.maintenanceAssets.find((item) => item.id === request.asset_id);
    if (!asset) {
      this.errorMessage = 'The related asset is not in the current asset selection.';
      return;
    }
    this.activeView = 'assets';
    this.openAsset(asset);
  }

  get activeDepartments(): MasterRecord[] {
    return this.departments.filter((item) => item.is_active);
  }

  get activeSites(): MasterRecord[] {
    return this.sites.filter((item) => item.is_active);
  }

  get activeCategories(): MasterRecord[] {
    return this.categories.filter((item) => item.is_active);
  }

  get activeCostCenters(): MasterRecord[] {
    return this.costCenters.filter((item) => item.is_active);
  }

  get currentAssignment(): AssetAssignment | undefined {
    return this.assignmentHistory.find((assignment) => assignment.status === 'active');
  }

  get canAssignSelectedAsset(): boolean {
    return this.selectedAsset?.status === 'in_stock' && !this.currentAssignment;
  }

  get pageCount(): number {
    return Math.max(1, Math.ceil(this.totalAssets / this.pageSize));
  }

  can(permission: string): boolean {
    return this.auth.permissions(this.companyId).has(permission);
  }

  get assignableCompanyRoles(): CompanyRole[] {
    const permissions = this.auth.permissions(this.companyId);
    return this.companyRoles.filter((role) => role.permissions.every((permission) => permissions.has(permission)));
  }

  selectCompany(id: string): void {
    if (this.companyId !== id) {
      this.invitation = undefined;
      this.successMessage = '';
      this.errorMessage = '';
      this.selectedAsset = undefined;
      this.assignmentHistory = [];
      this.assignmentRecipients = [];
      this.suppliers = [];
      this.purchaseOrders = [];
      this.goodsReceipts = [];
      this.procurementLoading = false;
      this.serviceContracts = [];
      this.maintenanceRequests = [];
      this.maintenanceAssets = [];
      this.maintenanceUsers = [];
      this.selectedMaintenanceRequest = undefined;
      this.maintenanceLoading = false;
      this.dashboardData = undefined;
      this.dashboardLoading = false;
      this.dashboardError = '';
      this.reportsLoading = false;
      this.reportsError = '';
      this.assetRegisterReport = [];
      this.assetAllocationReport = [];
      this.warrantyExpiryReport = [];
      this.maintenanceReport = [];
      this.procurementReport = [];
      this.verificationCampaignReport = [];
      this.verificationDiscrepancyReport = [];
      this.verificationCampaigns = [];
      this.selectedCampaign = undefined;
      this.campaignDashboard = undefined;
      this.campaignExpectedAssets = [];
      this.campaignDiscrepancies = [];
      this.campaignUnregisteredAssets = [];
      this.verificationLoading = false;
    }
    this.companyId = id;
    this.company = this.companies.find((item) => item.id === id);
    this.creatingCompany = this.companies.length === 0;
    if (this.company) {
      this.companyForm.name = this.company.name;
      this.companyForm.is_active = this.company.is_active;
    }
    if (!id) {
      return;
    }
    if (this.company && !this.company.is_active && this.can('system.companies.manage')) {
      this.loading = false;
      return;
    }
    this.loading = true;
    this.errorMessage = '';
    forkJoin({
      departments: this.registry.listMaster(id, 'departments'),
      sites: this.registry.listMaster(id, 'sites'),
      categories: this.registry.listMaster(id, 'categories'),
      costCenters: this.registry.listMaster(id, 'cost-centers'),
      rules: this.registry.listNumberRules(id)
    }).subscribe({
      next: (result) => {
        this.departments = result.departments;
        this.sites = result.sites;
        this.categories = result.categories;
        this.costCenters = result.costCenters;
        this.numberRules = result.rules;
        this.loading = false;
        this.loadCompanyMembers();
        if (!this.ruleForm.category_id && result.rules.length) {
          const defaultRule = result.rules.find((rule) => rule.category_id === null) ?? result.rules[0];
          this.ruleForm = {
            category_id: defaultRule.category_id ?? '',
            prefix: defaultRule.prefix,
            separator: defaultRule.separator,
            padding: defaultRule.padding
          };
        }
        if (this.activeView === 'dashboard' && !this.can('dashboard.read')) {
          this.activeView = 'assets';
        }
        this.loadAssets();
        if (this.activeView === 'dashboard' && this.can('dashboard.read')) {
          this.loadDashboard();
        } else if (this.activeView === 'reports') {
          this.loadActiveReport();
        } else if (this.activeView === 'procurement') {
          this.loadProcurement();
        } else if (this.activeView === 'maintenance') {
          this.loadMaintenance();
        } else if (this.activeView === 'verification') {
          this.loadVerification();
        }
        if (this.selectedSiteId) {
          this.loadLocations(this.selectedSiteId);
        }
      },
      error: (error) => this.fail(error)
    });
  }


  loadCompanyMembers(): void {
    this.members = [];
    this.companyRoles = [];
    if (!this.companyId || !this.can('company.members.manage')) {
      return;
    }
    forkJoin({
      members: this.registry.companyMembers(this.companyId),
      roles: this.registry.companyRoles(this.companyId)
    }).subscribe({
      next: ({ members, roles }) => {
        this.members = members;
        this.companyRoles = roles;
        if (!this.inviteRoleCode) {
          this.inviteRoleCode = this.assignableCompanyRoles[0]?.code ?? '';
        }
      },
      error: (error) => this.fail(error)
    });
  }

  inviteCompanyMember(): void {
    if (!this.companyId || !this.inviteEmail.trim() || !this.inviteRoleCode) {
      return;
    }
    this.registry.inviteMember(this.companyId, this.inviteEmail.trim(), this.inviteRoleCode).subscribe({
      next: (invitation) => {
        this.invitation = invitation;
        this.inviteEmail = '';
        this.successMessage = `Invitation created for ${invitation.email}. Share the one-time token securely.`;
        this.loadCompanyMembers();
      },
      error: (error) => this.fail(error)
    });
  }

  revokeCompanyMember(member: CompanyMember): void {
    if (!this.companyId || member.id === this.auth.currentUser()?.id || member.status === 'revoked') {
      return;
    }
    if (!window.confirm(`Revoke ${member.email}'s company membership?`)) {
      return;
    }
    this.registry.updateMembership(this.companyId, member.membership_id, 'revoked').subscribe({
      next: () => {
        this.successMessage = `Membership for ${member.email} was revoked.`;
        this.loadCompanyMembers();
      },
      error: (error) => this.fail(error)
    });
  }

  setView(view: ViewName): void {
    if (view === 'dashboard' && !this.can('dashboard.read')) {
      view = 'assets';
    }
    if (view === 'verification' && !this.can('verification.read')) {
      view = 'assets';
    }
    this.activeView = view;
    this.errorMessage = '';
    this.successMessage = '';
    this.editingMasterId = '';
    this.masterForm = { code: '', name: '', description: '', address: '', details: '', is_active: true };
    if (view === 'dashboard') {
      this.loadDashboard();
    } else if (view === 'reports') {
      this.loadActiveReport();
    } else if (view === 'assets') {
      this.loadAssets();
    } else if (view === 'procurement') {
      this.loadProcurement();
    } else if (view === 'maintenance') {
      this.loadMaintenance();
    } else if (view === 'verification') {
      this.loadVerification();
    }
  }


  get selectedPurchaseOrder(): PurchaseOrder | undefined {
    return this.purchaseOrders.find((order) => order.id === this.goodsReceiptForm.purchase_order_id);
  }

  get selectedPurchaseOrderLine() {
    return this.selectedPurchaseOrder?.lines.find((line) => line.id === this.goodsReceiptForm.purchase_order_line_id);
  }

  remainingToReceive(lineId: string): number {
    const orderedLine = this.selectedPurchaseOrder?.lines.find((line) => line.id === lineId);
    if (!orderedLine) return 0;
    return this.remainingInOrder(orderedLine.purchase_order_id, orderedLine.id, orderedLine.quantity_ordered);
  }

  private remainingInOrder(orderId: string, lineId: string, orderedQuantity: number): number {
    const received = this.goodsReceipts
      .filter((receipt) => receipt.purchase_order_id === orderId)
      .flatMap((receipt) => receipt.lines)
      .filter((line) => line.purchase_order_line_id === lineId)
      .reduce((total, line) => total + line.quantity_received, 0);
    return Math.max(0, orderedQuantity - received);
  }

  loadProcurement(): void {
    if (!this.companyId || !this.can('procurement.read')) return;
    const requestedCompanyId = this.companyId;
    this.procurementLoading = true;
    forkJoin({
      suppliers: this.registry.suppliers(requestedCompanyId),
      orders: this.registry.purchaseOrders(requestedCompanyId),
      receipts: this.registry.goodsReceipts(requestedCompanyId)
    }).subscribe({
      next: (result) => {
        if (requestedCompanyId !== this.companyId) return;
        this.suppliers = result.suppliers;
        this.purchaseOrders = result.orders;
        this.goodsReceipts = result.receipts;
        this.procurementLoading = false;
      },
      error: (error) => {
        if (requestedCompanyId !== this.companyId) return;
        this.procurementLoading = false;
        this.fail(error);
      }
    });
  }

      loadMaintenance(): void {
        if (!this.companyId || !this.can('maintenance.read')) return;
        const requestedCompanyId = this.companyId;
        this.maintenanceLoading = true;
        forkJoin({
          requests: this.registry.maintenanceRequests(requestedCompanyId, this.maintenanceFilters),
          users: this.registry.maintenanceUsers(requestedCompanyId),
          assets: this.registry.listAssets(requestedCompanyId, { page: 1, page_size: 100 })
        }).subscribe({
          next: ({ requests, users, assets }) => {
            if (requestedCompanyId !== this.companyId) return;
            this.maintenanceRequests = requests;
            this.maintenanceUsers = users;
            this.maintenanceAssets = assets.items;
            this.maintenanceLoading = false;
            if (this.selectedMaintenanceRequest) {
              this.selectedMaintenanceRequest = requests.find(
                (request) => request.id === this.selectedMaintenanceRequest?.id
              );
              if (this.selectedMaintenanceRequest) this.selectMaintenanceRequest(this.selectedMaintenanceRequest);
            }
          },
          error: (error) => {
            if (requestedCompanyId !== this.companyId) return;
            this.maintenanceLoading = false;
            this.fail(error);
          }
        });
      }

      applyMaintenanceFilters(): void {
        this.selectedMaintenanceRequest = undefined;
        this.loadMaintenance();
      }

      selectMaintenanceRequest(request: MaintenanceRequest): void {
        this.selectedMaintenanceRequest = request;
        this.maintenanceUpdateForm = {
          status: request.status,
          assignee_id: request.assignee_id ?? '',
          diagnosis: request.diagnosis ?? '',
          work_performed: request.work_performed ?? '',
          resolution_notes: request.resolution_notes ?? '',
          completed_date: request.completed_date ?? '',
          cost: request.cost === null ? null : Number(request.cost)
        };
      }

      createMaintenanceRequest(): void {
        if (!this.companyId || this.saving || !this.can('maintenance.manage')) return;
        this.saving = true;
        this.registry.createMaintenanceRequest(this.companyId, {
          ...this.maintenanceCreateForm,
          title: this.maintenanceCreateForm.title.trim(),
          issue_description: this.maintenanceCreateForm.issue_description.trim(),
          assignee_id: this.maintenanceCreateForm.assignee_id || null
        }).subscribe({
          next: (request) => {
            this.saving = false;
            this.maintenanceCreateForm = {
              asset_id: '',
              title: '',
              issue_description: '',
              priority: 'normal',
              reported_date: this.today(),
              assignee_id: ''
            };
            this.successMessage = `Maintenance request created for ${request.asset_number}.`;
            this.errorMessage = '';
            this.loadMaintenance();
          },
          error: (error) => this.fail(error)
        });
      }

      saveMaintenanceRequest(): void {
        const request = this.selectedMaintenanceRequest;
        if (!request || this.saving || !this.can('maintenance.manage')) return;
        if (this.maintenanceUpdateForm.status !== request.status &&
            !window.confirm(`Change request ${request.id.slice(0, 8)} from ${request.status} to ${this.maintenanceUpdateForm.status}?`)) {
          return;
        }
        this.saving = true;
        this.registry.updateMaintenanceRequest(this.companyId, request.id, {
          ...this.maintenanceUpdateForm,
          assignee_id: this.maintenanceUpdateForm.assignee_id || null,
          diagnosis: this.maintenanceUpdateForm.diagnosis || null,
          work_performed: this.maintenanceUpdateForm.work_performed || null,
          resolution_notes: this.maintenanceUpdateForm.resolution_notes || null,
          completed_date: this.maintenanceUpdateForm.completed_date || null,
          cost: this.maintenanceUpdateForm.cost === null ? null : Number(this.maintenanceUpdateForm.cost)
        }).subscribe({
          next: (updated) => {
            this.saving = false;
            this.successMessage = `Maintenance request for ${updated.asset_number} updated.`;
            this.errorMessage = '';
            this.loadMaintenance();
          },
          error: (error) => this.fail(error)
        });
      }

      allowedMaintenanceStatuses(request: MaintenanceRequest): MaintenanceStatus[] {
        switch (request.status) {
          case 'open': return ['open', 'in_progress'];
          case 'in_progress': return ['in_progress', 'resolved'];
          case 'resolved': return ['resolved', 'closed'];
          case 'closed': return ['closed'];
        }
      }

      loadServiceContracts(): void {
        const asset = this.selectedAsset;
        if (!asset || !this.companyId || !this.can('maintenance.read')) {
          this.serviceContracts = [];
          return;
        }
        const requestedCompanyId = this.companyId;
        const requestedAssetId = asset.id;
        this.contractsLoading = true;
        this.registry.serviceContracts(requestedCompanyId, requestedAssetId).subscribe({
          next: (contracts) => {
            if (requestedCompanyId !== this.companyId || requestedAssetId !== this.selectedAsset?.id) return;
            this.serviceContracts = contracts;
            this.contractsLoading = false;
          },
          error: (error) => {
            if (requestedCompanyId !== this.companyId || requestedAssetId !== this.selectedAsset?.id) return;
            this.contractsLoading = false;
            this.fail(error);
          }
        });
      }

      createServiceContract(): void {
        const asset = this.selectedAsset;
        if (!asset || this.saving || !this.can('maintenance.manage')) return;
        this.saving = true;
        this.registry.createServiceContract(this.companyId, asset.id, {
          ...this.contractForm,
          provider_name: this.contractForm.provider_name.trim() || null,
          reference_number: this.contractForm.reference_number.trim() || null,
          coverage_description: this.contractForm.coverage_description.trim() || null,
          support_contact: this.contractForm.support_contact.trim() || null,
          notes: this.contractForm.notes.trim() || null
        }).subscribe({
          next: (contract) => {
            this.saving = false;
            this.contractForm = {
              contract_type: 'warranty',
              provider_name: '',
              reference_number: '',
              start_date: this.today(),
              end_date: this.today(),
              coverage_description: '',
              support_contact: '',
              notes: ''
            };
            this.successMessage = `${contract.contract_type === 'amc' ? 'AMC' : 'Warranty'} recorded for ${asset.asset_number}.`;
            this.errorMessage = '';
            this.loadServiceContracts();
          },
          error: (error) => this.fail(error)
        });
      }

      cancelServiceContract(contract: AssetServiceContract): void {
        if (!this.can('maintenance.manage') || contract.status === 'cancelled' ||
            !window.confirm(`Cancel ${contract.contract_type} ${contract.reference_number || 'contract'}?`)) return;
        this.saving = true;
        this.registry.cancelServiceContract(this.companyId, contract.id).subscribe({
          next: () => {
            this.saving = false;
            this.successMessage = 'Service contract cancelled; its record is retained.';
            this.loadServiceContracts();
          },
          error: (error) => this.fail(error)
        });
      }

  createSupplier(): void {
    if (!this.companyId || this.saving || !this.can('procurement.manage')) return;
    this.saving = true;
    this.registry.createSupplier(this.companyId, {
      ...this.supplierForm,
      email: this.supplierForm.email || null,
      phone: this.supplierForm.phone || null,
      notes: this.supplierForm.notes || null
    }).subscribe({
      next: (supplier) => {
        this.suppliers = [...this.suppliers, supplier].sort((a, b) => a.name.localeCompare(b.name));
        this.supplierForm = { code: '', name: '', email: '', phone: '', notes: '' };
        this.saving = false;
        this.successMessage = `Supplier ${supplier.name} created.`;
        this.errorMessage = '';
      },
      error: (error) => this.fail(error)
    });
  }

  initPurchaseOrderForm(initial?: any): any {
    const today = this.today();
    const rawLines = initial?.lines;
    const lines: Array<{
      category_id: string;
      description: string;
      quantity_ordered: number;
      unit_cost: number;
      discount: number;
      tax_rate: number;
      tax_amount: number;
    }> = Array.isArray(rawLines) && rawLines.length > 0
      ? rawLines.map((l: any) => ({
          category_id: l.category_id || '',
          description: l.description || '',
          quantity_ordered: l.quantity_ordered !== undefined ? Number(l.quantity_ordered) : 1,
          unit_cost: l.unit_cost !== undefined ? Number(l.unit_cost) : 0,
          discount: l.discount !== undefined ? Number(l.discount) : 0,
          tax_rate: l.tax_rate !== undefined ? Number(l.tax_rate) : 0,
          tax_amount: l.tax_amount !== undefined ? Number(l.tax_amount) : 0,
        }))
      : [{
          category_id: initial?.category_id || '',
          description: initial?.description || '',
          quantity_ordered: initial?.quantity_ordered !== undefined ? Number(initial.quantity_ordered) : 1,
          unit_cost: initial?.unit_cost !== undefined ? Number(initial.unit_cost) : 0,
          discount: 0,
          tax_rate: 0,
          tax_amount: 0,
        }];

    const target: any = {
      supplier_id: initial?.supplier_id || '',
      order_number: initial?.order_number || '',
      ordered_date: initial?.ordered_date || today,
      expected_date: initial?.expected_date || '',
      notes: initial?.notes || '',
      lines
    };

    Object.defineProperties(target, {
      category_id: {
        get() { return this.lines[0]?.category_id ?? ''; },
        set(v: string) { if (this.lines[0]) this.lines[0].category_id = v; },
        enumerable: true,
        configurable: true
      },
      description: {
        get() { return this.lines[0]?.description ?? ''; },
        set(v: string) { if (this.lines[0]) this.lines[0].description = v; },
        enumerable: true,
        configurable: true
      },
      quantity_ordered: {
        get() { return this.lines[0]?.quantity_ordered ?? 1; },
        set(v: number) { if (this.lines[0]) this.lines[0].quantity_ordered = Number(v); },
        enumerable: true,
        configurable: true
      },
      unit_cost: {
        get() { return this.lines[0]?.unit_cost ?? 0; },
        set(v: number) { if (this.lines[0]) this.lines[0].unit_cost = Number(v); },
        enumerable: true,
        configurable: true
      }
    });

    return target;
  }

  addPoLine(): void {
    if (!this.purchaseOrderForm.lines) {
      this.purchaseOrderForm.lines = [];
    }
    this.purchaseOrderForm.lines.push({
      category_id: '',
      description: '',
      quantity_ordered: 1,
      unit_cost: 0,
      discount: 0,
      tax_rate: 0,
      tax_amount: 0,
    });
    this.changeDetector.markForCheck();
  }

  removePoLine(index: number): void {
    if (!this.purchaseOrderForm.lines || this.purchaseOrderForm.lines.length <= 1) return;
    this.purchaseOrderForm.lines.splice(index, 1);
    this.changeDetector.markForCheck();
  }

  poLineSubtotal(line: any): number {
    const qty = Number(line?.quantity_ordered) || 0;
    const cost = Number(line?.unit_cost) || 0;
    return Number((qty * cost).toFixed(2));
  }

  poLineTotal(line: any): number {
    const subtotal = this.poLineSubtotal(line);
    const disc = Number(line?.discount) || 0;
    const tax = Number(line?.tax_amount) || 0;
    return Math.max(0, Number((subtotal - disc + tax).toFixed(2)));
  }

  get poTotalQuantity(): number {
    return (this.purchaseOrderForm?.lines || []).reduce((acc: number, l: any) => acc + (Number(l.quantity_ordered) || 0), 0);
  }

  get poSubtotal(): number {
    return Number((this.purchaseOrderForm?.lines || []).reduce((acc: number, l: any) => acc + this.poLineSubtotal(l), 0).toFixed(2));
  }

  get poTotalDiscount(): number {
    return Number((this.purchaseOrderForm?.lines || []).reduce((acc: number, l: any) => acc + (Number(l.discount) || 0), 0).toFixed(2));
  }

  get poTotalTax(): number {
    return Number((this.purchaseOrderForm?.lines || []).reduce((acc: number, l: any) => acc + (Number(l.tax_amount) || 0), 0).toFixed(2));
  }

  get poTotalAmount(): number {
    return Math.max(0, Number((this.poSubtotal - this.poTotalDiscount + this.poTotalTax).toFixed(2)));
  }

  canEditOrder(order: PurchaseOrder): boolean {
    return order.status === 'open' && this.can('procurement.manage') && !this.orderHasReceipts(order.id);
  }

  orderHasReceipts(orderId: string): boolean {
    return this.goodsReceipts.some((r) => r.purchase_order_id === orderId);
  }

  editPurchaseOrder(order: PurchaseOrder): void {
    if (!this.canEditOrder(order)) return;
    this.editingPurchaseOrderId = order.id;
    this.purchaseOrderForm = {
      supplier_id: order.supplier_id,
      order_number: order.order_number,
      ordered_date: order.ordered_date,
      expected_date: order.expected_date || '',
      notes: order.notes || '',
      lines: (order.lines || []).map((line) => ({
        category_id: line.category_id,
        description: line.description,
        quantity_ordered: line.quantity_ordered,
        unit_cost: Number(line.unit_cost) || 0,
        discount: Number(line.discount) || 0,
        tax_rate: Number(line.tax_rate) || 0,
        tax_amount: Number(line.tax_amount) || 0,
      }))
    };
    this.errorMessage = '';
    this.successMessage = '';
    this.changeDetector.markForCheck();
  }

  cancelPoEdit(): void {
    this.editingPurchaseOrderId = '';
    this.purchaseOrderForm = this.initPurchaseOrderForm();
    this.errorMessage = '';
    this.changeDetector.markForCheck();
  }

  createPurchaseOrder(): void {
    if (!this.companyId || this.saving || !this.can('procurement.manage')) return;
    if (!this.suppliers.length) {
      this.errorMessage = 'Please register at least one supplier before creating a purchase order.';
      this.changeDetector.markForCheck();
      return;
    }
    if (!this.activeCategories.length) {
      this.errorMessage = 'Please create at least one asset category before creating a purchase order.';
      this.changeDetector.markForCheck();
      return;
    }
    if (!this.purchaseOrderForm.supplier_id) {
      this.errorMessage = 'Please choose a supplier.';
      this.changeDetector.markForCheck();
      return;
    }
    if (!this.purchaseOrderForm.order_number?.trim()) {
      this.errorMessage = 'Please enter an order number.';
      this.changeDetector.markForCheck();
      return;
    }
    if (!this.purchaseOrderForm.ordered_date) {
      this.errorMessage = 'Please choose an order date.';
      this.changeDetector.markForCheck();
      return;
    }
    if (this.purchaseOrderForm.expected_date && this.purchaseOrderForm.expected_date < this.purchaseOrderForm.ordered_date) {
      this.errorMessage = 'Expected date must be on or after the ordered date.';
      this.changeDetector.markForCheck();
      return;
    }

    const lines = this.purchaseOrderForm.lines || [];
    if (lines.length === 0) {
      this.errorMessage = 'Please add at least one line item.';
      this.changeDetector.markForCheck();
      return;
    }

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (!line.category_id) {
        this.errorMessage = i === 0
          ? 'Please choose an asset category for the item.'
          : `Please choose an asset category for line #${i + 1}.`;
        this.changeDetector.markForCheck();
        return;
      }
      if (!line.description?.trim()) {
        this.errorMessage = i === 0
          ? 'Please enter an item description.'
          : `Please enter an item description for line #${i + 1}.`;
        this.changeDetector.markForCheck();
        return;
      }
      const qty = Number(line.quantity_ordered);
      if (!qty || qty <= 0) {
        this.errorMessage = i === 0
          ? 'Quantity ordered must be greater than zero.'
          : `Quantity ordered for line #${i + 1} must be greater than zero.`;
        this.changeDetector.markForCheck();
        return;
      }
      const cost = Number(line.unit_cost);
      if (isNaN(cost) || cost < 0) {
        this.errorMessage = i === 0
          ? 'Unit cost must be zero or a positive amount.'
          : `Unit cost for line #${i + 1} must be zero or a positive amount.`;
        this.changeDetector.markForCheck();
        return;
      }
    }

    this.errorMessage = '';
    this.saving = true;
    this.changeDetector.markForCheck();

    const payload = {
      supplier_id: this.purchaseOrderForm.supplier_id,
      order_number: this.purchaseOrderForm.order_number.trim(),
      ordered_date: this.purchaseOrderForm.ordered_date,
      expected_date: this.purchaseOrderForm.expected_date || null,
      notes: this.purchaseOrderForm.notes || '',
      lines: lines.map((l: any) => ({
        category_id: l.category_id,
        description: l.description.trim(),
        quantity_ordered: Number(l.quantity_ordered),
        unit_cost: Number(l.unit_cost),
        discount: Number(l.discount) || 0,
        tax_rate: Number(l.tax_rate) || 0,
        tax_amount: Number(l.tax_amount) || 0,
      }))
    };

    if (this.editingPurchaseOrderId) {
      this.registry.updatePurchaseOrder(this.companyId, this.editingPurchaseOrderId, payload).subscribe({
        next: (order) => {
          const index = this.purchaseOrders.findIndex((item) => item.id === order.id);
          if (index >= 0) {
            this.purchaseOrders[index] = order;
          }
          this.editingPurchaseOrderId = '';
          this.purchaseOrderForm = this.initPurchaseOrderForm();
          this.saving = false;
          this.successMessage = `Purchase order ${order.order_number} updated.`;
          this.errorMessage = '';
          this.changeDetector.markForCheck();
        },
        error: (error) => this.fail(error)
      });
    } else {
      this.registry.createPurchaseOrder(this.companyId, payload).subscribe({
        next: (order) => {
          this.purchaseOrders = [order, ...this.purchaseOrders];
          this.purchaseOrderForm = this.initPurchaseOrderForm();
          this.saving = false;
          this.successMessage = `Purchase order ${order.order_number} created.`;
          this.errorMessage = '';
          this.changeDetector.markForCheck();
        },
        error: (error) => this.fail(error)
      });
    }
  }

  savePurchaseOrder(): void {
    this.createPurchaseOrder();
  }

  createGoodsReceipt(): void {
    const line = this.selectedPurchaseOrderLine;
    const quantity = Number(this.goodsReceiptForm.quantity_received);
    const rejected = Number(this.goodsReceiptForm.quantity_rejected);
    if (!this.companyId || !this.selectedPurchaseOrder || !line || this.saving || !this.can('procurement.manage')) return;
    if (quantity > this.remainingToReceive(line.id) || rejected > quantity) {
      this.errorMessage = 'Received quantity must not exceed the remaining ordered quantity, and rejected quantity must not exceed received quantity.';
      return;
    }
    if (!window.confirm(`Receive ${quantity - rejected} accepted item(s) and register them as assets?`)) return;
    const serials = this.goodsReceiptForm.serial_numbers
      .split(',')
      .map((serial) => serial.trim())
      .filter(Boolean);
    this.saving = true;
    this.registry.receiveGoods(this.companyId, this.selectedPurchaseOrder.id, {
      receipt_number: this.goodsReceiptForm.receipt_number.trim(),
      received_date: this.goodsReceiptForm.received_date,
      delivery_reference: this.goodsReceiptForm.delivery_reference,
      notes: this.goodsReceiptForm.notes,
      lines: [{
        purchase_order_line_id: line.id,
        quantity_received: quantity,
        quantity_rejected: rejected,
        serial_numbers: serials,
        discrepancy_notes: this.goodsReceiptForm.discrepancy_notes
      }]
    }).subscribe({
      next: (receipt) => {
        this.goodsReceipts = [receipt, ...this.goodsReceipts];
        const index = this.purchaseOrders.findIndex((order) => order.id === receipt.purchase_order_id);
        if (index >= 0) {
          const po = this.purchaseOrders[index];
          const allReceived = po.lines.every((orderLine) =>
            this.remainingInOrder(
              po.id,
              orderLine.id,
              orderLine.quantity_ordered
            ) === 0
          );
          this.purchaseOrders[index] = {
            ...po,
            status: allReceived ? 'received' : 'partially_received'
          };
        }
        this.goodsReceiptForm = {
          ...this.goodsReceiptForm,
          receipt_number: '',
          received_date: this.today(),
          delivery_reference: '',
          notes: '',
          quantity_received: 1,
          quantity_rejected: 0,
          serial_numbers: '',
          discrepancy_notes: ''
        };
        this.saving = false;
        this.successMessage = `Receipt ${receipt.receipt_number} recorded; ${receipt.lines.flatMap((item) => item.assets).length} asset(s) registered.`;
        this.errorMessage = '';
        this.changeDetector.markForCheck();
      },
      error: (error) => this.fail(error)
    });
  }

  selectReceiptOrder(orderId: string): void {
    this.goodsReceiptForm.purchase_order_id = orderId;
    const order = this.purchaseOrders.find((item) => item.id === orderId);
    const firstLine = order?.lines.find((line) =>
      this.remainingInOrder(orderId, line.id, line.quantity_ordered) > 0
    );
    this.goodsReceiptForm.purchase_order_line_id = firstLine?.id ?? '';
    this.goodsReceiptForm.quantity_received = firstLine ? Math.max(1, this.remainingToReceive(firstLine.id)) : 1;
    this.changeDetector.markForCheck();
  }

  onReceiptLineChange(lineId: string): void {
    this.goodsReceiptForm.purchase_order_line_id = lineId;
    if (lineId) {
      const rem = this.remainingToReceive(lineId);
      this.goodsReceiptForm.quantity_received = rem > 0 ? rem : 1;
    }
    this.changeDetector.markForCheck();
  }

  supplierName(supplierId: string): string {
    return this.suppliers.find((supplier) => supplier.id === supplierId)?.name ?? 'Unknown supplier';
  }

  orderNumber(orderId: string): string {
    return this.purchaseOrders.find((order) => order.id === orderId)?.order_number ?? orderId;
  }

  receiptAssets(receipt: GoodsReceipt) {
    return receipt.lines.flatMap((line) => line.assets);
  }

  loadAssets(): void {
    if (!this.companyId) {
      return;
    }
    this.loading = true;
    this.registry.listAssets(this.companyId, {
      page: this.page,
      page_size: this.pageSize,
      search: this.filters.search,
      category_id: this.filters.category_id,
      status: this.filters.status,
      site_id: this.filters.site_id,
      location_id: this.filters.location_id,
      department_id: this.filters.department_id
    }).subscribe({
      next: (result: AssetPage) => {
        this.assets = result.items;
        this.totalAssets = result.total;
        this.loading = false;
      },
      error: (error) => this.fail(error)
    });
  }

  pageBy(delta: number): void {
    const pageCount = Math.max(1, Math.ceil(this.totalAssets / this.pageSize));
    this.page = Math.min(pageCount, Math.max(1, this.page + delta));
    this.loadAssets();
  }

  onSiteChange(siteId: string): void {
    this.selectedSiteId = siteId;
    this.locations = [];
    if (siteId) {
      this.loadLocations(siteId);
    }
  }

  loadLocations(siteId: string): void {
    if (!siteId || !this.companyId) {
      this.locations = [];
      return;
    }
    this.registry.listLocations(this.companyId, siteId).subscribe({
      next: (records) => (this.locations = records),
      error: (error) => this.fail(error)
    });
  }

  saveMaster(): void {
    if (!this.companyId) {
      this.errorMessage = 'Create or select a company before adding master data.';
      return;
    }
    const kind = this.activeView as MasterKind;
    const payload: Record<string, string | boolean | null> = {
      code: this.masterForm.code.trim(),
      name: this.masterForm.name.trim(),
      is_active: this.masterForm.is_active
    };
    if (kind === 'sites') {
      payload['address'] = this.masterForm.address;
    } else if (kind === 'categories') {
      payload['description'] = this.masterForm.description;
    }
    if (this.editingMasterId) {
      const body: Record<string, string | boolean | null> = { name: this.masterForm.name.trim(), is_active: this.masterForm.is_active };
      if (kind === 'sites') {
        body['address'] = this.masterForm.address;
      } else if (kind === 'categories') {
        body['description'] = this.masterForm.description;
      }
      this.updateMaster(kind, this.editingMasterId, body);
      return;
    }
    this.saving = true;
    this.registry.createMaster(this.companyId, kind, payload).subscribe({
      next: () => {
        this.saving = false;
        this.successMessage = 'Record created.';
        this.masterForm = { code: '', name: '', description: '', address: '', details: '', is_active: true };
        this.refreshMaster(kind);
      },
      error: (error) => this.fail(error)
    });
  }

  saveLocation(): void {
    if (!this.selectedSiteId) {
      this.errorMessage = 'Select a site for this location.';
      return;
    }
    this.saving = true;
    if (this.editingLocationId) {
      this.registry.updateLocation(this.companyId, this.selectedSiteId, this.editingLocationId, {
        name: this.masterForm.name.trim(),
        details: this.masterForm.details,
        is_active: this.masterForm.is_active
      }).subscribe({
        next: () => {
          this.saving = false;
          this.editingLocationId = '';
          this.successMessage = 'Location updated.';
          this.loadLocations(this.selectedSiteId);
          this.masterForm = { code: '', name: '', description: '', address: '', details: '', is_active: true };
        },
        error: (error) => this.fail(error)
      });
      return;
    }
    this.registry.createLocation(this.companyId, this.selectedSiteId, {
      code: this.masterForm.code.trim(),
      name: this.masterForm.name.trim(),
      details: this.masterForm.details,
      is_active: true
    }).subscribe({
      next: () => {
        this.saving = false;
        this.successMessage = 'Location created.';
        this.masterForm = { code: '', name: '', description: '', address: '', details: '', is_active: true };
        this.loadLocations(this.selectedSiteId);
      },
      error: (error) => this.fail(error)
    });
  }

  editMaster(record: MasterRecord): void {
    this.editingMasterId = record.id;
    this.masterForm = {
      code: record.code,
      name: record.name,
      description: record.description ?? '',
      address: record.address ?? '',
      details: record.details ?? '',
      is_active: record.is_active
    };
    if (record.site_id) {
      this.selectedSiteId = record.site_id;
      this.loadLocations(record.site_id);
    }
  }

  editLocation(record: MasterRecord): void {
    this.editingLocationId = record.id;
    this.selectedSiteId = record.site_id ?? this.selectedSiteId;
    if (this.selectedSiteId) this.loadLocations(this.selectedSiteId);
    this.masterForm.code = record.code;
    this.masterForm.name = record.name;
    this.masterForm.details = record.details ?? '';
    this.masterForm.is_active = record.is_active;
  }

  deactivateLocation(record: MasterRecord): void {
    if (!window.confirm(`Deactivate location ${record.name}?`)) return;
    this.registry.deactivateLocation(this.companyId, this.selectedSiteId, record).subscribe({
      next: () => {
        this.successMessage = 'Location deactivated.';
        this.loadLocations(this.selectedSiteId);
      },
      error: (error) => this.fail(error)
    });
  }

  private updateMaster(kind: MasterKind, id: string, payload: Record<string, string | boolean | null>): void {
    this.saving = true;
    this.registry.updateMaster(this.companyId, kind, id, payload).subscribe({
      next: () => {
        this.saving = false;
        this.successMessage = 'Record updated.';
        this.editingMasterId = '';
        this.masterForm = { code: '', name: '', description: '', address: '', details: '', is_active: true };
        this.refreshMaster(kind);
      },
      error: (error) => this.fail(error)
    });
  }

  deactivateMaster(kind: MasterKind, record: MasterRecord): void {
    if (!window.confirm(`Deactivate ${record.name}?`)) {
      return;
    }
    this.registry.deactivateMaster(this.companyId, kind, record).subscribe({
      next: () => {
        this.successMessage = 'Record deactivated.';
        this.refreshMaster(kind);
      },
      error: (error) => this.fail(error)
    });
  }

  deactivateCurrentMaster(record: MasterRecord): void {
    if (this.activeView === 'departments' || this.activeView === 'sites' || this.activeView === 'categories' || this.activeView === 'cost-centers') {
      this.deactivateMaster(this.activeView, record);
    }
  }

  private refreshMaster(kind: MasterKind): void {
    this.registry.listMaster(this.companyId, kind).subscribe({
      next: (records) => {
        if (kind === 'departments') this.departments = records;
        if (kind === 'sites') this.sites = records;
        if (kind === 'categories') this.categories = records;
        if (kind === 'cost-centers') this.costCenters = records;
      },
      error: (error) => this.fail(error)
    });
  }

  createCompany(): void {
    this.saving = true;
    this.registry.createCompany({
      code: this.companyForm.code.trim(),
      name: this.companyForm.name.trim(),
      number_prefix: this.companyForm.number_prefix.trim()
    }).subscribe({
      next: (company) => {
        this.saving = false;
        this.successMessage = 'Company created with its own default asset numbering rule and six initial categories.';
        this.companies = [...this.companies, company];
        this.companyForm = { code: '', name: '', number_prefix: 'AST', is_active: true };
        this.selectCompany(company.id);
      },
      error: (error) => this.fail(error)
    });
  }

  beginCompanyCreate(): void {
    this.creatingCompany = true;
    this.companyForm = { code: '', name: '', number_prefix: 'AST', is_active: true };
    this.successMessage = '';
  }

  selectCompanyForEdit(company: Company): void {
    this.selectCompany(company.id);
    this.creatingCompany = false;
  }

  saveCompany(): void {
    if (!this.company) {
      return;
    }
    this.registry.updateCompany(this.company.id, { name: this.companyForm.name, is_active: this.companyForm.is_active }).subscribe({
      next: (updated) => {
        this.company = updated;
        this.companies = this.companies.map((item) => item.id === updated.id ? updated : item);
        this.successMessage = 'Company updated.';
      },
      error: (error) => this.fail(error)
    });
  }

  saveNumberRule(): void {
    this.registry.saveNumberRule(
      this.companyId,
      { prefix: this.ruleForm.prefix.trim(), separator: this.ruleForm.separator, padding: Number(this.ruleForm.padding) },
      this.ruleForm.category_id || undefined
    ).subscribe({
      next: (rule) => {
        this.successMessage = 'Numbering rule saved. Existing asset numbers are not changed.';
        this.numberRules = [...this.numberRules.filter((item) => item.category_id !== rule.category_id), rule];
      },
      error: (error) => this.fail(error)
    });
  }

  onRuleCategoryChange(categoryId: string): void {
    const rule = this.numberRules.find((item) => item.category_id === (categoryId || null));
    this.ruleForm = rule
      ? { category_id: categoryId, prefix: rule.prefix, separator: rule.separator, padding: rule.padding }
      : { category_id: categoryId, prefix: 'AST', separator: '-', padding: 6 };
  }

  createAsset(): void {
    const payload: Partial<Asset> = {
      ...this.assetForm,
      category_id: this.assetForm.category_id || undefined,
      site_id: this.assetForm.site_id || undefined,
      location_id: this.assetForm.location_id || undefined,
      responsible_department_id: this.assetForm.responsible_department_id || undefined,
      cost_center_id: this.assetForm.cost_center_id || undefined
    };
    this.saving = true;
    this.registry.createAsset(this.companyId, payload).subscribe({
      next: (asset) => {
        this.saving = false;
        this.successMessage = `Asset ${asset.asset_number} registered.`;
        this.assetForm = { category_id: '', status: 'in_stock', site_id: '', location_id: '', responsible_department_id: '', cost_center_id: '' };
        this.page = 1;
        this.loadAssets();
        this.openAsset(asset);
      },
      error: (error) => this.fail(error)
    });
  }

  openAsset(asset: Asset): void {
    this.activeView = 'assets';
    this.selectedAsset = asset;
    this.assetEditForm = { ...asset };
    this.usageForm = { department_id: '', purpose: '' };
    this.assignmentSiteId = asset.site_id ?? '';
    this.transferSiteId = asset.site_id ?? '';
    this.assignmentForm = {
      recipient_id: '',
      effective_date: this.today(),
      responsible_department_id: asset.responsible_department_id ?? '',
      location_id: asset.location_id ?? '',
      notes: '',
      reference: ''
    };
    this.handoverForm = {
      handover_date: this.today(),
      condition: '',
      included_items: '',
      acknowledgement: '',
      notes: ''
    };
    this.returnForm = {
      return_date: this.today(),
      condition: '',
      notes: '',
      issue_details: '',
      next_asset_status: 'in_stock'
    };
    this.changeDetector.detectChanges();
    const detailsPanel = this.assetDetail?.nativeElement;
    detailsPanel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    detailsPanel?.focus({ preventScroll: true });
    if (asset.site_id) {
      this.loadLocations(asset.site_id);
    } else {
      this.locations = [];
    }
    this.loadAssignmentLocations(this.assignmentSiteId, 'assignment');
    this.loadAssignmentLocations(this.transferSiteId, 'transfer');
    if (this.can('asset.assignment.manage')) {
      this.loadAssignmentRecipients();
    } else {
      this.assignmentRecipients = [];
    }
    this.refreshAssetDetails();
    this.loadServiceContracts();
  }

  refreshAssetDetails(): void {
    if (!this.selectedAsset || !this.companyId) return;
    forkJoin({
      asset: this.registry.getAsset(this.companyId, this.selectedAsset.id),
      usages: this.registry.usages(this.companyId, this.selectedAsset.id, true),
      history: this.registry.history(this.companyId, this.selectedAsset.id),
      assignments: this.registry.assignments(this.companyId, this.selectedAsset.id)
    }).subscribe({
      next: (result) => {
        this.selectedAsset = result.asset;
        this.assetEditForm = { ...result.asset };
        this.selectedUsages = result.usages;
        this.assetHistory = result.history;
        this.assignmentHistory = result.assignments;
        const current = this.currentAssignment;
        if (current) {
          this.transferForm = {
            recipient_id: '',
            effective_date: this.today(),
            reason: '',
            responsible_department_id: current.responsible_department_id ?? '',
            location_id: current.location_id ?? '',
            reference: '',
            condition: '',
            included_items: '',
            acknowledgement: '',
            notes: ''
          };
        }
      },
      error: (error) => this.fail(error)
    });
  }

  loadAssignmentRecipients(): void {
    if (!this.companyId || !this.can('asset.assignment.manage')) return;
    this.assignmentRecipientsLoading = true;
    this.registry.assignmentRecipients(this.companyId).subscribe({
      next: (recipients) => {
        this.assignmentRecipients = recipients;
        this.assignmentRecipientsLoading = false;
      },
      error: (error) => {
        this.assignmentRecipientsLoading = false;
        this.fail(error);
      }
    });
  }

  loadAssignmentLocations(siteId: string, target: 'assignment' | 'transfer'): void {
    if (!siteId || !this.companyId) {
      if (target === 'assignment') this.assignmentLocations = [];
      else this.transferLocations = [];
      return;
    }
    this.registry.listLocations(this.companyId, siteId).subscribe({
      next: (locations) => {
        if (target === 'assignment') this.assignmentLocations = locations.filter((item) => item.is_active);
        else this.transferLocations = locations.filter((item) => item.is_active);
      },
      error: (error) => this.fail(error)
    });
  }

  assignAsset(): void {
    if (!this.selectedAsset || !this.canAssignSelectedAsset || !this.assignmentForm.recipient_id) return;
    if (!window.confirm(`Assign ${this.selectedAsset.asset_number} to the selected recipient?`)) return;
    this.saving = true;
    this.registry.createAssignment(this.companyId, this.selectedAsset.id, {
      ...this.assignmentForm,
      responsible_department_id: this.assignmentForm.responsible_department_id || null,
      location_id: this.assignmentForm.location_id || null
    }).subscribe({
      next: () => this.lifecycleUpdated('Asset assigned.'),
      error: (error) => this.fail(error)
    });
  }

  recordHandover(): void {
    const assignment = this.currentAssignment;
    if (!this.selectedAsset || !assignment) return;
    this.saving = true;
    this.registry.recordHandover(
      this.companyId,
      this.selectedAsset.id,
      assignment.id,
      this.handoverForm
    ).subscribe({
      next: () => this.lifecycleUpdated('Handover recorded.'),
      error: (error) => this.fail(error)
    });
  }

  returnAsset(): void {
    const assignment = this.currentAssignment;
    if (!this.selectedAsset || !assignment) return;
    if (!window.confirm(`Record the return of ${this.selectedAsset.asset_number}?`)) return;
    this.saving = true;
    this.registry.returnAssignment(
      this.companyId,
      this.selectedAsset.id,
      assignment.id,
      this.returnForm
    ).subscribe({
      next: () => this.lifecycleUpdated('Asset return recorded.'),
      error: (error) => this.fail(error)
    });
  }

  transferAsset(): void {
    const assignment = this.currentAssignment;
    if (!this.selectedAsset || !assignment || !this.transferForm.recipient_id) return;
    if (!window.confirm(`Transfer ${this.selectedAsset.asset_number} to the selected recipient?`)) return;
    this.saving = true;
    this.registry.transferAssignment(
      this.companyId,
      this.selectedAsset.id,
      assignment.id,
      {
        ...this.transferForm,
        responsible_department_id: this.transferForm.responsible_department_id || null,
        location_id: this.transferForm.location_id || null
      }
    ).subscribe({
      next: () => this.lifecycleUpdated('Asset transferred; previous custody is retained in history.'),
      error: (error) => this.fail(error)
    });
  }

  private lifecycleUpdated(message: string): void {
    this.saving = false;
    this.successMessage = message;
    this.loadAssets();
    this.refreshAssetDetails();
  }

  saveAsset(): void {
    if (!this.selectedAsset) return;
    this.registry.updateAsset(this.companyId, this.selectedAsset.id, {
      ...this.assetEditForm,
      site_id: this.assetEditForm.site_id || null,
      location_id: this.assetEditForm.location_id || null,
      responsible_department_id: this.assetEditForm.responsible_department_id || null,
      cost_center_id: this.assetEditForm.cost_center_id || null
    }).subscribe({
      next: (updated) => {
        this.selectedAsset = updated;
        this.successMessage = 'Asset updated.';
        this.loadAssets();
        this.refreshAssetDetails();
      },
      error: (error) => this.fail(error)
    });
  }

  addUsage(): void {
    if (!this.selectedAsset || !this.usageForm.department_id) return;
    this.registry.startUsage(this.companyId, this.selectedAsset.id, this.usageForm).subscribe({
      next: () => {
        this.successMessage = 'Department usage started. Custodian and location were not changed.';
        this.usageForm = { department_id: '', purpose: '' };
        this.refreshAssetDetails();
      },
      error: (error) => this.fail(error)
    });
  }

  endUsage(usage: DepartmentUsage): void {
    if (!this.selectedAsset || usage.ended_at || !window.confirm('End this department usage relationship?')) return;
    this.registry.endUsage(this.companyId, this.selectedAsset.id, usage.id).subscribe({
      next: () => {
        this.successMessage = 'Department usage ended; its history is retained.';
        this.refreshAssetDetails();
      },
      error: (error) => this.fail(error)
    });
  }

  categoryName(categoryId: string): string {
    return this.categories.find((item) => item.id === categoryId)?.name ?? 'Unknown category';
  }

  siteName(siteId: string | null): string {
    return this.sites.find((item) => item.id === siteId)?.name ?? '—';
  }

  locationName(locationId: string | null): string {
    for (const site of this.sites) {
      const location = this.locations.find((item) => item.id === locationId);
      if (location && site.id === location.site_id) return location.name;
    }
    return locationId ? 'Location recorded' : '—';
  }

  departmentName(departmentId: string): string {
    return this.departments.find((item) => item.id === departmentId)?.name ?? 'Unknown department';
  }

  loadDashboard(): void {
    if (!this.companyId || !this.can('dashboard.read')) return;
    this.dashboardLoading = true;
    this.dashboardError = '';
    this.registry.dashboard(this.companyId).subscribe({
      next: (data) => {
        this.dashboardData = data;
        this.dashboardLoading = false;
        this.changeDetector.markForCheck();
      },
      error: (err) => {
        this.dashboardLoading = false;
        this.dashboardError = err?.error?.detail || 'Failed to load dashboard metrics.';
        this.changeDetector.markForCheck();
      }
    });
  }

  selectReport(type: ReportType): void {
    this.activeReport = type;
    this.reportSearch = '';
    this.reportStatusFilter = '';
    this.reportCategoryFilter = '';
    this.reportSiteFilter = '';
    this.reportDepartmentFilter = '';
    this.reportSupplierFilter = '';
    this.reportCoverageStatusFilter = '';
    this.reportPriorityFilter = '';
    this.reportDiscrepancyTypeFilter = '';
    this.reportCampaignFilter = '';
    this.loadActiveReport();
  }

  loadActiveReport(): void {
    if (!this.companyId) return;
    this.reportsLoading = true;
    this.reportsError = '';
    if (this.activeReport === 'asset-register') {
      this.registry.reportAssetRegister(this.companyId, {
        status: this.reportStatusFilter || undefined,
        category_id: this.reportCategoryFilter || undefined,
        site_id: this.reportSiteFilter || undefined,
        department_id: this.reportDepartmentFilter || undefined,
        search: this.reportSearch.trim() || undefined,
      }).subscribe({
        next: (items) => {
          this.assetRegisterReport = items;
          this.reportsLoading = false;
          this.changeDetector.markForCheck();
        },
        error: (err) => {
          this.reportsLoading = false;
          this.reportsError = err?.error?.detail || 'Failed to load asset register report.';
          this.changeDetector.markForCheck();
        }
      });
    } else if (this.activeReport === 'asset-allocation') {
      this.registry.reportAssetAllocation(this.companyId, {
        department_id: this.reportDepartmentFilter || undefined,
        site_id: this.reportSiteFilter || undefined,
        search: this.reportSearch.trim() || undefined,
      }).subscribe({
        next: (items) => {
          this.assetAllocationReport = items;
          this.reportsLoading = false;
          this.changeDetector.markForCheck();
        },
        error: (err) => {
          this.reportsLoading = false;
          this.reportsError = err?.error?.detail || 'Failed to load asset allocation report.';
          this.changeDetector.markForCheck();
        }
      });
    } else if (this.activeReport === 'warranty-expiry') {
      this.registry.reportWarrantyExpiry(this.companyId, {
        contract_type: this.reportStatusFilter || undefined,
        coverage_status: this.reportCoverageStatusFilter || undefined,
        search: this.reportSearch.trim() || undefined,
      }).subscribe({
        next: (items) => {
          this.warrantyExpiryReport = items;
          this.reportsLoading = false;
          this.changeDetector.markForCheck();
        },
        error: (err) => {
          this.reportsLoading = false;
          this.reportsError = err?.error?.detail || 'Failed to load warranty and AMC expiry report.';
          this.changeDetector.markForCheck();
        }
      });
    } else if (this.activeReport === 'maintenance') {
      this.registry.reportMaintenance(this.companyId, {
        status: this.reportStatusFilter || undefined,
        priority: this.reportPriorityFilter || undefined,
        search: this.reportSearch.trim() || undefined,
      }).subscribe({
        next: (items) => {
          this.maintenanceReport = items;
          this.reportsLoading = false;
          this.changeDetector.markForCheck();
        },
        error: (err) => {
          this.reportsLoading = false;
          this.reportsError = err?.error?.detail || 'Failed to load maintenance report.';
          this.changeDetector.markForCheck();
        }
      });
    } else if (this.activeReport === 'procurement') {
      this.registry.reportProcurement(this.companyId, {
        status: this.reportStatusFilter || undefined,
        supplier_id: this.reportSupplierFilter || undefined,
        search: this.reportSearch.trim() || undefined,
      }).subscribe({
        next: (items) => {
          this.procurementReport = items;
          this.reportsLoading = false;
          this.changeDetector.markForCheck();
        },
        error: (err) => {
          this.reportsLoading = false;
          this.reportsError = err?.error?.detail || 'Failed to load procurement report.';
          this.changeDetector.markForCheck();
        }
      });
    } else if (this.activeReport === 'verification-campaigns') {
      this.registry.reportVerificationCampaigns(this.companyId, {
        status: this.reportStatusFilter || undefined,
        search: this.reportSearch.trim() || undefined,
      }).subscribe({
        next: (items) => {
          this.verificationCampaignReport = items;
          this.reportsLoading = false;
          this.changeDetector.markForCheck();
        },
        error: (err) => {
          this.reportsLoading = false;
          this.reportsError = err?.error?.detail || 'Failed to load verification campaigns report.';
          this.changeDetector.markForCheck();
        }
      });
    } else if (this.activeReport === 'verification-discrepancies') {
      this.registry.reportVerificationDiscrepancies(this.companyId, {
        campaign_id: this.reportCampaignFilter || undefined,
        discrepancy_type: this.reportDiscrepancyTypeFilter || undefined,
        status: this.reportStatusFilter || undefined,
      }).subscribe({
        next: (items) => {
          this.verificationDiscrepancyReport = items;
          this.reportsLoading = false;
          this.changeDetector.markForCheck();
        },
        error: (err) => {
          this.reportsLoading = false;
          this.reportsError = err?.error?.detail || 'Failed to load verification discrepancies report.';
          this.changeDetector.markForCheck();
        }
      });
    }
  }

  generateReportCsvContent(): string {
    let headers: string[] = [];
    let rows: (string | number | null | undefined)[][] = [];

    if (this.activeReport === 'asset-register') {
      headers = ['Asset Number', 'Category', 'Manufacturer', 'Model', 'Serial Number', 'Status', 'Site', 'Department', 'Custodian', 'Acquisition Date', 'Cost', 'Warranty Start', 'Warranty End'];
      rows = this.assetRegisterReport.map(item => [
        item.asset_number, item.category_name, item.manufacturer ?? '', item.model ?? '', item.serial_number ?? '',
        item.status, item.site_name ?? '', item.department_name ?? '', item.custodian_name ?? '',
        item.acquisition_date ?? '', item.acquisition_cost ?? '', item.warranty_start ?? '', item.warranty_end ?? ''
      ]);
    } else if (this.activeReport === 'asset-allocation') {
      headers = ['Asset Number', 'Model', 'Category', 'Recipient / Custodian', 'Department', 'Site', 'Location', 'Effective Date', 'Status', 'Reference'];
      rows = this.assetAllocationReport.map(item => [
        item.asset_number, item.model ?? '', item.category_name, item.recipient_email ?? '',
        item.department_name ?? '', item.site_name ?? '', item.location_name ?? '',
        item.effective_date ?? '', item.status, item.reference ?? ''
      ]);
    } else if (this.activeReport === 'warranty-expiry') {
      headers = ['Contract Type', 'Reference', 'Provider / Supplier', 'Asset Number', 'Asset Model', 'Start Date', 'End Date', 'Days Remaining', 'Coverage Status', 'Support Contact'];
      rows = this.warrantyExpiryReport.map(item => [
        item.contract_type.toUpperCase(), item.reference_number ?? '', item.supplier_name ?? item.provider_name ?? '',
        item.asset_number, item.asset_model ?? '', item.start_date, item.end_date,
        item.days_remaining, item.coverage_status, item.support_contact ?? ''
      ]);
    } else if (this.activeReport === 'maintenance') {
      headers = ['Title', 'Asset Number', 'Priority', 'Status', 'Requester', 'Assignee', 'Reported Date', 'Completed Date', 'Cost', 'Resolution Notes'];
      rows = this.maintenanceReport.map(item => [
        item.title, item.asset_number, item.priority, item.status, item.requester_email,
        item.assignee_email ?? '', item.reported_date, item.completed_date ?? '', item.cost ?? '', item.resolution_notes ?? ''
      ]);
    } else if (this.activeReport === 'procurement') {
      headers = ['PO Number', 'Supplier', 'Ordered Date', 'Status', 'Total Ordered', 'Total Received', 'Total Outstanding', 'GRN Numbers'];
      rows = this.procurementReport.map(item => [
        item.order_number, item.supplier_name, item.ordered_date, item.order_status,
        item.total_ordered_quantity, item.total_received_quantity, item.total_outstanding_quantity,
        item.receipt_numbers.join('; ')
      ]);
    } else if (this.activeReport === 'verification-campaigns') {
      headers = ['Campaign Ref', 'Name', 'Status', 'Start Date', 'End Date', 'Expected Assets', 'Verified Assets', 'Missing Assets', 'Discrepancies', 'Unregistered', 'Completion %', 'Created At', 'Completed At'];
      rows = this.verificationCampaignReport.map(item => [
        item.campaign_reference, item.campaign_name, item.status, item.start_date, item.end_date,
        item.total_expected, item.total_verified, item.total_missing, item.discrepancy_count,
        item.unregistered_count, item.completion_percentage, item.created_at, item.completed_at ?? ''
      ]);
    } else if (this.activeReport === 'verification-discrepancies') {
      headers = ['Discrepancy ID', 'Campaign Ref', 'Asset Number', 'Discrepancy Type', 'Status', 'Expected Summary', 'Observed Summary', 'Resolution Action', 'Resolution Notes', 'Resolved By', 'Resolved At', 'Created At'];
      rows = this.verificationDiscrepancyReport.map(item => [
        item.discrepancy_id, item.campaign_reference, item.asset_number ?? '', item.discrepancy_type,
        item.status, item.expected_summary ?? '', item.observed_summary ?? '', item.resolution_action ?? '',
        item.resolution_notes ?? '', item.resolved_by_name ?? '', item.resolved_at ?? '', item.created_at
      ]);
    }

    const UTF8_BOM = '\uFEFF';
    return UTF8_BOM + [
      headers.map(h => serializeCsvCell(h)).join(','),
      ...rows.map(row => row.map(cell => serializeCsvCell(cell)).join(','))
    ].join('\r\n');
  }

  exportReportCsv(): void {
    const filename = `mindzen-${this.activeReport}-${this.today()}.csv`;
    const csvContent = this.generateReportCsvContent();

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  objectKeys(obj: Record<string, any> | undefined | null): string[] {
    return Object.keys(obj || {});
  }

  statusEntries(obj: Record<string, number> | undefined | null): { status: string; count: number }[] {
    return Object.entries(obj || {}).map(([status, count]) => ({ status, count }));
  }

  formatStatus(status: string | undefined | null): string {
    return (status || '').replace(/_/g, ' ');
  }

  readonly todayDate: Date = new Date();
  readonly todayDateIso: string = this.todayDate.toISOString();

  calculatePercentage(count: number | undefined | null, total: number | undefined | null): number {
    if (!total || total <= 0 || !count || count <= 0) return 0;
    return Math.min(100, Math.round((count / total) * 100));
  }

  getStatusSlices(): { status: string; label: string; count: number; percentage: number; color: string }[] {
    if (!this.dashboardData || !this.dashboardData.assets_by_status) return [];
    const total = this.dashboardData.total_assets;
    const statusColorMap: Record<string, string> = {
      in_stock: '#16a34a',     // Emerald/Green
      assigned: '#2563eb',     // Blue
      maintenance: '#f59e0b',  // Amber/Orange
      disposed: '#64748b',     // Slate/Gray
    };
    const fallbackColors = ['#8b5cf6', '#ec4899', '#06b6d4', '#eab308'];
    let fallbackIndex = 0;

    return Object.entries(this.dashboardData.assets_by_status).map(([status, count]) => {
      const percentage = this.calculatePercentage(count, total);
      const color = statusColorMap[status] || fallbackColors[(fallbackIndex++) % fallbackColors.length];
      return {
        status,
        label: this.formatStatus(status),
        count,
        percentage,
        color,
      };
    });
  }

  getStatusDonutGradient(): string {
    if (!this.dashboardData || this.dashboardData.total_assets <= 0) {
      return 'conic-gradient(#e2e8f0 0% 100%)';
    }
    const slices = this.getStatusSlices();
    if (slices.length === 0) {
      return 'conic-gradient(#e2e8f0 0% 100%)';
    }
    let currentPct = 0;
    const parts: string[] = [];
    for (const slice of slices) {
      const nextPct = Math.min(100, currentPct + slice.percentage);
      parts.push(`${slice.color} ${currentPct}% ${nextPct}%`);
      currentPct = nextPct;
    }
    if (currentPct < 100 && slices.length > 0) {
      parts.push(`${slices[slices.length - 1].color} ${currentPct}% 100%`);
    }
    return `conic-gradient(${parts.join(', ')})`;
  }

  getExpiryBadgeClass(daysRemaining: number): string {
    if (daysRemaining < 0) return 'status-expired';
    if (daysRemaining <= 7) return 'status-urgent';
    return 'status-expiring_soon';
  }

  getExpiryLabel(daysRemaining: number): string {
    if (daysRemaining < 0) return `${Math.abs(daysRemaining)}d overdue`;
    if (daysRemaining === 0) return 'Expires today';
    if (daysRemaining <= 7) return `${daysRemaining}d left (Urgent)`;
    return `${daysRemaining}d left`;
  }

  formatAuditAction(action: string | undefined | null): string {
    if (!action) return 'Activity';
    return action
      .replace(/[._]/g, ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  navigateToAssets(status?: string): void {
    if (!this.can('asset.read')) return;
    this.filters = {
      search: '',
      category_id: '',
      status: status ?? '',
      site_id: '',
      location_id: '',
      department_id: '',
    };
    this.page = 1;
    this.setView('assets');
  }

  filterByCategory(categoryId: string): void {
    if (!this.can('asset.read')) return;
    this.filters = {
      search: '',
      category_id: categoryId,
      status: '',
      site_id: '',
      location_id: '',
      department_id: '',
    };
    this.page = 1;
    this.setView('assets');
  }

  filterByDepartment(departmentId: string | null): void {
    if (!this.can('asset.read') || !departmentId) return;
    this.filters = {
      search: '',
      category_id: '',
      status: '',
      site_id: '',
      location_id: '',
      department_id: departmentId,
    };
    this.page = 1;
    this.setView('assets');
  }

  navigateToContracts(): void {
    if (this.can('maintenance.read')) {
      this.selectReport('warranty-expiry');
      this.setView('reports');
    }
  }

  navigateToMaintenance(): void {
    if (this.can('maintenance.read')) {
      this.setView('maintenance');
    }
  }

  navigateToProcurement(): void {
    if (this.can('procurement.read')) {
      this.setView('procurement');
    }
  }

  isReportEmpty(): boolean {
    if (this.activeReport === 'asset-register') return this.assetRegisterReport.length === 0;
    if (this.activeReport === 'asset-allocation') return this.assetAllocationReport.length === 0;
    if (this.activeReport === 'warranty-expiry') return this.warrantyExpiryReport.length === 0;
    if (this.activeReport === 'maintenance') return this.maintenanceReport.length === 0;
    if (this.activeReport === 'procurement') return this.procurementReport.length === 0;
    if (this.activeReport === 'verification-campaigns') return this.verificationCampaignReport.length === 0;
    if (this.activeReport === 'verification-discrepancies') return this.verificationDiscrepancyReport.length === 0;
    return true;
  }

  resetReportFilters(): void {
    this.reportSearch = '';
    this.reportStatusFilter = '';
    this.reportCategoryFilter = '';
    this.reportSiteFilter = '';
    this.reportDepartmentFilter = '';
    this.reportSupplierFilter = '';
    this.reportCoverageStatusFilter = '';
    this.reportPriorityFilter = '';
    this.reportDiscrepancyTypeFilter = '';
    this.reportCampaignFilter = '';
    this.loadActiveReport();
  }

  loadAllLocations(): void {
    if (!this.companyId || !this.sites.length) return;
    forkJoin(this.sites.map(s => this.registry.listLocations(this.companyId, s.id))).subscribe({
      next: (results) => {
        this.allLocations = results.flat();
        this.changeDetector.markForCheck();
      },
      error: () => {}
    });
  }

  loadVerification(): void {
    if (!this.companyId || !this.can('verification.read')) return;
    this.verificationLoading = true;
    this.loadAllLocations();
    if (!this.assignmentRecipients.length && this.can('asset.assignment.manage')) {
      this.loadAssignmentRecipients();
    }
    this.registry.listVerificationCampaigns(this.companyId, {
      status: this.verificationStatusFilter !== 'all' ? this.verificationStatusFilter : undefined,
      search: this.verificationSearch.trim() || undefined
    }).subscribe({
      next: (campaigns) => {
        this.verificationCampaigns = campaigns;
        this.verificationLoading = false;
        if (this.selectedCampaign) {
          const updated = campaigns.find(c => c.id === this.selectedCampaign?.id);
          if (updated) {
            this.selectedCampaign = updated;
            this.refreshSelectedCampaignData();
          } else {
            this.registry.getVerificationCampaign(this.companyId, this.selectedCampaign.id).subscribe({
              next: (c) => {
                this.selectedCampaign = c;
                this.refreshSelectedCampaignData();
              },
              error: () => {
                this.selectedCampaign = undefined;
              }
            });
          }
        }
        this.changeDetector.markForCheck();
      },
      error: (err) => {
        this.verificationLoading = false;
        this.fail(err);
      }
    });
  }

  selectVerificationCampaign(campaign: VerificationCampaign): void {
    this.selectedCampaign = campaign;
    this.verificationSubView = 'expected';
    this.expectedSearch = '';
    this.expectedVerifiedFilter = undefined;
    this.expectedCategoryFilter = '';
    this.expectedLocationFilter = '';
    this.discrepancyTypeFilter = 'all';
    this.discrepancyStatusFilter = 'all';
    this.unregisteredStatusFilter = 'all';
    this.refreshSelectedCampaignData();
  }

  clearSelectedCampaign(): void {
    this.selectedCampaign = undefined;
    this.loadVerification();
  }

  refreshSelectedCampaignData(): void {
    if (!this.companyId || !this.selectedCampaign) return;
    const cid = this.companyId;
    const campId = this.selectedCampaign.id;

    this.registry.getVerificationDashboard(cid, campId).subscribe({
      next: (summary) => {
        this.campaignDashboard = summary;
        this.changeDetector.markForCheck();
      },
      error: () => {}
    });

    this.loadExpectedAssets();
    this.loadDiscrepancies();
    this.loadUnregisteredAssets();
  }

  loadExpectedAssets(): void {
    if (!this.companyId || !this.selectedCampaign) return;
    this.registry.getVerificationExpectedAssets(this.companyId, this.selectedCampaign.id, {
      search: this.expectedSearch.trim() || undefined,
      verified: this.expectedVerifiedFilter,
      category_id: this.expectedCategoryFilter || undefined,
      location_id: this.expectedLocationFilter || undefined
    }).subscribe({
      next: (items) => {
        this.campaignExpectedAssets = items;
        this.changeDetector.markForCheck();
      },
      error: (err) => this.fail(err)
    });
  }

  loadDiscrepancies(): void {
    if (!this.companyId || !this.selectedCampaign) return;
    this.registry.getVerificationDiscrepancies(this.companyId, this.selectedCampaign.id, {
      discrepancy_type: this.discrepancyTypeFilter !== 'all' ? this.discrepancyTypeFilter : undefined,
      status: this.discrepancyStatusFilter !== 'all' ? this.discrepancyStatusFilter : undefined
    }).subscribe({
      next: (items) => {
        this.campaignDiscrepancies = items;
        this.changeDetector.markForCheck();
      },
      error: (err) => this.fail(err)
    });
  }

  loadUnregisteredAssets(): void {
    if (!this.companyId || !this.selectedCampaign) return;
    this.registry.getUnregisteredAssets(this.companyId, this.selectedCampaign.id, this.unregisteredStatusFilter !== 'all' ? this.unregisteredStatusFilter : undefined).subscribe({
      next: (items) => {
        this.campaignUnregisteredAssets = items;
        this.changeDetector.markForCheck();
      },
      error: (err) => this.fail(err)
    });
  }

  openCreateCampaignModal(): void {
    this.campaignCreateForm = {
      campaign_reference: '',
      name: '',
      description: '',
      start_date: this.today(),
      end_date: this.today(),
      scope_category_ids: [],
      scope_location_ids: []
    };
    this.campaignCreateModalOpen = true;
  }

  closeCreateCampaignModal(): void {
    this.campaignCreateModalOpen = false;
  }

  submitCreateCampaign(): void {
    if (!this.companyId || !this.campaignCreateForm.campaign_reference.trim() || !this.campaignCreateForm.name.trim()) return;
    this.saving = true;
    this.registry.createVerificationCampaign(this.companyId, {
      ...this.campaignCreateForm,
      campaign_reference: this.campaignCreateForm.campaign_reference.trim(),
      name: this.campaignCreateForm.name.trim(),
      scope_category_ids: this.campaignCreateForm.scope_category_ids?.length ? this.campaignCreateForm.scope_category_ids : null,
      scope_location_ids: this.campaignCreateForm.scope_location_ids?.length ? this.campaignCreateForm.scope_location_ids : null
    }).subscribe({
      next: (campaign) => {
        this.saving = false;
        this.campaignCreateModalOpen = false;
        this.successMessage = `Campaign "${campaign.name}" (${campaign.campaign_reference}) created successfully.`;
        this.loadVerification();
        this.selectVerificationCampaign(campaign);
      },
      error: (err) => {
        this.saving = false;
        this.fail(err);
      }
    });
  }

  transitionCampaignStatus(status: string): void {
    if (!this.companyId || !this.selectedCampaign) return;
    if (status === 'cancelled' && !window.confirm('Are you sure you want to cancel this verification campaign? This cannot be undone.')) {
      return;
    }
    this.saving = true;
    this.registry.transitionVerificationCampaignStatus(this.companyId, this.selectedCampaign.id, status).subscribe({
      next: (updated) => {
        this.saving = false;
        this.selectedCampaign = updated;
        this.successMessage = `Campaign status updated to ${this.formatStatus(status)}.`;
        this.refreshSelectedCampaignData();
        this.registry.listVerificationCampaigns(this.companyId).subscribe(list => {
          this.verificationCampaigns = list;
          this.changeDetector.markForCheck();
        });
      },
      error: (err) => {
        this.saving = false;
        this.fail(err);
      }
    });
  }

  openRecordObservationModal(expectedAsset: VerificationExpectedAsset): void {
    this.selectedExpectedAsset = expectedAsset;
    this.observationForm = {
      is_found: true,
      actual_location_id: expectedAsset.expected_location_id || '',
      actual_custodian_id: expectedAsset.expected_custodian_id || '',
      observed_condition: expectedAsset.expected_condition || 'good',
      remarks: '',
      reference_notes: ''
    };
    this.observationModalOpen = true;
  }

  closeRecordObservationModal(): void {
    this.observationModalOpen = false;
    this.selectedExpectedAsset = undefined;
  }

  submitObservation(): void {
    if (!this.companyId || !this.selectedCampaign || !this.selectedExpectedAsset) return;
    this.saving = true;
    this.registry.recordVerificationObservation(this.companyId, this.selectedCampaign.id, this.selectedExpectedAsset.id, {
      ...this.observationForm,
      actual_location_id: this.observationForm.is_found && this.observationForm.actual_location_id ? this.observationForm.actual_location_id : null,
      actual_custodian_id: this.observationForm.is_found && this.observationForm.actual_custodian_id ? this.observationForm.actual_custodian_id : null,
      verification_date: this.today()
    }).subscribe({
      next: () => {
        this.saving = false;
        this.observationModalOpen = false;
        this.successMessage = `Observation recorded for asset ${this.selectedExpectedAsset?.asset_number}.`;
        this.selectedExpectedAsset = undefined;
        this.refreshSelectedCampaignData();
      },
      error: (err) => {
        this.saving = false;
        this.fail(err);
      }
    });
  }

  openResolveDiscrepancyModal(d: VerificationDiscrepancy): void {
    this.selectedDiscrepancy = d;
    this.resolveDiscrepancyForm = {
      resolution_action: d.discrepancy_type === 'missing' ? 'mark_missing' : 'update_master',
      resolution_notes: ''
    };
    this.resolveDiscrepancyModalOpen = true;
  }

  closeResolveDiscrepancyModal(): void {
    this.resolveDiscrepancyModalOpen = false;
    this.selectedDiscrepancy = undefined;
  }

  submitResolveDiscrepancy(): void {
    if (!this.companyId || !this.selectedCampaign || !this.selectedDiscrepancy || !this.resolveDiscrepancyForm.resolution_notes.trim()) return;
    this.saving = true;
    this.registry.resolveVerificationDiscrepancy(this.companyId, this.selectedCampaign.id, this.selectedDiscrepancy.id, {
      ...this.resolveDiscrepancyForm,
      resolution_notes: this.resolveDiscrepancyForm.resolution_notes.trim()
    }).subscribe({
      next: () => {
        this.saving = false;
        const action = this.resolveDiscrepancyForm.resolution_action;
        this.resolveDiscrepancyModalOpen = false;
        this.successMessage = `Discrepancy resolved with action "${this.formatStatus(action)}".`;
        this.selectedDiscrepancy = undefined;
        this.refreshSelectedCampaignData();
        if (action === 'update_master' || action === 'mark_missing') {
          this.loadAssets();
        }
      },
      error: (err) => {
        this.saving = false;
        this.fail(err);
      }
    });
  }

  openRecordUnregisteredModal(): void {
    this.unregisteredForm = {
      description: '',
      category_id: this.categories[0]?.id || '',
      serial_number: '',
      site_id: this.sites[0]?.id || '',
      location_id: '',
      custodian_id: '',
      observed_condition: 'good',
      remarks: ''
    };
    this.unregisteredModalOpen = true;
  }

  closeRecordUnregisteredModal(): void {
    this.unregisteredModalOpen = false;
  }

  submitRecordUnregistered(): void {
    if (!this.companyId || !this.selectedCampaign || !this.unregisteredForm.description.trim() || !this.unregisteredForm.category_id) return;
    this.saving = true;
    this.registry.recordUnregisteredAsset(this.companyId, this.selectedCampaign.id, {
      ...this.unregisteredForm,
      description: this.unregisteredForm.description.trim(),
      serial_number: this.unregisteredForm.serial_number?.trim() || null,
      site_id: this.unregisteredForm.site_id || null,
      location_id: this.unregisteredForm.location_id || null,
      custodian_id: this.unregisteredForm.custodian_id || null,
      remarks: this.unregisteredForm.remarks?.trim() || null
    }).subscribe({
      next: () => {
        this.saving = false;
        this.unregisteredModalOpen = false;
        this.successMessage = `Unregistered asset discovery recorded.`;
        this.refreshSelectedCampaignData();
      },
      error: (err) => {
        this.saving = false;
        this.fail(err);
      }
    });
  }

  openRegisterUnregisteredModal(u: VerificationUnregisteredAsset): void {
    this.selectedUnregisteredAsset = u;
    this.registerUnregisteredForm = {
      asset_number: '',
      cost_center_id: this.costCenters[0]?.id || '',
      responsible_department_id: this.departments[0]?.id || '',
      acquisition_cost: null,
      acquisition_date: this.today(),
      resolution_notes: `Registered from verification discovery in campaign ${this.selectedCampaign?.campaign_reference}`
    };
    this.registerUnregisteredModalOpen = true;
  }

  closeRegisterUnregisteredModal(): void {
    this.registerUnregisteredModalOpen = false;
    this.selectedUnregisteredAsset = undefined;
  }

  submitRegisterUnregistered(): void {
    if (!this.companyId || !this.selectedCampaign || !this.selectedUnregisteredAsset || !this.registerUnregisteredForm.resolution_notes.trim()) return;
    this.saving = true;
    this.registry.registerUnregisteredAsset(this.companyId, this.selectedCampaign.id, this.selectedUnregisteredAsset.id, {
      ...this.registerUnregisteredForm,
      asset_number: this.registerUnregisteredForm.asset_number?.trim() || null,
      cost_center_id: this.registerUnregisteredForm.cost_center_id || null,
      responsible_department_id: this.registerUnregisteredForm.responsible_department_id || null,
      acquisition_date: this.registerUnregisteredForm.acquisition_date || this.today(),
      resolution_notes: this.registerUnregisteredForm.resolution_notes.trim()
    }).subscribe({
      next: (result) => {
        this.saving = false;
        this.registerUnregisteredModalOpen = false;
        this.successMessage = `Asset registered as ${result.registered_asset_number}.`;
        this.selectedUnregisteredAsset = undefined;
        this.refreshSelectedCampaignData();
        this.loadAssets();
      },
      error: (err) => {
        this.saving = false;
        this.fail(err);
      }
    });
  }

  isCategoryInScope(categoryId: string): boolean {
    return (this.campaignCreateForm.scope_category_ids || []).includes(categoryId);
  }

  toggleCategoryScope(categoryId: string): void {
    const list = this.campaignCreateForm.scope_category_ids ? [...this.campaignCreateForm.scope_category_ids] : [];
    const idx = list.indexOf(categoryId);
    if (idx > -1) {
      list.splice(idx, 1);
    } else {
      list.push(categoryId);
    }
    this.campaignCreateForm.scope_category_ids = list;
  }

  isLocationInScope(locationId: string): boolean {
    return (this.campaignCreateForm.scope_location_ids || []).includes(locationId);
  }

  toggleLocationScope(locationId: string): void {
    const list = this.campaignCreateForm.scope_location_ids ? [...this.campaignCreateForm.scope_location_ids] : [];
    const idx = list.indexOf(locationId);
    if (idx > -1) {
      list.splice(idx, 1);
    } else {
      list.push(locationId);
    }
    this.campaignCreateForm.scope_location_ids = list;
  }

  formatDiscrepancyType(type: string | undefined | null): string {
    if (!type) return '—';
    return type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  formatDiscrepancyStatus(status: string | undefined | null): string {
    return this.formatStatus(status);
  }

  discrepancyTypeBadgeClass(type: string): string {
    switch (type) {
      case 'missing': return 'status-cancelled';
      case 'location_mismatch': return 'status-expiring_soon';
      case 'custodian_mismatch': return 'status-assigned';
      case 'condition_mismatch': return 'status-maintenance';
      case 'unregistered_found': return 'status-active';
      default: return 'status-in_stock';
    }
  }

  campaignStatusBadgeClass(status: string): string {
    switch (status) {
      case 'draft': return 'status-in_stock';
      case 'in_progress': return 'status-active';
      case 'under_review': return 'status-expiring_soon';
      case 'completed': return 'status-assigned';
      case 'cancelled': return 'status-cancelled';
      default: return 'status-in_stock';
    }
  }

  private today(): string {

    const now = new Date();
    const localDate = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
    return localDate.toISOString().slice(0, 10);
  }

  private fail(error: { error?: { detail?: string | { message?: string } | Array<{ msg?: string; loc?: (string | number)[] }> }; message?: string }): void {
    this.loading = false;
    this.saving = false;
    const detail = error.error?.detail;
    if (typeof detail === 'string') {
      this.errorMessage = detail;
    } else if (Array.isArray(detail)) {
      this.errorMessage = detail
        .map((d) => {
          const field = Array.isArray(d.loc) ? d.loc.filter((part) => part !== 'body').join(' -> ') : '';
          return field ? `${field}: ${d.msg}` : (d.msg || JSON.stringify(d));
        })
        .join('; ') || 'Validation error.';
    } else {
      this.errorMessage = detail?.message ?? error.message ?? 'Request failed.';
    }
    this.changeDetector.markForCheck();
  }
}
