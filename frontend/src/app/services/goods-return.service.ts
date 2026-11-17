import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

export interface AssetEligibilityCheckItem {
  asset_id: string;
  asset_number: string;
  serial_number: string | null;
  status: string;
  is_eligible: boolean;
  blocking_reasons: string[];
}

export interface GoodsReceiptLineEligibilitySummary {
  goods_receipt_line_id: string;
  purchase_order_line_id: string;
  quantity_received: number;
  quantity_rejected: number;
  quantity_reversed: number;
  unreversed_accepted_quantity: number;
  eligible_asset_count: number;
}

export interface GoodsReceiptReversalEligibilityResponse {
  goods_receipt_id: string;
  receipt_number: string;
  status: string;
  is_reversible: boolean;
  total_accepted_quantity: number;
  total_quantity_reversed: number;
  unreversed_accepted_quantity: number;
  lines: GoodsReceiptLineEligibilitySummary[];
  assets: AssetEligibilityCheckItem[];
}

export interface ReversalLineItem {
  goods_receipt_line_id: string;
  asset_ids: string[];
  notes?: string | null;
}

export interface GoodsReceiptReversalCreate {
  reason: string;
  lines: ReversalLineItem[];
}

export interface ReversalAssetRead {
  id: string;
  company_id: string;
  reversal_id: string;
  reversal_line_id: string;
  goods_receipt_line_id: string;
  asset_id: string;
  asset_number: string | null;
  serial_number: string | null;
  created_at: string;
}

export interface ReversalLineRead {
  id: string;
  company_id: string;
  reversal_id: string;
  goods_receipt_line_id: string;
  purchase_order_line_id: string;
  quantity_reversed: number;
  notes: string | null;
  created_at: string;
  assets: ReversalAssetRead[];
}

export interface GoodsReceiptReversalRead {
  id: string;
  company_id: string;
  goods_receipt_id: string;
  purchase_order_id: string;
  reversal_reference: string | null;
  reversed_at: string;
  reversed_by_id: string;
  reason: string;
  created_at: string;
  lines: ReversalLineRead[];
}

export interface ReturnEligibleAssetItem {
  goods_receipt_reversal_asset_id: string;
  reversal_id: string;
  reversal_line_id: string;
  goods_receipt_line_id: string;
  asset_id: string;
  asset_number: string;
  serial_number: string | null;
  is_actively_reserved: boolean;
  active_reservation_return_id: string | null;
  active_reservation_return_number: string | null;
  is_eligible: boolean;
  ineligibility_reason: string | null;
}

export interface GoodsReturnLine {
  id: string;
  company_id: string;
  goods_return_id: string;
  goods_receipt_reversal_id: string;
  goods_receipt_reversal_asset_id: string;
  goods_receipt_reversal_line_id: string;
  goods_receipt_line_id: string;
  asset_id: string;
  asset_number: string | null;
  serial_number: string | null;
  return_condition: string;
  notes: string | null;
  created_at: string;
  /** Optional underlying asset lifecycle status (e.g. 'return_pending', 'reversed'). */
  asset_status?: string | null;
}

export interface GoodsReturn {
  id: string;
  company_id: string;
  return_number: string;
  supplier_id: string;
  purchase_order_id: string;
  original_goods_receipt_id: string;
  goods_receipt_reversal_id: string;
  return_date: string;
  status: 'draft' | 'approved' | 'dispatched' | 'partially_returned_to_warehouse' | 'returned_to_warehouse' | 'completed' | 'cancelled';
  return_reason: string;
  vendor_reference: string | null;
  dispatch_reference: string | null;
  transport_details: string | null;
  notes: string | null;
  policy_strict_approval_applied: boolean | null;
  created_by_id: string;
  created_at: string;
  approved_by_id: string | null;
  approved_at: string | null;
  dispatched_by_id: string | null;
  dispatched_at: string | null;
  completed_by_id: string | null;
  completed_at: string | null;
  cancelled_by_id: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  lines: GoodsReturnLine[];
}

export interface GoodsReturnWarehouseReceiptLine {
  id: string;
  company_id: string;
  warehouse_receipt_id: string;
  goods_return_id: string;
  goods_return_line_id: string;
  asset_id: string;
  condition_on_return: string;
  notes: string | null;
  is_corrected: boolean;
  correction_reason: string | null;
  corrected_at: string | null;
  corrected_by_id: string | null;
  created_at: string;
}

export interface GoodsReturnWarehouseReceipt {
  id: string;
  company_id: string;
  goods_return_id: string;
  receipt_number: string;
  receipt_date: string;
  received_at: string;
  received_by_id: string;
  warehouse_location_id: string | null;
  dispatch_reference: string | null;
  reason: string;
  notes: string | null;
  created_at: string;
  lines: GoodsReturnWarehouseReceiptLine[];
}

export interface GoodsReturnCreatePayload {
  goods_receipt_reversal_id: string;
  return_date: string;
  return_reason: string;
  vendor_reference?: string | null;
  dispatch_reference?: string | null;
  transport_details?: string | null;
  notes?: string | null;
  lines: {
    goods_receipt_reversal_asset_id: string;
    return_condition?: string;
    notes?: string | null;
  }[];
}

export interface GoodsReturnDispatchPayload {
  dispatch_reference: string;
  transport_details?: string | null;
  notes?: string | null;
}

export interface GoodsReturnCancelPayload {
  cancellation_reason: string;
}

export interface WarehouseReceiptCreatePayload {
  receipt_date: string;
  warehouse_location_id?: string | null;
  dispatch_reference?: string | null;
  reason: string;
  notes?: string | null;
  lines: {
    goods_return_line_id: string;
    condition_on_return?: string;
    notes?: string | null;
  }[];
}

export interface WarehouseReceiptCorrectionPayload {
  correction_reason: string;
  notes?: string | null;
}

export interface CompanySettingsUpdatePayload {
  procurement_different_person_return_approval?: boolean;
  reason: string;
}

@Injectable({
  providedIn: 'root',
})
export class GoodsReturnService {
  private base = environment.apiBaseUrl;

  constructor(private http: HttpClient) {}

  getGoodsReceiptReversalCheck(
    companyId: string,
    goodsReceiptId: string
  ): Observable<GoodsReceiptReversalEligibilityResponse> {
    return this.http.get<GoodsReceiptReversalEligibilityResponse>(
      `${this.base}/companies/${companyId}/goods-receipts/${goodsReceiptId}/reversal-check`
    );
  }

  reverseGoodsReceipt(
    companyId: string,
    goodsReceiptId: string,
    payload: GoodsReceiptReversalCreate
  ): Observable<GoodsReceiptReversalRead> {
    return this.http.post<GoodsReceiptReversalRead>(
      `${this.base}/companies/${companyId}/goods-receipts/${goodsReceiptId}/reverse`,
      payload
    );
  }

  listGoodsReceiptReversals(
    companyId: string,
    goodsReceiptId: string
  ): Observable<GoodsReceiptReversalRead[]> {
    return this.http.get<GoodsReceiptReversalRead[]>(
      `${this.base}/companies/${companyId}/goods-receipts/${goodsReceiptId}/reversals`
    );
  }

  getReturnEligibleAssets(companyId: string, reversalId: string): Observable<ReturnEligibleAssetItem[]> {
    return this.http.get<ReturnEligibleAssetItem[]>(
      `${this.base}/companies/${companyId}/goods-receipt-reversals/${reversalId}/return-eligible-assets`
    );
  }

  getReversalReturns(companyId: string, reversalId: string): Observable<GoodsReturn[]> {
    return this.http.get<GoodsReturn[]>(
      `${this.base}/companies/${companyId}/goods-receipt-reversals/${reversalId}/returns`
    );
  }

  createGoodsReturn(companyId: string, payload: GoodsReturnCreatePayload): Observable<GoodsReturn> {
    return this.http.post<GoodsReturn>(`${this.base}/companies/${companyId}/goods-returns`, payload);
  }

  listGoodsReturns(
    companyId: string,
    filters?: { status?: string; reversalId?: string; supplierId?: string }
  ): Observable<GoodsReturn[]> {
    let params = new HttpParams();
    if (filters?.status) params = params.set('status', filters.status);
    if (filters?.reversalId) params = params.set('reversal_id', filters.reversalId);
    if (filters?.supplierId) params = params.set('supplier_id', filters.supplierId);
    return this.http.get<GoodsReturn[]>(`${this.base}/companies/${companyId}/goods-returns`, { params });
  }

  getGoodsReturn(companyId: string, returnId: string): Observable<GoodsReturn> {
    return this.http.get<GoodsReturn>(`${this.base}/companies/${companyId}/goods-returns/${returnId}`);
  }

  updateGoodsReturn(companyId: string, returnId: string, payload: Partial<GoodsReturnCreatePayload>): Observable<GoodsReturn> {
    return this.http.patch<GoodsReturn>(`${this.base}/companies/${companyId}/goods-returns/${returnId}`, payload);
  }

  deselectReturnLine(companyId: string, returnId: string, lineId: string): Observable<GoodsReturn> {
    return this.http.delete<GoodsReturn>(`${this.base}/companies/${companyId}/goods-returns/${returnId}/lines/${lineId}`);
  }

  approveGoodsReturn(companyId: string, returnId: string): Observable<GoodsReturn> {
    return this.http.post<GoodsReturn>(`${this.base}/companies/${companyId}/goods-returns/${returnId}/approve`, {});
  }

  dispatchGoodsReturn(companyId: string, returnId: string, payload: GoodsReturnDispatchPayload): Observable<GoodsReturn> {
    return this.http.post<GoodsReturn>(`${this.base}/companies/${companyId}/goods-returns/${returnId}/dispatch`, payload);
  }

  createWarehouseReceipt(
    companyId: string,
    returnId: string,
    payload: WarehouseReceiptCreatePayload
  ): Observable<GoodsReturnWarehouseReceipt> {
    return this.http.post<GoodsReturnWarehouseReceipt>(
      `${this.base}/companies/${companyId}/goods-returns/${returnId}/warehouse-receipts`,
      payload
    );
  }

  listWarehouseReceipts(companyId: string, returnId: string): Observable<GoodsReturnWarehouseReceipt[]> {
    return this.http.get<GoodsReturnWarehouseReceipt[]>(
      `${this.base}/companies/${companyId}/goods-returns/${returnId}/warehouse-receipts`
    );
  }

  correctWarehouseReceiptLine(
    companyId: string,
    returnId: string,
    receiptId: string,
    lineId: string,
    payload: WarehouseReceiptCorrectionPayload
  ): Observable<GoodsReturnWarehouseReceipt> {
    return this.http.post<GoodsReturnWarehouseReceipt>(
      `${this.base}/companies/${companyId}/goods-returns/${returnId}/warehouse-receipts/${receiptId}/lines/${lineId}/correct`,
      payload
    );
  }

  completeGoodsReturn(companyId: string, returnId: string): Observable<GoodsReturn> {
    return this.http.post<GoodsReturn>(`${this.base}/companies/${companyId}/goods-returns/${returnId}/complete`, {});
  }

  cancelGoodsReturn(companyId: string, returnId: string, payload: GoodsReturnCancelPayload): Observable<GoodsReturn> {
    return this.http.post<GoodsReturn>(`${this.base}/companies/${companyId}/goods-returns/${returnId}/cancel`, payload);
  }

  getCompanySettings(companyId: string): Observable<Record<string, any>> {
    return this.http.get<Record<string, any>>(`${this.base}/companies/${companyId}/settings`);
  }

  updateCompanySettings(companyId: string, payload: CompanySettingsUpdatePayload): Observable<Record<string, any>> {
    return this.http.put<Record<string, any>>(`${this.base}/companies/${companyId}/settings`, payload);
  }
}

