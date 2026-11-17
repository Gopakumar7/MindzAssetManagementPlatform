import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import {
  GoodsReceiptReversalEligibilityResponse,
  GoodsReceiptReversalRead,
  GoodsReturnService,
} from '../../../services/goods-return.service';
import { GoodsReceipt } from '../../../services/registry.service';
import { GoodsReceiptReversalModalComponent } from './goods-receipt-reversal-modal.component';

describe('GoodsReceiptReversalModalComponent', () => {
  let component: GoodsReceiptReversalModalComponent;
  let fixture: ComponentFixture<GoodsReceiptReversalModalComponent>;
  let mockGoodsReturnService: jasmine.SpyObj<GoodsReturnService>;

  const mockReceipt: GoodsReceipt = {
    id: 'receipt-uuid-1',
    company_id: 'company-uuid-1',
    purchase_order_id: 'po-uuid-1',
    receipt_number: 'GRN-20261107-001',
    received_date: '2026-11-07',
    delivery_reference: 'DEL-001',
    notes: 'Intake batch A',
    status: 'completed',
    created_at: '2026-11-07T10:00:00Z',
    lines: [
      {
        id: 'line-uuid-1',
        purchase_order_line_id: 'po-line-1',
        quantity_received: 3,
        quantity_rejected: 0,
        quantity_reversed: 0,
        discrepancy_notes: null,
        assets: [
          { id: 'ast-1', asset_number: 'AST-001', serial_number: 'SN-001', status: 'in_stock' },
          { id: 'ast-2', asset_number: 'AST-002', serial_number: 'SN-002', status: 'in_stock' },
          { id: 'ast-3', asset_number: 'AST-003', serial_number: 'SN-003', status: 'in_stock' },
        ],
      },
    ],
  };

  const mockEligibilityResponse: GoodsReceiptReversalEligibilityResponse = {
    goods_receipt_id: 'receipt-uuid-1',
    receipt_number: 'GRN-20261107-001',
    status: 'completed',
    is_reversible: true,
    total_accepted_quantity: 3,
    total_quantity_reversed: 0,
    unreversed_accepted_quantity: 3,
    lines: [
      {
        goods_receipt_line_id: 'line-uuid-1',
        purchase_order_line_id: 'po-line-1',
        quantity_received: 3,
        quantity_rejected: 0,
        quantity_reversed: 0,
        unreversed_accepted_quantity: 3,
        eligible_asset_count: 2,
      },
    ],
    assets: [
      {
        asset_id: 'ast-1',
        asset_number: 'AST-001',
        serial_number: 'SN-001',
        status: 'in_stock',
        is_eligible: true,
        blocking_reasons: [],
      },
      {
        asset_id: 'ast-2',
        asset_number: 'AST-002',
        serial_number: 'SN-002',
        status: 'in_stock',
        is_eligible: true,
        blocking_reasons: [],
      },
      {
        asset_id: 'ast-3',
        asset_number: 'AST-003',
        serial_number: 'SN-003',
        status: 'assigned',
        is_eligible: false,
        blocking_reasons: ['Asset is currently assigned to user (Jane Doe)'],
      },
    ],
  };

  beforeEach(async () => {
    mockGoodsReturnService = jasmine.createSpyObj('GoodsReturnService', [
      'getGoodsReceiptReversalCheck',
      'reverseGoodsReceipt',
    ]);
    mockGoodsReturnService.getGoodsReceiptReversalCheck.and.returnValue(
      of(mockEligibilityResponse)
    );

    await TestBed.configureTestingModule({
      imports: [GoodsReceiptReversalModalComponent],
      providers: [
        { provide: GoodsReturnService, useValue: mockGoodsReturnService },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(GoodsReceiptReversalModalComponent);
    component = fixture.componentInstance;
    component.companyId = 'company-uuid-1';
    component.receipt = mockReceipt;
    fixture.detectChanges();
  });

  it('should initialize and load eligibility check from backend endpoint', () => {
    expect(component).toBeTruthy();
    expect(mockGoodsReturnService.getGoodsReceiptReversalCheck).toHaveBeenCalledWith(
      'company-uuid-1',
      'receipt-uuid-1'
    );
    expect(component.loading).toBeFalse();
    expect(component.checkResult).toEqual(mockEligibilityResponse);
    expect(component.eligibleAssetIds).toEqual(['ast-1', 'ast-2']);
  });

  it('should map assets to their parent goods_receipt_line_id', () => {
    expect(component.assetLineMap.get('ast-1')).toBe('line-uuid-1');
    expect(component.assetLineMap.get('ast-2')).toBe('line-uuid-1');
    expect(component.assetLineMap.get('ast-3')).toBe('line-uuid-1');
  });

  it('should toggle individual asset selection', () => {
    expect(component.isAssetSelected('ast-1')).toBeFalse();
    component.toggleAsset('ast-1');
    expect(component.isAssetSelected('ast-1')).toBeTrue();
    component.toggleAsset('ast-1');
    expect(component.isAssetSelected('ast-1')).toBeFalse();
  });

  it('should select all eligible assets and toggle them off', () => {
    expect(component.areAllEligibleSelected()).toBeFalse();
    component.selectAllEligible();
    expect(component.isAssetSelected('ast-1')).toBeTrue();
    expect(component.isAssetSelected('ast-2')).toBeTrue();
    expect(component.isAssetSelected('ast-3')).toBeFalse(); // ast-3 is ineligible
    expect(component.areAllEligibleSelected()).toBeTrue();

    // Toggle off
    component.selectAllEligible();
    expect(component.areAllEligibleSelected()).toBeFalse();
    expect(component.selectedAssetIds.size).toBe(0);
  });

  it('should strictly validate submission conditions (min 1 asset and non-empty reason)', () => {
    component.selectedAssetIds.clear();
    component.reversalReason = '';
    expect(component.canSubmit()).toBeFalse();

    // Only asset selected, no reason
    component.toggleAsset('ast-1');
    expect(component.canSubmit()).toBeFalse();

    // Asset selected and whitespace reason
    component.reversalReason = '   ';
    expect(component.canSubmit()).toBeFalse();

    // Asset selected and valid reason
    component.reversalReason = 'Defective screen batch';
    expect(component.canSubmit()).toBeTrue();

    // During submission
    component.submitting = true;
    expect(component.canSubmit()).toBeFalse();
  });

  it('should execute reversal with correct payload and emit reversalCompleted', () => {
    const mockReversalResult: GoodsReceiptReversalRead = {
      id: 'rev-res-1',
      company_id: 'company-uuid-1',
      goods_receipt_id: 'receipt-uuid-1',
      purchase_order_id: 'po-uuid-1',
      reversal_reference: 'REV-001',
      reversed_at: '2026-11-07T12:00:00Z',
      reversed_by_id: 'user-uuid-1',
      reason: 'Defective screen batch',
      created_at: '2026-11-07T12:00:00Z',
      lines: [],
    };
    mockGoodsReturnService.reverseGoodsReceipt.and.returnValue(of(mockReversalResult));

    spyOn(component.reversalCompleted, 'emit');

    component.toggleAsset('ast-1');
    component.toggleAsset('ast-2');
    component.reversalReason = 'Defective screen batch';

    component.submitReversal();

    expect(mockGoodsReturnService.reverseGoodsReceipt).toHaveBeenCalledWith(
      'company-uuid-1',
      'receipt-uuid-1',
      {
        reason: 'Defective screen batch',
        lines: [
          {
            goods_receipt_line_id: 'line-uuid-1',
            asset_ids: ['ast-1', 'ast-2'],
            notes: null,
          },
        ],
      }
    );
    expect(component.submitting).toBeFalse();
    expect(component.reversalCompleted.emit).toHaveBeenCalledWith(mockReversalResult);
  });

  it('should handle HTTP 409 conflict gracefully preserving user selection and reason', () => {
    mockGoodsReturnService.reverseGoodsReceipt.and.returnValue(
      throwError(() => ({
        status: 409,
        error: { detail: 'Goods receipt "GRN-20261107-001" is already fully reversed' },
      }))
    );

    component.toggleAsset('ast-1');
    component.reversalReason = 'Defective screen batch';

    component.submitReversal();

    expect(component.submitting).toBeFalse();
    expect(component.error).toBe('Goods receipt "GRN-20261107-001" is already fully reversed');
    // Context preserved
    expect(component.isAssetSelected('ast-1')).toBeTrue();
    expect(component.reversalReason).toBe('Defective screen batch');
  });

  it('should emit close when onClose is called', () => {
    spyOn(component.close, 'emit');
    component.onClose();
    expect(component.close.emit).toHaveBeenCalled();
  });
});
