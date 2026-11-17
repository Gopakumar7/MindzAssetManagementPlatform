import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import {
  GoodsReturn,
  GoodsReturnService,
  GoodsReturnWarehouseReceipt,
} from '../../../services/goods-return.service';
import { formatLocalCalendarDate } from '../../../utils/date.utils';
import { GoodsReturnWarehouseReceiptModalComponent } from './goods-return-warehouse-receipt-modal.component';

describe('GoodsReturnWarehouseReceiptModalComponent', () => {
  let component: GoodsReturnWarehouseReceiptModalComponent;
  let fixture: ComponentFixture<GoodsReturnWarehouseReceiptModalComponent>;
  let mockGoodsReturnService: jasmine.SpyObj<GoodsReturnService>;

  const mockReturn: GoodsReturn = {
    id: 'grr-100',
    company_id: 'comp-1',
    return_number: 'GRR-20261107-0001',
    supplier_id: 'sup-1',
    purchase_order_id: 'po-1',
    original_goods_receipt_id: 'grn-1',
    goods_receipt_reversal_id: 'rev-1',
    return_date: '2026-11-07',
    status: 'dispatched',
    return_reason: 'RMA Return',
    vendor_reference: 'VEND-RMA-123',
    dispatch_reference: 'DISP-CARRIER-01',
    transport_details: 'Logistics Van',
    notes: 'Fragile batch',
    policy_strict_approval_applied: null,
    created_by_id: 'user-1',
    created_at: '2026-11-07T10:00:00Z',
    approved_by_id: 'user-2',
    approved_at: '2026-11-07T11:00:00Z',
    dispatched_by_id: 'user-2',
    dispatched_at: '2026-11-07T12:00:00Z',
    completed_by_id: null,
    completed_at: null,
    cancelled_by_id: null,
    cancelled_at: null,
    cancellation_reason: null,
    lines: [
      {
        id: 'line-1',
        company_id: 'comp-1',
        goods_return_id: 'grr-100',
        goods_receipt_reversal_id: 'rev-1',
        goods_receipt_reversal_asset_id: 'ra-1',
        goods_receipt_reversal_line_id: 'rl-1',
        goods_receipt_line_id: 'gl-1',
        asset_id: 'ast-1',
        asset_number: 'AST-0001',
        serial_number: 'SN-0001',
        return_condition: 'as_received',
        notes: null,
        created_at: '2026-11-07T10:00:00Z',
      },
      {
        id: 'line-2',
        company_id: 'comp-1',
        goods_return_id: 'grr-100',
        goods_receipt_reversal_id: 'rev-1',
        goods_receipt_reversal_asset_id: 'ra-2',
        goods_receipt_reversal_line_id: 'rl-1',
        goods_receipt_line_id: 'gl-1',
        asset_id: 'ast-2',
        asset_number: 'AST-0002',
        serial_number: 'SN-0002',
        return_condition: 'damaged',
        notes: 'Chassis crack',
        created_at: '2026-11-07T10:00:00Z',
      },
    ],
  };

  const mockCreatedReceipt: GoodsReturnWarehouseReceipt = {
    id: 'wr-1',
    company_id: 'comp-1',
    goods_return_id: 'grr-100',
    receipt_number: 'WR-GRR-20261107-0001-01',
    receipt_date: '2026-11-07',
    received_at: '2026-11-07T14:00:00Z',
    received_by_id: 'user-wh',
    warehouse_location_id: null,
    dispatch_reference: 'DISP-CARRIER-01',
    reason: 'Carrier delivery returned to warehouse',
    notes: 'Inspected and verified',
    created_at: '2026-11-07T14:00:00Z',
    lines: [
      {
        id: 'wrl-1',
        company_id: 'comp-1',
        warehouse_receipt_id: 'wr-1',
        goods_return_id: 'grr-100',
        goods_return_line_id: 'line-1',
        asset_id: 'ast-1',
        condition_on_return: 'intact',
        notes: null,
        is_corrected: false,
        correction_reason: null,
        corrected_at: null,
        corrected_by_id: null,
        created_at: '2026-11-07T14:00:00Z',
      },
    ],
  };

  beforeEach(async () => {
    mockGoodsReturnService = jasmine.createSpyObj('GoodsReturnService', ['createWarehouseReceipt']);

    await TestBed.configureTestingModule({
      imports: [GoodsReturnWarehouseReceiptModalComponent],
      providers: [{ provide: GoodsReturnService, useValue: mockGoodsReturnService }],
    }).compileComponents();

    fixture = TestBed.createComponent(GoodsReturnWarehouseReceiptModalComponent);
    component = fixture.componentInstance;
    component.companyId = 'comp-1';
    component.goodsReturn = mockReturn;
    component.warehouseReceipts = [];
    fixture.detectChanges();
  });

  it('initializes eligible assets and pre-fills default values', () => {
    expect(component.eligibleAssets.length).toBe(2);
    expect(component.selectedCount).toBe(2);
    expect(component.receiptDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(component.receiptDate).toBe(formatLocalCalendarDate());
    expect(component.dispatchReference).toBe('DISP-CARRIER-01');
    expect(component.eligibleAssets[0].conditionOnReturn).toBe('intact');
  });

  it('accepts custom condition string without arbitrary enum restriction', () => {
    mockGoodsReturnService.createWarehouseReceipt.and.returnValue(of(mockCreatedReceipt));

    component.reason = 'Inspection bay 1 intake';
    component.confirmed = true;
    component.eligibleAssets[0].selected = true;
    component.eligibleAssets[0].conditionOnReturn = 'minor cosmetic scratch on bezel';
    component.eligibleAssets[1].selected = false;

    component.onSubmit();

    expect(mockGoodsReturnService.createWarehouseReceipt).toHaveBeenCalledWith(
      'comp-1',
      'grr-100',
      jasmine.objectContaining({
        lines: [
          jasmine.objectContaining({
            condition_on_return: 'minor cosmetic scratch on bezel',
          }),
        ],
      })
    );
  });

  it('enforces asset eligibility based on return status and asset_status when available', () => {
    // 1. Ineligible return status (e.g. 'draft') -> 0 eligible assets
    component.goodsReturn = { ...mockReturn, status: 'draft' };
    component.initEligibleAssets();
    expect(component.eligibleAssets.length).toBe(0);

    // 2. Ineligible return status (e.g. 'completed') -> 0 eligible assets
    component.goodsReturn = { ...mockReturn, status: 'completed' };
    component.initEligibleAssets();
    expect(component.eligibleAssets.length).toBe(0);

    // 3. Eligible return status ('partially_returned_to_warehouse') -> assets evaluated
    component.goodsReturn = { ...mockReturn, status: 'partially_returned_to_warehouse' };
    component.initEligibleAssets();
    expect(component.eligibleAssets.length).toBe(2);

    // 4. Line with explicit asset_status other than 'return_pending' is excluded
    component.goodsReturn = {
      ...mockReturn,
      status: 'dispatched',
      lines: [
        { ...mockReturn.lines[0], asset_status: 'return_pending' },
        { ...mockReturn.lines[1], asset_status: 'reversed' },
      ],
    };
    component.initEligibleAssets();
    expect(component.eligibleAssets.length).toBe(1);
    expect(component.eligibleAssets[0].lineId).toBe('line-1');
  });

  it('filters out assets that already have active uncorrected warehouse receipts', () => {
    component.warehouseReceipts = [mockCreatedReceipt];
    component.initEligibleAssets();
    fixture.detectChanges();

    // line-1 has an active receipt in mockCreatedReceipt, so only line-2 remains eligible
    expect(component.eligibleAssets.length).toBe(1);
    expect(component.eligibleAssets[0].lineId).toBe('line-2');
    expect(component.eligibleAssets[0].assetNumber).toBe('AST-0002');
  });

  it('supports select all and deselect all actions', () => {
    expect(component.selectedCount).toBe(2);

    component.deselectAll();
    expect(component.selectedCount).toBe(0);

    component.selectAll();
    expect(component.selectedCount).toBe(2);
  });

  it('validates mandatory fields and prevents submission when invalid', () => {
    // 1. Initial state: reason is empty, unconfirmed -> invalid
    expect(component.isFormValid).toBeFalse();

    // 2. Reason < 3 chars
    component.reason = 'ab';
    component.confirmed = true;
    expect(component.isFormValid).toBeFalse();

    // 3. Reason >= 3 chars but 0 selected
    component.reason = 'Valid reason';
    component.deselectAll();
    expect(component.isFormValid).toBeFalse();

    // 4. Select at least 1, but unconfirmed
    component.eligibleAssets[0].selected = true;
    component.confirmed = false;
    expect(component.isFormValid).toBeFalse();

    // 5. Valid state
    component.confirmed = true;
    expect(component.isFormValid).toBeTrue();
  });

  it('submits valid receipt payload and emits receiptCreated', () => {
    mockGoodsReturnService.createWarehouseReceipt.and.returnValue(of(mockCreatedReceipt));
    spyOn(component.receiptCreated, 'emit');

    component.reason = 'Physical receipt at warehouse bay 3';
    component.notes = 'Batch inspection complete';
    component.eligibleAssets[0].selected = true;
    component.eligibleAssets[0].conditionOnReturn = 'intact';
    component.eligibleAssets[0].notes = 'Package undamaged';
    component.eligibleAssets[1].selected = false;
    component.confirmed = true;

    component.onSubmit();

    expect(mockGoodsReturnService.createWarehouseReceipt).toHaveBeenCalledWith(
      'comp-1',
      'grr-100',
      {
        receipt_date: component.receiptDate,
        reason: 'Physical receipt at warehouse bay 3',
        dispatch_reference: 'DISP-CARRIER-01',
        warehouse_location_id: null,
        notes: 'Batch inspection complete',
        lines: [
          {
            goods_return_line_id: 'line-1',
            condition_on_return: 'intact',
            notes: 'Package undamaged',
          },
        ],
      }
    );
    expect(component.receiptCreated.emit).toHaveBeenCalledWith(mockCreatedReceipt);
    expect(component.submitting).toBeFalse();
  });

  it('handles HTTP 400 with return_pending validation error: displays message, clears selections, resets confirmation, preserves metadata, and triggers refresh', () => {
    mockGoodsReturnService.createWarehouseReceipt.and.returnValue(
      throwError(() => ({
        status: 400,
        error: { detail: "Asset 'AST-0001' has status 'reversed', expected 'return_pending'" },
      }))
    );
    spyOn(component.conflictOccurred, 'emit');

    component.reason = 'Valid intake justification';
    component.dispatchReference = 'DISP-CARRIER-99';
    component.warehouseLocationId = 'loc-uuid-1';
    component.notes = 'Batch received at bay 2';
    component.confirmed = true;
    component.eligibleAssets[0].selected = true;

    const origDate = component.receiptDate;

    component.onSubmit();

    // 1. Error message contains backend detail
    expect(component.error).toBe("Asset 'AST-0001' has status 'reversed', expected 'return_pending'");

    // 2. Not submitting / no auto-resubmit
    expect(component.submitting).toBeFalse();
    expect(mockGoodsReturnService.createWarehouseReceipt).toHaveBeenCalledTimes(1);

    // 3. Stale selection cleared
    expect(component.eligibleAssets.every((a) => !a.selected)).toBeTrue();

    // 4. Confirmation reset
    expect(component.confirmed).toBeFalse();

    // 5. Safe header metadata preserved
    expect(component.receiptDate).toBe(origDate);
    expect(component.reason).toBe('Valid intake justification');
    expect(component.dispatchReference).toBe('DISP-CARRIER-99');
    expect(component.warehouseLocationId).toBe('loc-uuid-1');
    expect(component.notes).toBe('Batch received at bay 2');

    // 6. Reload signal emitted for parent to refresh authoritative detail & receipts
    expect(component.conflictOccurred.emit).toHaveBeenCalled();
  });

  it('handles generic HTTP 400 validation error: preserves selections, preserves confirmation, preserves metadata, and does not trigger refresh', () => {
    mockGoodsReturnService.createWarehouseReceipt.and.returnValue(
      throwError(() => ({
        status: 400,
        error: { detail: 'Invalid warehouse location specified for this company' },
      }))
    );
    spyOn(component.conflictOccurred, 'emit');

    component.reason = 'Valid intake justification';
    component.dispatchReference = 'DISP-CARRIER-99';
    component.warehouseLocationId = 'invalid-uuid';
    component.notes = 'Line notes test';
    component.confirmed = true;
    component.eligibleAssets[0].selected = true;
    component.eligibleAssets[1].selected = false;

    const origDate = component.receiptDate;

    component.onSubmit();

    // 1. Backend error displayed directly without concurrency mislabeling
    expect(component.error).toBe('Invalid warehouse location specified for this company');

    // 2. Selected assets are preserved
    expect(component.eligibleAssets[0].selected).toBeTrue();
    expect(component.eligibleAssets[1].selected).toBeFalse();

    // 3. Confirmation state is preserved
    expect(component.confirmed).toBeTrue();

    // 4. Safe header metadata is preserved
    expect(component.receiptDate).toBe(origDate);
    expect(component.reason).toBe('Valid intake justification');
    expect(component.dispatchReference).toBe('DISP-CARRIER-99');
    expect(component.warehouseLocationId).toBe('invalid-uuid');
    expect(component.notes).toBe('Line notes test');

    // 5. No conflict refresh emitted
    expect(component.conflictOccurred.emit).not.toHaveBeenCalled();

    // 6. No auto-resubmission
    expect(component.submitting).toBeFalse();
    expect(mockGoodsReturnService.createWarehouseReceipt).toHaveBeenCalledTimes(1);
  });

  it('handles HTTP 409 conflict, unchecks confirmation, clears stale selection, preserves metadata, and emits conflictOccurred', () => {
    mockGoodsReturnService.createWarehouseReceipt.and.returnValue(
      throwError(() => ({
        status: 409,
        error: { detail: 'Line line-1 has already been received into the warehouse' },
      }))
    );
    spyOn(component.conflictOccurred, 'emit');

    component.reason = 'Intake test';
    component.dispatchReference = 'DISP-CARRIER-99';
    component.warehouseLocationId = 'loc-uuid-1';
    component.notes = 'Conflict test notes';
    component.confirmed = true;
    component.eligibleAssets[0].selected = true;

    const origDate = component.receiptDate;

    component.onSubmit();

    expect(component.submitting).toBeFalse();
    expect(component.error).toContain('already been received');
    expect(component.confirmed).toBeFalse();
    expect(component.eligibleAssets.every((a) => !a.selected)).toBeTrue();
    expect(component.conflictOccurred.emit).toHaveBeenCalled();

    // Header metadata preserved
    expect(component.receiptDate).toBe(origDate);
    expect(component.reason).toBe('Intake test');
    expect(component.dispatchReference).toBe('DISP-CARRIER-99');
    expect(component.warehouseLocationId).toBe('loc-uuid-1');
    expect(component.notes).toBe('Conflict test notes');
    expect(mockGoodsReturnService.createWarehouseReceipt).toHaveBeenCalledTimes(1);
  });

  it('handles HTTP 403 permission error gracefully', () => {
    mockGoodsReturnService.createWarehouseReceipt.and.returnValue(
      throwError(() => ({
        status: 403,
        error: { detail: 'Forbidden' },
      }))
    );

    component.reason = 'Valid reason';
    component.confirmed = true;
    component.onSubmit();

    expect(component.error).toContain('Forbidden');
  });

  it('handles HTTP 422 validation error gracefully', () => {
    mockGoodsReturnService.createWarehouseReceipt.and.returnValue(
      throwError(() => ({
        status: 422,
        error: { detail: 'Duplicate return lines' },
      }))
    );

    component.reason = 'Valid reason';
    component.confirmed = true;
    component.onSubmit();

    expect(component.error).toContain('Duplicate return lines');
  });

  it('supports escape key dismissal when not submitting', () => {
    const closeSpy = spyOn(component.close, 'emit');

    component.onEscape();
    expect(closeSpy).toHaveBeenCalled();

    closeSpy.calls.reset();
    component.submitting = true;
    component.onEscape();
    expect(closeSpy).not.toHaveBeenCalled();
  });
});
