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

export interface ImportRowError {
  row_number: number;
  field: string;
  value?: string | null;
  message: string;
}

export interface ImportRowWarning {
  row_number: number;
  field: string;
  message: string;
}

export interface AssetImportPreviewRow {
  row_number: number;
  category_code: string;
  category_name: string;
  serial_number: string;
  manufacturer: string;
  model: string;
  status: string;
  site_code: string;
  location_code: string;
  department_code: string;
  cost_center_code: string;
  acquisition_date: string;
  acquisition_cost: string;
  has_errors: boolean;
}

export interface AssetImportPreviewResponse {
  valid: boolean;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  preview_token?: string | null;
  errors: ImportRowError[];
  warnings: ImportRowWarning[];
  preview_rows: AssetImportPreviewRow[];
}

export interface AssetImportConfirmResponse {
  imported_count: number;
  asset_numbers: string[];
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

  lookupAsset(companyId: string, code: string): Observable<Asset> {
    const params = new HttpParams().set('code', code.trim());
    return this.http.get<Asset>(`${this.base}/companies/${companyId}/assets/lookup`, { params });
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

  downloadAssetImportTemplate(companyId: string, format: 'csv' | 'xlsx' = 'csv'): Observable<Blob> {
    const params = new HttpParams().set('format', format);
    return this.http.get(`${this.base}/companies/${companyId}/assets/import/template`, {
      params,
      responseType: 'blob'
    });
  }

  previewAssetImport(companyId: string, file: File): Observable<AssetImportPreviewResponse> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    return this.http.post<AssetImportPreviewResponse>(`${this.base}/companies/${companyId}/assets/import/preview`, formData);
  }

  confirmAssetImport(companyId: string, previewToken: string): Observable<AssetImportConfirmResponse> {
    return this.http.post<AssetImportConfirmResponse>(`${this.base}/companies/${companyId}/assets/import/confirm`, {
      preview_token: previewToken
    });
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

  // --- Physical Asset Verification ---

  listVerificationCampaigns(companyId: string, filters: { status?: string; search?: string } = {}): Observable<VerificationCampaign[]> {
    let params = new HttpParams();
    if (filters.status && filters.status !== 'all') params = params.set('status', filters.status);
    if (filters.search) params = params.set('search', filters.search);
    return this.http.get<VerificationCampaign[]>(`${this.base}/companies/${companyId}/verification-campaigns`, { params });
  }

  getVerificationCampaign(companyId: string, campaignId: string): Observable<VerificationCampaign> {
    return this.http.get<VerificationCampaign>(`${this.base}/companies/${companyId}/verification-campaigns/${campaignId}`);
  }

  createVerificationCampaign(companyId: string, payload: VerificationCampaignCreate): Observable<VerificationCampaign> {
    return this.http.post<VerificationCampaign>(`${this.base}/companies/${companyId}/verification-campaigns`, payload);
  }

  updateVerificationCampaign(companyId: string, campaignId: string, payload: VerificationCampaignUpdate): Observable<VerificationCampaign> {
    return this.http.patch<VerificationCampaign>(`${this.base}/companies/${companyId}/verification-campaigns/${campaignId}`, payload);
  }

  transitionVerificationCampaignStatus(companyId: string, campaignId: string, status: string): Observable<VerificationCampaign> {
    return this.http.post<VerificationCampaign>(`${this.base}/companies/${companyId}/verification-campaigns/${campaignId}/status`, { status });
  }

  getVerificationExpectedAssets(companyId: string, campaignId: string, filters: {
    search?: string;
    verified?: boolean;
    category_id?: string;
    location_id?: string;
  } = {}): Observable<VerificationExpectedAsset[]> {
    let params = new HttpParams();
    if (filters.search) params = params.set('search', filters.search);
    if (filters.verified !== undefined) params = params.set('verified', filters.verified ? 'true' : 'false');
    if (filters.category_id) params = params.set('category_id', filters.category_id);
    if (filters.location_id) params = params.set('location_id', filters.location_id);
    return this.http.get<VerificationExpectedAsset[]>(`${this.base}/companies/${companyId}/verification-campaigns/${campaignId}/expected-assets`, { params });
  }

  recordVerificationObservation(companyId: string, campaignId: string, expectedAssetId: string, payload: VerificationObservationCreate): Observable<VerificationObservation> {
    return this.http.post<VerificationObservation>(`${this.base}/companies/${companyId}/verification-campaigns/${campaignId}/expected-assets/${expectedAssetId}/observations`, payload);
  }

  getVerificationDiscrepancies(companyId: string, campaignId: string, filters: {
    discrepancy_type?: string;
    status?: string;
  } = {}): Observable<VerificationDiscrepancy[]> {
    let params = new HttpParams();
    if (filters.discrepancy_type && filters.discrepancy_type !== 'all') params = params.set('discrepancy_type', filters.discrepancy_type);
    if (filters.status && filters.status !== 'all') params = params.set('status', filters.status);
    return this.http.get<VerificationDiscrepancy[]>(`${this.base}/companies/${companyId}/verification-campaigns/${campaignId}/discrepancies`, { params });
  }

  resolveVerificationDiscrepancy(companyId: string, campaignId: string, discrepancyId: string, payload: VerificationDiscrepancyResolveRequest): Observable<VerificationDiscrepancy> {
    return this.http.post<VerificationDiscrepancy>(`${this.base}/companies/${companyId}/verification-campaigns/${campaignId}/discrepancies/${discrepancyId}/resolve`, payload);
  }

  recordUnregisteredAsset(companyId: string, campaignId: string, payload: VerificationUnregisteredAssetCreate): Observable<VerificationUnregisteredAsset> {
    return this.http.post<VerificationUnregisteredAsset>(`${this.base}/companies/${companyId}/verification-campaigns/${campaignId}/unregistered-assets`, payload);
  }

  getUnregisteredAssets(companyId: string, campaignId: string, status?: string): Observable<VerificationUnregisteredAsset[]> {
    let params = new HttpParams();
    if (status && status !== 'all') params = params.set('status', status);
    return this.http.get<VerificationUnregisteredAsset[]>(`${this.base}/companies/${companyId}/verification-campaigns/${campaignId}/unregistered-assets`, { params });
  }

  registerUnregisteredAsset(companyId: string, campaignId: string, unregisteredAssetId: string, payload: VerificationUnregisteredAssetRegister): Observable<VerificationUnregisteredAsset> {
    return this.http.post<VerificationUnregisteredAsset>(`${this.base}/companies/${companyId}/verification-campaigns/${campaignId}/unregistered-assets/${unregisteredAssetId}/register`, payload);
  }

  getVerificationDashboard(companyId: string, campaignId: string): Observable<VerificationDashboardSummary> {
    return this.http.get<VerificationDashboardSummary>(`${this.base}/companies/${companyId}/verification-campaigns/${campaignId}/dashboard`);
  }

  reportVerificationCampaigns(companyId: string, filters: { status?: string; search?: string } = {}): Observable<VerificationCampaignReportItem[]> {
    let params = new HttpParams();
    if (filters.status && filters.status !== 'all') params = params.set('status', filters.status);
    if (filters.search) params = params.set('search', filters.search);
    return this.http.get<VerificationCampaignReportItem[]>(`${this.base}/companies/${companyId}/reports/verification-campaigns`, { params });
  }

  reportVerificationDiscrepancies(companyId: string, filters: { campaign_id?: string; discrepancy_type?: string; status?: string } = {}): Observable<VerificationDiscrepancyReportItem[]> {
    let params = new HttpParams();
    if (filters.campaign_id) params = params.set('campaign_id', filters.campaign_id);
    if (filters.discrepancy_type && filters.discrepancy_type !== 'all') params = params.set('discrepancy_type', filters.discrepancy_type);
    if (filters.status && filters.status !== 'all') params = params.set('status', filters.status);
    return this.http.get<VerificationDiscrepancyReportItem[]>(`${this.base}/companies/${companyId}/reports/verification-discrepancies`, { params });
  }

  // --- Asset Financial Lifecycle ---

  getAssetFinancial(companyId: string, assetId: string): Observable<AssetFinancial> {
    return this.http.get<AssetFinancial>(`${this.base}/companies/${companyId}/assets/${assetId}/financial`);
  }

  configureAssetFinancial(companyId: string, assetId: string, payload: AssetFinancialCreate): Observable<AssetFinancial> {
    return this.http.put<AssetFinancial>(`${this.base}/companies/${companyId}/assets/${assetId}/financial`, payload);
  }

  editAssetFinancial(companyId: string, assetId: string, payload: Partial<AssetFinancialCreate>): Observable<AssetFinancial> {
    return this.http.patch<AssetFinancial>(`${this.base}/companies/${companyId}/assets/${assetId}/financial`, payload);
  }

  adjustAssetFinancial(companyId: string, assetId: string, payload: AssetFinancialAdjust): Observable<AssetFinancial> {
    return this.http.post<AssetFinancial>(`${this.base}/companies/${companyId}/assets/${assetId}/financial/adjust`, payload);
  }

  getDepreciationSchedule(companyId: string, assetId: string): Observable<DepreciationScheduleItem[]> {
    return this.http.get<DepreciationScheduleItem[]>(`${this.base}/companies/${companyId}/assets/${assetId}/depreciation-schedule`);
  }

  postDepreciation(companyId: string, assetId: string, payload: { period: string; notes?: string | null }): Observable<AssetDepreciationEntry> {
    return this.http.post<AssetDepreciationEntry>(`${this.base}/companies/${companyId}/assets/${assetId}/depreciation-entries`, payload);
  }

  listDepreciationEntries(companyId: string, assetId: string): Observable<AssetDepreciationEntry[]> {
    return this.http.get<AssetDepreciationEntry[]>(`${this.base}/companies/${companyId}/assets/${assetId}/depreciation-entries`);
  }

  postBatchDepreciation(companyId: string, payload: { period: string; notes?: string | null }): Observable<BatchDepreciationResult> {
    return this.http.post<BatchDepreciationResult>(`${this.base}/companies/${companyId}/depreciation-entries/batch`, payload);
  }

  disposeAsset(companyId: string, assetId: string, payload: AssetDisposalCreate): Observable<AssetDisposal> {
    return this.http.post<AssetDisposal>(`${this.base}/companies/${companyId}/assets/${assetId}/dispose`, payload);
  }

  getAssetDisposal(companyId: string, assetId: string): Observable<AssetDisposal> {
    return this.http.get<AssetDisposal>(`${this.base}/companies/${companyId}/assets/${assetId}/disposal`);
  }

  reportAssetDepreciation(companyId: string, filters: { category_id?: string; site_id?: string; location_id?: string; financial_status?: string } = {}): Observable<AssetDepreciationReportItem[]> {
    let params = new HttpParams();
    if (filters.category_id) params = params.set('category_id', filters.category_id);
    if (filters.site_id) params = params.set('site_id', filters.site_id);
    if (filters.location_id) params = params.set('location_id', filters.location_id);
    if (filters.financial_status) params = params.set('financial_status', filters.financial_status);
    return this.http.get<AssetDepreciationReportItem[]>(`${this.base}/companies/${companyId}/reports/asset-depreciation`, { params });
  }

  reportAssetDisposals(companyId: string, filters: { start_date?: string; end_date?: string; disposal_reason?: string; disposal_method?: string } = {}): Observable<AssetDisposalReportItem[]> {
    let params = new HttpParams();
    if (filters.start_date) params = params.set('start_date', filters.start_date);
    if (filters.end_date) params = params.set('end_date', filters.end_date);
    if (filters.disposal_reason) params = params.set('disposal_reason', filters.disposal_reason);
    if (filters.disposal_method) params = params.set('disposal_method', filters.disposal_method);
    return this.http.get<AssetDisposalReportItem[]>(`${this.base}/companies/${companyId}/reports/asset-disposals`, { params });
  }

  getFinancialDashboard(companyId: string): Observable<FinancialDashboardMetric> {
    return this.http.get<FinancialDashboardMetric>(`${this.base}/companies/${companyId}/dashboard/financial`);
  }

  listAlerts(
    companyId: string,
    filters: {
      status?: string;
      severity?: string;
      alert_type?: string;
      search?: string;
      auto_sync?: boolean;
      limit?: number;
      offset?: number;
    } = {}
  ): Observable<AssetAlert[]> {
    let params = new HttpParams();
    if (filters.status) params = params.set('status', filters.status);
    if (filters.severity) params = params.set('severity', filters.severity);
    if (filters.alert_type) params = params.set('alert_type', filters.alert_type);
    if (filters.search) params = params.set('search', filters.search);
    if (filters.auto_sync) params = params.set('auto_sync', 'true');
    if (filters.limit) params = params.set('limit', filters.limit.toString());
    if (filters.offset) params = params.set('offset', filters.offset.toString());
    return this.http.get<AssetAlert[]>(`${this.base}/companies/${companyId}/alerts`, { params });
  }

  getAlertSummary(companyId: string): Observable<AssetAlertSummary> {
    return this.http.get<AssetAlertSummary>(`${this.base}/companies/${companyId}/alerts/summary`);
  }

  syncAlerts(companyId: string): Observable<AlertSyncResponse> {
    return this.http.post<AlertSyncResponse>(`${this.base}/companies/${companyId}/alerts/sync`, {});
  }

  acknowledgeAlert(companyId: string, alertId: string, notes?: string): Observable<AssetAlert> {
    return this.http.post<AssetAlert>(`${this.base}/companies/${companyId}/alerts/${alertId}/acknowledge`, { notes });
  }

  assignAlert(companyId: string, alertId: string, responsibleUserId: string): Observable<AssetAlert> {
    return this.http.post<AssetAlert>(`${this.base}/companies/${companyId}/alerts/${alertId}/assign`, {
      responsible_user_id: responsibleUserId
    });
  }

  resolveAlert(companyId: string, alertId: string, resolutionNotes?: string, reason: string = 'manual_resolution'): Observable<AssetAlert> {
    return this.http.post<AssetAlert>(`${this.base}/companies/${companyId}/alerts/${alertId}/resolve`, {
      resolution_reason: reason,
      resolution_notes: resolutionNotes
    });
  }

  dismissAlert(companyId: string, alertId: string, resolutionNotes?: string): Observable<AssetAlert> {
    return this.http.post<AssetAlert>(`${this.base}/companies/${companyId}/alerts/${alertId}/dismiss`, {
      resolution_notes: resolutionNotes
    });
  }

  getLastAlertJob(companyId: string): Observable<ScheduledJobExecution | null> {
    return this.http.get<ScheduledJobExecution | null>(`${this.base}/companies/${companyId}/alerts/last-job`);
  }

  getNotifications(status?: string, companyId?: string): Observable<InAppNotification[]> {
    let params = new HttpParams();
    if (status) params = params.set('status', status);
    if (companyId) params = params.set('company_id', companyId);
    return this.http.get<InAppNotification[]>(`${this.base}/notifications`, { params });
  }

  getUnreadNotificationCount(companyId?: string): Observable<NotificationUnreadCount> {
    let params = new HttpParams();
    if (companyId) params = params.set('company_id', companyId);
    return this.http.get<NotificationUnreadCount>(`${this.base}/notifications/unread-count`, { params });
  }

  markNotificationRead(notificationId: string): Observable<InAppNotification> {
    return this.http.post<InAppNotification>(`${this.base}/notifications/${notificationId}/read`, {});
  }

  markAllNotificationsRead(companyId?: string): Observable<NotificationUnreadCount> {
    let params = new HttpParams();
    if (companyId) params = params.set('company_id', companyId);
    return this.http.post<NotificationUnreadCount>(`${this.base}/notifications/mark-all-read`, {}, { params });
  }
}


export interface VerificationCampaign {
  id: string;
  company_id: string;
  campaign_reference: string;
  name: string;
  description: string | null;
  status: string;
  start_date: string;
  end_date: string;
  scope_category_ids: string[] | null;
  scope_location_ids: string[] | null;
  created_by_id: string;
  created_by_name: string | null;
  started_at: string | null;
  completed_at: string | null;
  closed_by_id: string | null;
  created_at: string;
  updated_at: string;
  total_expected: number;
  total_verified: number;
  total_unverified: number;
  total_missing: number;
  total_discrepancies: number;
  total_unregistered: number;
  completion_percentage: number;
}

export interface VerificationCampaignCreate {
  campaign_reference: string;
  name: string;
  description?: string | null;
  start_date: string;
  end_date: string;
  scope_category_ids?: string[] | null;
  scope_location_ids?: string[] | null;
}

export interface VerificationCampaignUpdate {
  name?: string | null;
  description?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  scope_category_ids?: string[] | null;
  scope_location_ids?: string[] | null;
}

export interface VerificationExpectedAsset {
  id: string;
  company_id: string;
  campaign_id: string;
  asset_id: string;
  asset_number: string;
  category_id: string;
  category_name?: string | null;
  serial_number?: string | null;
  model?: string | null;
  manufacturer?: string | null;
  expected_site_id?: string | null;
  site_name?: string | null;
  expected_location_id?: string | null;
  location_name?: string | null;
  expected_department_id?: string | null;
  department_name?: string | null;
  expected_custodian_id?: string | null;
  expected_custodian_name?: string | null;
  expected_condition?: string | null;
  expected_status: string;
  is_verified: boolean;
  observation_id?: string | null;
  observation_found?: boolean | null;
  has_discrepancy: boolean;
  discrepancy_types: string[];
  created_at: string;
}

export interface VerificationObservationCreate {
  is_found: boolean;
  actual_location_id?: string | null;
  actual_custodian_id?: string | null;
  observed_condition: string;
  verification_date?: string | null;
  remarks?: string | null;
  reference_notes?: string | null;
}

export interface VerificationObservation {
  id: string;
  company_id: string;
  campaign_id: string;
  expected_asset_id?: string | null;
  asset_id?: string | null;
  asset_number?: string | null;
  is_found: boolean;
  actual_site_id?: string | null;
  actual_site_name?: string | null;
  actual_location_id?: string | null;
  actual_location_name?: string | null;
  actual_department_id?: string | null;
  actual_custodian_id?: string | null;
  actual_custodian_name?: string | null;
  observed_condition: string;
  verification_date: string;
  verified_by_id: string;
  verified_by_name?: string | null;
  remarks?: string | null;
  reference_notes?: string | null;
  created_at: string;
}

export interface VerificationDiscrepancy {
  id: string;
  company_id: string;
  campaign_id: string;
  campaign_reference?: string | null;
  observation_id?: string | null;
  expected_asset_id?: string | null;
  asset_id?: string | null;
  asset_number?: string | null;
  discrepancy_type: string;
  status: string;
  expected_data?: any;
  observed_data?: any;
  notes?: string | null;
  resolution_action?: string | null;
  resolution_notes?: string | null;
  resolved_by_id?: string | null;
  resolved_by_name?: string | null;
  resolved_at?: string | null;
  created_at: string;
}

export interface VerificationDiscrepancyResolveRequest {
  resolution_action: string;
  resolution_notes: string;
}

export interface VerificationUnregisteredAssetCreate {
  description: string;
  category_id: string;
  serial_number?: string | null;
  site_id?: string | null;
  location_id?: string | null;
  custodian_id?: string | null;
  observed_condition?: string | null;
  remarks?: string | null;
}

export interface VerificationUnregisteredAssetRegister {
  asset_number?: string | null;
  cost_center_id?: string | null;
  responsible_department_id?: string | null;
  acquisition_cost?: number | null;
  acquisition_date?: string | null;
  resolution_notes: string;
}

export interface VerificationUnregisteredAsset {
  id: string;
  company_id: string;
  campaign_id: string;
  observation_id?: string | null;
  discrepancy_id?: string | null;
  serial_number?: string | null;
  description: string;
  category_id: string;
  category_name?: string | null;
  site_id?: string | null;
  site_name?: string | null;
  location_id?: string | null;
  location_name?: string | null;
  custodian_id?: string | null;
  custodian_name?: string | null;
  observed_condition?: string | null;
  remarks?: string | null;
  status: string;
  registered_asset_id?: string | null;
  registered_asset_number?: string | null;
  created_at: string;
}

export interface VerificationDashboardSummary {
  campaign_id: string;
  campaign_reference: string;
  campaign_name: string;
  status: string;
  start_date: string;
  end_date: string;
  total_expected: number;
  total_verified: number;
  total_unverified: number;
  total_missing: number;
  completion_percentage: number;
  discrepancies_by_type: Record<string, number>;
  unregistered_count: number;
  pending_resolutions: number;
  resolved_resolutions: number;
}

export interface VerificationCampaignReportItem {
  campaign_id: string;
  campaign_reference: string;
  campaign_name: string;
  status: string;
  start_date: string;
  end_date: string;
  total_expected: number;
  total_verified: number;
  total_missing: number;
  discrepancy_count: number;
  unregistered_count: number;
  completion_percentage: number;
  created_at: string;
  completed_at?: string | null;
}

export interface VerificationDiscrepancyReportItem {
  discrepancy_id: string;
  campaign_reference: string;
  campaign_name: string;
  asset_number?: string | null;
  discrepancy_type: string;
  status: string;
  expected_summary?: string | null;
  observed_summary?: string | null;
  notes?: string | null;
  resolution_action?: string | null;
  resolution_notes?: string | null;
  resolved_by_name?: string | null;
  resolved_at?: string | null;
  created_at: string;
}

export interface AssetFinancial {
  id: string;
  company_id: string;
  asset_id: string;
  capitalised_cost: number | string;
  currency: string;
  depreciation_method: string;
  useful_life_months: number;
  residual_value: number | string;
  depreciation_start_date: string;
  accumulated_depreciation: number | string;
  current_book_value: number | string;
  financial_status: string;
  created_at: string;
  updated_at: string;
}

export interface AssetFinancialCreate {
  capitalised_cost: number;
  currency?: string;
  depreciation_method?: string;
  useful_life_months: number;
  residual_value?: number;
  depreciation_start_date: string;
}

export interface AssetFinancialAdjust {
  useful_life_months?: number | null;
  residual_value?: number | null;
  notes?: string | null;
}

export interface DepreciationScheduleItem {
  period: string;
  period_start_date: string;
  period_end_date: string;
  depreciation_amount: number | string;
  accumulated_depreciation: number | string;
  book_value: number | string;
  status: string;
}

export interface AssetDepreciationEntry {
  id: string;
  company_id: string;
  asset_id: string;
  period: string;
  period_start_date: string;
  period_end_date: string;
  depreciation_amount: number | string;
  accumulated_depreciation_after: number | string;
  book_value_after: number | string;
  method: string;
  posted_by_id: string;
  posted_at: string;
  notes?: string | null;
}

export interface BatchDepreciationResult {
  period: string;
  processed_count: number;
  posted_count: number;
  skipped_count: number;
  total_depreciation_posted: number | string;
  posted_asset_ids: string[];
  skipped: Array<{ asset_id: string; asset_number?: string; reason: string }>;
}

export interface AssetDisposal {
  id: string;
  company_id: string;
  asset_id: string;
  disposal_date: string;
  disposal_reason: string;
  disposal_method: string;
  sale_proceeds: number | string;
  net_book_value_at_disposal: number | string;
  gain_loss: number | string;
  notes?: string | null;
  disposed_by_id: string;
  created_at: string;
}

export interface AssetDisposalCreate {
  disposal_date: string;
  disposal_reason: string;
  disposal_method: string;
  sale_proceeds?: number;
  notes?: string | null;
}

export interface AssetDepreciationReportItem {
  asset_id: string;
  asset_number: string;
  asset_name: string;
  category_name: string;
  site_name?: string | null;
  location_name?: string | null;
  acquisition_date?: string | null;
  capitalised_cost: number | string;
  currency: string;
  depreciation_method: string;
  useful_life_months: number;
  residual_value: number | string;
  depreciation_start_date: string;
  accumulated_depreciation: number | string;
  current_book_value: number | string;
  financial_status: string;
}

export interface AssetDisposalReportItem {
  asset_id: string;
  asset_number: string;
  asset_name: string;
  category_name: string;
  acquisition_date?: string | null;
  acquisition_cost?: number | string | null;
  disposal_date: string;
  disposal_reason: string;
  disposal_method: string;
  sale_proceeds: number | string;
  net_book_value_at_disposal: number | string;
  gain_loss: number | string;
  disposed_by_email?: string | null;
  notes?: string | null;
}

export interface FinancialDashboardMetric {
  total_capitalised_cost: number | string;
  total_accumulated_depreciation: number | string;
  total_net_book_value: number | string;
  approaching_eol_count: number;
  fully_depreciated_active_count: number;
  disposed_count: number;
  total_disposal_proceeds: number | string;
  total_disposal_gain_loss: number | string;
}

export interface AssetAlert {
  id: string;
  company_id: string;
  alert_type: string;
  severity: 'critical' | 'warning' | 'info';
  status: 'open' | 'acknowledged' | 'resolved' | 'dismissed';
  title: string;
  description: string | null;
  entity_type: string;
  entity_id: string;
  entity_reference: string | null;
  asset_id: string | null;
  due_date: string | null;
  days_overdue: number | null;
  responsible_user_id: string | null;
  responsible_user_email?: string | null;
  target_route: string | null;
  acknowledged_at: string | null;
  acknowledged_by_id: string | null;
  acknowledged_by_email?: string | null;
  resolved_at: string | null;
  resolved_by_id: string | null;
  resolved_by_email?: string | null;
  resolution_reason: string | null;
  resolution_notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface AssetAlertSummary {
  total_open: number;
  total_acknowledged: number;
  total_resolved: number;
  total_dismissed: number;
  critical_count: number;
  warning_count: number;
  info_count: number;
  by_type: Record<string, number>;
}

export interface AlertSyncResponse {
  synced: boolean;
  created_count: number;
  updated_count: number;
  auto_resolved_count: number;
  active_count: number;
}

export interface ScheduledJobExecution {
  id: string;
  job_name: string;
  status: 'running' | 'completed' | 'failed';
  started_at: string;
  last_heartbeat_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  total_companies_processed: number;
  alerts_created: number;
  alerts_updated: number;
  alerts_auto_resolved: number;
  error_message: string | null;
  node_id: string | null;
  created_at: string;
}

export interface InAppNotification {
  id: string;
  company_id: string | null;
  recipient_user_id: string;
  notification_type: string;
  title: string;
  message: string;
  severity: 'critical' | 'warning' | 'info';
  entity_type: string | null;
  entity_id: string | null;
  target_route: string | null;
  status: 'unread' | 'read' | 'archived';
  read_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface NotificationUnreadCount {
  unread_count: number;
}


