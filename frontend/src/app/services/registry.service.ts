import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

export interface Company {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
}

export interface CompanyRole {
  code: string;
  name: string;
  scope: string;
  permissions: string[];
}

export interface CompanyMember {
  id: string;
  email: string;
  membership_id: string;
  status: string;
  role_code: string;
  role_name: string;
  created_at: string;
}

export interface Invitation {
  email: string;
  company_id: string;
  role_code: string;
  token: string;
  expires_at: string;
}

export interface MasterRecord {
  id: string;
  company_id: string;
  code: string;
  name: string;
  is_active: boolean;
  address?: string | null;
  details?: string | null;
  description?: string | null;
  site_id?: string;
}

export interface NumberRule {
  id: string;
  category_id: string | null;
  prefix: string;
  separator: string;
  padding: number;
}

export interface Asset {
  id: string;
  company_id: string;
  category_id: string;
  asset_number: string;
  serial_number: string | null;
  manufacturer: string | null;
  model: string | null;
  acquisition_date: string | null;
  acquisition_cost: string | null;
  status: string;
  site_id: string | null;
  location_id: string | null;
  responsible_department_id: string | null;
  cost_center_id: string | null;
  custodian_name: string | null;
  vendor_reference: string | null;
  invoice_reference: string | null;
  warranty_start: string | null;
  warranty_end: string | null;
  notes: string | null;
}

export interface AssetPage {
  items: Asset[];
  total: number;
  page: number;
  page_size: number;
}

export interface DepartmentUsage {
  id: string;
  department_id: string;
  purpose: string | null;
  started_at: string;
  ended_at: string | null;
}

export interface AssetHistory {
  id: string;
  event_type: string;
  field_name: string | null;
  old_value: string | null;
  new_value: string | null;
  occurred_at: string;
}

export interface AssignmentRecipient {
  id: string;
  email: string;
}

export interface AssetAssignment {
  id: string;
  company_id: string;
  asset_id: string;
  recipient_id: string;
  recipient_email: string;
  responsible_department_id: string | null;
  location_id: string | null;
  effective_date: string;
  status: 'active' | 'returned' | 'transferred';
  notes: string | null;
  reference: string | null;
  handover_date: string | null;
  handover_condition: string | null;
  included_items: string | null;
  acknowledgement: string | null;
  handover_notes: string | null;
  ended_at: string | null;
  return_date: string | null;
  return_condition: string | null;
  return_notes: string | null;
  issue_details: string | null;
  next_asset_status: string | null;
  transfer_reason: string | null;
  previous_assignment_id: string | null;
  created_at: string;
}

export interface ProcurementSupplier {
  id: string;
  company_id: string;
  code: string;
  name: string;
  email: string | null;
  phone: string | null;
  notes: string | null;
  is_active: boolean;
  created_at: string;
}

export interface PurchaseOrderLine {
  id: string;
  company_id: string;
  purchase_order_id: string;
  category_id: string;
  description: string;
  quantity_ordered: number;
  unit_cost: string;
  discount?: string;
  tax_rate?: string;
  tax_amount?: string;
  line_subtotal?: string;
  line_total?: string;
  quantity_received?: number;
  quantity_remaining?: number;
}

export interface PurchaseOrder {
  id: string;
  company_id: string;
  supplier_id: string;
  order_number: string;
  status: 'open' | 'partially_received' | 'received';
  ordered_date: string;
  expected_date: string | null;
  notes: string | null;
  created_at: string;
  lines: PurchaseOrderLine[];
  total_quantity?: number;
  subtotal?: string;
  total_discount?: string;
  total_tax?: string;
  total_amount?: string;
}

export interface GoodsReceiptAsset {
  id: string;
  asset_number: string;
  serial_number: string | null;
  status: string;
}

export interface GoodsReceiptLine {
  id: string;
  purchase_order_line_id: string;
  quantity_received: number;
  quantity_rejected: number;
  discrepancy_notes: string | null;
  assets: GoodsReceiptAsset[];
}

export interface GoodsReceipt {
  id: string;
  company_id: string;
  purchase_order_id: string;
  receipt_number: string;
  received_date: string;
  delivery_reference: string | null;
  notes: string | null;
  created_at: string;
  lines: GoodsReceiptLine[];
}

export interface AssetServiceContract {
  id: string;
  company_id: string;
  asset_id: string;
  supplier_id: string | null;
  contract_type: 'warranty' | 'amc';
  provider_name: string | null;
  reference_number: string | null;
  start_date: string;
  end_date: string;
  coverage_description: string | null;
  support_contact: string | null;
  notes: string | null;
  status: 'active' | 'cancelled';
  coverage_status: 'active' | 'expiring_soon' | 'upcoming' | 'expired' | 'cancelled';
  created_at: string;
}

export type MaintenanceStatus = 'open' | 'in_progress' | 'resolved' | 'closed';
export type MaintenancePriority = 'low' | 'normal' | 'high' | 'urgent';

export interface MaintenanceRequest {
  id: string;
  company_id: string;
  asset_id: string;
  asset_number: string;
  requester_id: string;
  requester_email: string;
  assignee_id: string | null;
  assignee_email: string | null;
  title: string;
  issue_description: string;
  priority: MaintenancePriority;
  status: MaintenanceStatus;
  reported_date: string;
  diagnosis: string | null;
  work_performed: string | null;
  resolution_notes: string | null;
  completed_date: string | null;
  cost: string | null;
  created_at: string;
  updated_at: string;
}

export interface CategoryMetric {
  category_id: string;
  category_name: string;
  count: number;
}

export interface SiteMetric {
  site_id: string | null;
  site_name: string;
  count: number;
}

export interface DepartmentMetric {
  department_id: string | null;
  department_name: string;
  count: number;
}

export interface ExpiringContractMetric {
  id: string;
  contract_type: string;
  reference_number: string | null;
  provider_name: string | null;
  asset_id: string;
  asset_number: string;
  end_date: string;
  days_remaining: number;
}

export interface MaintenanceSummaryMetric {
  open: number;
  in_progress: number;
  resolved: number;
  closed: number;
  total_open_and_in_progress: number;
}

export interface ProcurementSummaryMetric {
  total_purchase_orders: number;
  orders_by_status: Record<string, number>;
  total_goods_receipts: number;
  total_items_received: number;
  total_items_rejected: number;
}

export interface RecentActivityMetric {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  actor_id: string | null;
  actor_email: string | null;
  outcome: string;
  occurred_at: string;
}

export interface DashboardData {
  total_assets: number;
  assets_by_status: Record<string, number>;
  assets_by_category: CategoryMetric[];
  assets_by_site: SiteMetric[];
  assets_by_department: DepartmentMetric[];
  expiring_contracts_count: number;
  expiring_contracts: ExpiringContractMetric[];
  maintenance_summary: MaintenanceSummaryMetric;
  procurement_summary: ProcurementSummaryMetric;
  recent_activity: RecentActivityMetric[];
}

export interface AssetRegisterReportItem {
  id: string;
  asset_number: string;
  category_id: string;
  category_name: string;
  manufacturer: string | null;
  model: string | null;
  serial_number: string | null;
  status: string;
  site_id: string | null;
  site_name: string | null;
  department_id: string | null;
  department_name: string | null;
  custodian_name: string | null;
  acquisition_date: string | null;
  acquisition_cost: number | string | null;
  warranty_start: string | null;
  warranty_end: string | null;
}

export interface AssetAllocationReportItem {
  assignment_id: string | null;
  asset_id: string;
  asset_number: string;
  model: string | null;
  category_name: string;
  recipient_id: string | null;
  recipient_email: string | null;
  department_id: string | null;
  department_name: string | null;
  site_id: string | null;
  site_name: string | null;
  location_id: string | null;
  location_name: string | null;
  effective_date: string | null;
  status: string;
  reference: string | null;
}

export interface WarrantyExpiryReportItem {
  id: string;
  contract_type: string;
  reference_number: string | null;
  provider_name: string | null;
  supplier_name: string | null;
  asset_id: string;
  asset_number: string;
  asset_model: string | null;
  start_date: string;
  end_date: string;
  days_remaining: number;
  status: string;
  coverage_status: string;
  support_contact: string | null;
}

export interface MaintenanceReportItem {
  id: string;
  title: string;
  asset_id: string;
  asset_number: string;
  priority: string;
  status: string;
  requester_email: string;
  assignee_email: string | null;
  reported_date: string;
  completed_date: string | null;
  cost: number | string | null;
  diagnosis: string | null;
  work_performed: string | null;
  resolution_notes: string | null;
}

export interface ProcurementReportLineItem {
  line_id: string;
  category_id: string;
  category_name: string;
  description: string;
  quantity_ordered: number;
  quantity_received: number;
  quantity_rejected: number;
  quantity_outstanding: number;
  unit_cost: number | string;
}

export interface ProcurementReportItem {
  order_id: string;
  order_number: string;
  supplier_id: string;
  supplier_name: string;
  ordered_date: string;
  expected_date: string | null;
  order_status: string;
  total_ordered_quantity: number;
  total_received_quantity: number;
  total_outstanding_quantity: number;
  lines: ProcurementReportLineItem[];
  receipt_numbers: string[];
}

@Injectable({ providedIn: 'root' })
export class RegistryService {

  private readonly base = `${environment.apiBaseUrl}`;

  constructor(private readonly http: HttpClient) {}

  companies(): Observable<Company[]> {
    return this.http.get<Company[]>(`${this.base}/companies`);
  }

  createCompany(payload: { code: string; name: string; number_prefix: string }): Observable<Company> {
    return this.http.post<Company>(`${this.base}/companies`, payload);
  }

  updateCompany(companyId: string, payload: Partial<Pick<Company, 'name' | 'is_active'>>): Observable<Company> {
    return this.http.patch<Company>(`${this.base}/companies/${companyId}`, payload);
  }

  companyRoles(companyId: string): Observable<CompanyRole[]> {
    return this.http.get<CompanyRole[]>(`${this.base}/security/companies/${companyId}/roles`);
  }

  companyMembers(companyId: string): Observable<CompanyMember[]> {
    return this.http.get<CompanyMember[]>(`${this.base}/security/companies/${companyId}/members`);
  }

  inviteMember(companyId: string, email: string, roleCode: string): Observable<Invitation> {
    return this.http.post<Invitation>(`${this.base}/security/companies/${companyId}/invitations`, {
      email,
      role_code: roleCode
    });
  }

  updateMembership(companyId: string, membershipId: string, status: 'revoked'): Observable<CompanyMember> {
    return this.http.patch<CompanyMember>(
      `${this.base}/security/companies/${companyId}/members/${membershipId}`,
      { status }
    );
  }

  listMaster(companyId: string, kind: 'departments' | 'sites' | 'categories' | 'cost-centers'): Observable<MasterRecord[]> {
    return this.http.get<MasterRecord[]>(`${this.base}/companies/${companyId}/${kind}`);
  }

  createMaster(
    companyId: string,
    kind: 'departments' | 'sites' | 'categories' | 'cost-centers',
    payload: Record<string, string | boolean | null>
  ): Observable<MasterRecord> {
    return this.http.post<MasterRecord>(`${this.base}/companies/${companyId}/${kind}`, payload);
  }

  updateMaster(
    companyId: string,
    kind: 'departments' | 'sites' | 'categories' | 'cost-centers',
    id: string,
    payload: Record<string, string | boolean | null>
  ): Observable<MasterRecord> {
    return this.http.patch<MasterRecord>(`${this.base}/companies/${companyId}/${kind}/${id}`, payload);
  }

  deactivateMaster(companyId: string, kind: 'departments' | 'sites' | 'categories' | 'cost-centers', record: MasterRecord): Observable<MasterRecord> {
    if (kind === 'departments') {
      return this.http.delete<MasterRecord>(`${this.base}/companies/${companyId}/${kind}/${record.id}`);
    }
    return this.http.patch<MasterRecord>(`${this.base}/companies/${companyId}/${kind}/${record.id}`, { is_active: false });
  }

  listLocations(companyId: string, siteId: string): Observable<MasterRecord[]> {
    return this.http.get<MasterRecord[]>(`${this.base}/companies/${companyId}/sites/${siteId}/locations`);
  }

  createLocation(companyId: string, siteId: string, payload: Record<string, string | boolean | null>): Observable<MasterRecord> {
    return this.http.post<MasterRecord>(`${this.base}/companies/${companyId}/sites/${siteId}/locations`, payload);
  }

  updateLocation(companyId: string, siteId: string, locationId: string, payload: Record<string, string | boolean | null>): Observable<MasterRecord> {
    return this.http.patch<MasterRecord>(
      `${this.base}/companies/${companyId}/sites/${siteId}/locations/${locationId}`,
      payload
    );
  }

  deactivateLocation(companyId: string, siteId: string, location: MasterRecord): Observable<MasterRecord> {
    return this.http.patch<MasterRecord>(
      `${this.base}/companies/${companyId}/sites/${siteId}/locations/${location.id}`,
      { is_active: false }
    );
  }

  listNumberRules(companyId: string): Observable<NumberRule[]> {
    return this.http.get<NumberRule[]>(`${this.base}/companies/${companyId}/numbering-rules`);
  }

  saveNumberRule(companyId: string, payload: { prefix: string; separator: string; padding: number }, categoryId?: string): Observable<NumberRule> {
    let params = new HttpParams();
    if (categoryId) {
      params = params.set('category_id', categoryId);
    }
    return this.http.put<NumberRule>(`${this.base}/companies/${companyId}/numbering-rules`, payload, { params });
  }

  listAssets(companyId: string, filters: {
    page: number;
    page_size: number;
    search?: string;
    category_id?: string;
    status?: string;
    site_id?: string;
    location_id?: string;
    department_id?: string;
  }): Observable<AssetPage> {
    let params = new HttpParams().set('page', filters.page).set('page_size', filters.page_size);
    for (const [key, value] of Object.entries(filters)) {
      if (key !== 'page' && key !== 'page_size' && value) {
        params = params.set(key, value);
      }
    }
    return this.http.get<AssetPage>(`${this.base}/companies/${companyId}/assets`, { params });
  }

  getAsset(companyId: string, assetId: string): Observable<Asset> {
    return this.http.get<Asset>(`${this.base}/companies/${companyId}/assets/${assetId}`);
  }

  createAsset(companyId: string, payload: Partial<Asset>): Observable<Asset> {
    return this.http.post<Asset>(`${this.base}/companies/${companyId}/assets`, payload);
  }

  updateAsset(companyId: string, assetId: string, payload: Partial<Asset>): Observable<Asset> {
    return this.http.patch<Asset>(`${this.base}/companies/${companyId}/assets/${assetId}`, payload);
  }

  usages(companyId: string, assetId: string, includeEnded = true): Observable<DepartmentUsage[]> {
    return this.http.get<DepartmentUsage[]>(`${this.base}/companies/${companyId}/assets/${assetId}/usages`, {
      params: { include_ended: includeEnded }
    });
  }

  startUsage(companyId: string, assetId: string, payload: { department_id: string; purpose: string }): Observable<DepartmentUsage> {
    return this.http.post<DepartmentUsage>(`${this.base}/companies/${companyId}/assets/${assetId}/usages`, payload);
  }

  endUsage(companyId: string, assetId: string, usageId: string): Observable<DepartmentUsage> {
    return this.http.post<DepartmentUsage>(
      `${this.base}/companies/${companyId}/assets/${assetId}/usages/${usageId}/end`,
      {}
    );
  }

  history(companyId: string, assetId: string): Observable<AssetHistory[]> {
    return this.http.get<AssetHistory[]>(`${this.base}/companies/${companyId}/assets/${assetId}/history`);
  }

  assignmentRecipients(companyId: string): Observable<AssignmentRecipient[]> {
    return this.http.get<AssignmentRecipient[]>(`${this.base}/companies/${companyId}/assets/assignment-recipients`);
  }

  assignments(companyId: string, assetId: string): Observable<AssetAssignment[]> {
    return this.http.get<AssetAssignment[]>(`${this.base}/companies/${companyId}/assets/${assetId}/assignments`);
  }

  createAssignment(companyId: string, assetId: string, payload: {
    recipient_id: string;
    effective_date: string;
    responsible_department_id: string | null;
    location_id: string | null;
    notes: string;
    reference: string;
  }): Observable<AssetAssignment> {
    return this.http.post<AssetAssignment>(
      `${this.base}/companies/${companyId}/assets/${assetId}/assignments`,
      payload
    );
  }

  recordHandover(companyId: string, assetId: string, assignmentId: string, payload: {
    handover_date: string;
    condition: string;
    included_items: string;
    acknowledgement: string;
    notes: string;
  }): Observable<AssetAssignment> {
    return this.http.post<AssetAssignment>(
      `${this.base}/companies/${companyId}/assets/${assetId}/assignments/${assignmentId}/handover`,
      payload
    );
  }

  returnAssignment(companyId: string, assetId: string, assignmentId: string, payload: {
    return_date: string;
    condition: string;
    notes: string;
    issue_details: string;
    next_asset_status: 'in_stock' | 'maintenance';
  }): Observable<AssetAssignment> {
    return this.http.post<AssetAssignment>(
      `${this.base}/companies/${companyId}/assets/${assetId}/assignments/${assignmentId}/return`,
      payload
    );
  }

  transferAssignment(companyId: string, assetId: string, assignmentId: string, payload: {
    recipient_id: string;
    effective_date: string;
    reason: string;
    responsible_department_id: string | null;
    location_id: string | null;
    reference: string;
    condition: string;
    included_items: string;
    acknowledgement: string;
    notes: string;
  }): Observable<AssetAssignment> {
    return this.http.post<AssetAssignment>(
      `${this.base}/companies/${companyId}/assets/${assetId}/assignments/${assignmentId}/transfer`,
      payload
    );
  }

  suppliers(companyId: string): Observable<ProcurementSupplier[]> {
    return this.http.get<ProcurementSupplier[]>(`${this.base}/companies/${companyId}/suppliers`);
  }

  createSupplier(companyId: string, payload: Pick<ProcurementSupplier, 'code' | 'name' | 'email' | 'phone' | 'notes'>): Observable<ProcurementSupplier> {
    return this.http.post<ProcurementSupplier>(`${this.base}/companies/${companyId}/suppliers`, payload);
  }

  purchaseOrders(companyId: string): Observable<PurchaseOrder[]> {
    return this.http.get<PurchaseOrder[]>(`${this.base}/companies/${companyId}/purchase-orders`);
  }

  getPurchaseOrder(companyId: string, orderId: string): Observable<PurchaseOrder> {
    return this.http.get<PurchaseOrder>(`${this.base}/companies/${companyId}/purchase-orders/${orderId}`);
  }

  createPurchaseOrder(companyId: string, payload: {
    supplier_id: string;
    order_number: string;
    ordered_date: string;
    expected_date: string | null;
    notes: string;
    lines: Array<{
      category_id: string;
      description: string;
      quantity_ordered: number;
      unit_cost: number;
      discount?: number;
      tax_rate?: number;
      tax_amount?: number;
    }>;
  }): Observable<PurchaseOrder> {
    return this.http.post<PurchaseOrder>(`${this.base}/companies/${companyId}/purchase-orders`, payload);
  }

  updatePurchaseOrder(companyId: string, orderId: string, payload: {
    supplier_id?: string;
    order_number?: string;
    ordered_date?: string;
    expected_date?: string | null;
    notes?: string | null;
    lines: Array<{
      category_id: string;
      description: string;
      quantity_ordered: number;
      unit_cost: number;
      discount?: number;
      tax_rate?: number;
      tax_amount?: number;
    }>;
  }): Observable<PurchaseOrder> {
    return this.http.put<PurchaseOrder>(
      `${this.base}/companies/${companyId}/purchase-orders/${orderId}`,
      payload
    );
  }

  goodsReceipts(companyId: string): Observable<GoodsReceipt[]> {
    return this.http.get<GoodsReceipt[]>(`${this.base}/companies/${companyId}/goods-receipts`);
  }

  receiveGoods(companyId: string, purchaseOrderId: string, payload: {
    receipt_number: string;
    received_date: string;
    delivery_reference: string;
    notes: string;
    lines: Array<{
      purchase_order_line_id: string;
      quantity_received: number;
      quantity_rejected: number;
      serial_numbers: Array<string | null>;
      discrepancy_notes: string;
    }>;
  }): Observable<GoodsReceipt> {
    return this.http.post<GoodsReceipt>(
      `${this.base}/companies/${companyId}/purchase-orders/${purchaseOrderId}/goods-receipts`,
      payload
    );
  }

  serviceContracts(companyId: string, assetId: string): Observable<AssetServiceContract[]> {
    return this.http.get<AssetServiceContract[]>(
      `${this.base}/companies/${companyId}/assets/${assetId}/service-contracts`
    );
  }

  createServiceContract(companyId: string, assetId: string, payload: {
    contract_type: 'warranty' | 'amc';
    provider_name: string | null;
    reference_number: string | null;
    start_date: string;
    end_date: string;
    coverage_description: string | null;
    support_contact: string | null;
    notes: string | null;
  }): Observable<AssetServiceContract> {
    return this.http.post<AssetServiceContract>(
      `${this.base}/companies/${companyId}/assets/${assetId}/service-contracts`,
      payload
    );
  }

  cancelServiceContract(companyId: string, contractId: string): Observable<AssetServiceContract> {
    return this.http.patch<AssetServiceContract>(
      `${this.base}/companies/${companyId}/service-contracts/${contractId}/cancel`,
      {}
    );
  }

  maintenanceUsers(companyId: string): Observable<AssignmentRecipient[]> {
    return this.http.get<AssignmentRecipient[]>(`${this.base}/companies/${companyId}/maintenance-users`);
  }

  maintenanceRequests(companyId: string, filters: {
    asset_id?: string;
    status?: MaintenanceStatus | '';
  } = {}): Observable<MaintenanceRequest[]> {
    let params = new HttpParams();
    if (filters.asset_id) params = params.set('asset_id', filters.asset_id);
    if (filters.status) params = params.set('status', filters.status);
    return this.http.get<MaintenanceRequest[]>(
      `${this.base}/companies/${companyId}/maintenance-requests`,
      { params }
    );
  }

  createMaintenanceRequest(companyId: string, payload: {
    asset_id: string;
    title: string;
    issue_description: string;
    priority: MaintenancePriority;
    reported_date: string;
    assignee_id: string | null;
  }): Observable<MaintenanceRequest> {
    return this.http.post<MaintenanceRequest>(
      `${this.base}/companies/${companyId}/maintenance-requests`,
      payload
    );
  }

  updateMaintenanceRequest(companyId: string, requestId: string, payload: {
    status: MaintenanceStatus;
    assignee_id: string | null;
    diagnosis: string | null;
    work_performed: string | null;
    resolution_notes: string | null;
    completed_date: string | null;
    cost: number | null;
  }): Observable<MaintenanceRequest> {
    return this.http.patch<MaintenanceRequest>(
      `${this.base}/companies/${companyId}/maintenance-requests/${requestId}`,
      payload
    );
  }

  dashboard(companyId: string): Observable<DashboardData> {
    return this.http.get<DashboardData>(`${this.base}/companies/${companyId}/dashboard`);
  }

  reportAssetRegister(companyId: string, filters: {
    status?: string;
    category_id?: string;
    site_id?: string;
    department_id?: string;
    search?: string;
  } = {}): Observable<AssetRegisterReportItem[]> {
    let params = new HttpParams();
    if (filters.status) params = params.set('status', filters.status);
    if (filters.category_id) params = params.set('category_id', filters.category_id);
    if (filters.site_id) params = params.set('site_id', filters.site_id);
    if (filters.department_id) params = params.set('department_id', filters.department_id);
    if (filters.search) params = params.set('search', filters.search);
    return this.http.get<AssetRegisterReportItem[]>(`${this.base}/companies/${companyId}/reports/asset-register`, { params });
  }

  reportAssetAllocation(companyId: string, filters: {
    recipient_id?: string;
    department_id?: string;
    site_id?: string;
    search?: string;
  } = {}): Observable<AssetAllocationReportItem[]> {
    let params = new HttpParams();
    if (filters.recipient_id) params = params.set('recipient_id', filters.recipient_id);
    if (filters.department_id) params = params.set('department_id', filters.department_id);
    if (filters.site_id) params = params.set('site_id', filters.site_id);
    if (filters.search) params = params.set('search', filters.search);
    return this.http.get<AssetAllocationReportItem[]>(`${this.base}/companies/${companyId}/reports/asset-allocation`, { params });
  }

  reportWarrantyExpiry(companyId: string, filters: {
    contract_type?: string;
    coverage_status?: string;
    search?: string;
  } = {}): Observable<WarrantyExpiryReportItem[]> {
    let params = new HttpParams();
    if (filters.contract_type) params = params.set('contract_type', filters.contract_type);
    if (filters.coverage_status) params = params.set('coverage_status', filters.coverage_status);
    if (filters.search) params = params.set('search', filters.search);
    return this.http.get<WarrantyExpiryReportItem[]>(`${this.base}/companies/${companyId}/reports/warranty-expiry`, { params });
  }

  reportMaintenance(companyId: string, filters: {
    status?: string;
    priority?: string;
    asset_id?: string;
    search?: string;
  } = {}): Observable<MaintenanceReportItem[]> {
    let params = new HttpParams();
    if (filters.status) params = params.set('status', filters.status);
    if (filters.priority) params = params.set('priority', filters.priority);
    if (filters.asset_id) params = params.set('asset_id', filters.asset_id);
    if (filters.search) params = params.set('search', filters.search);
    return this.http.get<MaintenanceReportItem[]>(`${this.base}/companies/${companyId}/reports/maintenance`, { params });
  }

  reportProcurement(companyId: string, filters: {
    status?: string;
    supplier_id?: string;
    search?: string;
  } = {}): Observable<ProcurementReportItem[]> {
    let params = new HttpParams();
    if (filters.status) params = params.set('status', filters.status);
    if (filters.supplier_id) params = params.set('supplier_id', filters.supplier_id);
    if (filters.search) params = params.set('search', filters.search);
    return this.http.get<ProcurementReportItem[]>(`${this.base}/companies/${companyId}/reports/procurement`, { params });
  }
}

