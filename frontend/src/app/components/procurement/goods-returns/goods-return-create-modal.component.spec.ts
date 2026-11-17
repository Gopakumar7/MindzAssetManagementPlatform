import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import {
  GoodsReceiptReversalRead,
  GoodsReturn,
  GoodsReturnService,
  ReturnEligibleAssetItem,
} from '../../../services/goods-return.service';
import { GoodsReceipt } from '../../../services/registry.service';
import { GoodsReturnCreateModalComponent } from './goods-return-create-modal.component';

describe('GoodsReturnCreateModalComponent', () => {
  let component: GoodsReturnCreateModalComponent;
  let fixture: ComponentFixture<GoodsReturnCreateModalComponent>;
  let mockGoodsReturnService: jasmine.SpyObj<GoodsReturnService>;

  const mockReceipt: GoodsReceipt = {
    id: 'receipt-1',
    company_id: 'comp-1',
    purchase_order_id: 'po-1',
    receipt_number: 'GRN-20261107-001',
    received_date: '2026-11-07',
    delivery_reference: 'DEL-1',
    notes: null,
    status: 'partially_reversed',
    created_at: '2026-11-07T10:00:00Z',
    lines: [
      {
        id: 'gl-1',
        purchase_order_line_id: 'po-line-1',
        quantity_received: 3,
        quantity_rejected: 0,
        quantity_reversed: 2,
        discrepancy_notes: null,
        assets: [],
      },
    ],
  };

  const mockReversals: GoodsReceiptReversalRead[] = [
    {
      id: 'rev-1',
      company_id: 'comp-1',
      goods_receipt_id: 'receipt-1',
      purchase_order_id: 'po-1',
      reversal_reference: 'REV-20261107-0001',
      reversed_at: '2026-11-07T11:00:00Z',
      reversed_by_id: 'user-1',
      reason: 'Defective screen batch',
      created_at: '2026-11-07T11:00:00Z',
      lines: [],
    },
  ];

  const mockEligibleAssets: ReturnEligibleAssetItem[] = [
    {
      goods_receipt_reversal_asset_id: 'ra-1',
      reversal_id: 'rev-1',
      reversal_line_id: 'rl-1',
      goods_receipt_line_id: 'gl-1',
      asset_id: 'ast-1',
      asset_number: 'AST-001',
      serial_number: 'SN-001',
      is_actively_reserved: false,
      active_reservation_return_id: null,
      active_reservation_return_number: null,
      is_eligible: true,
      ineligibility_reason: null,
    },
    {
      goods_receipt_reversal_asset_id: 'ra-2',
      reversal_id: 'rev-1',
      reversal_line_id: 'rl-1',
      goods_receipt_line_id: 'gl-1',
      asset_id: 'ast-2',
      asset_number: 'AST-002',
      serial_number: 'SN-002',
      is_actively_reserved: true,
      active_reservation_return_id: 'grr-other',
      active_reservation_return_number: 'GRR-20261107-0099',
      is_eligible: false,
      ineligibility_reason: 'Asset is actively reserved in Return GRR-20261107-0099',
    },
    {
      goods_receipt_reversal_asset_id: 'ra-3',
      reversal_id: 'rev-1',
      reversal_line_id: 'rl-1',
      goods_receipt_line_id: 'gl-1',
      asset_id: 'ast-3',
      asset_number: 'AST-003',
      serial_number: 'SN-003',
      is_actively_reserved: false,
      active_reservation_return_id: null,
      active_reservation_return_number: null,
      is_eligible: false,
      ineligibility_reason: "Asset status is 'in_stock', expected 'reversed'",
    },
  ];

  beforeEach(async () => {
    mockGoodsReturnService = jasmine.createSpyObj('GoodsReturnService', [
      'listGoodsReceiptReversals',
      'getReturnEligibleAssets',
      'createGoodsReturn',
    ]);
    mockGoodsReturnService.listGoodsReceiptReversals.and.returnValue(of(mockReversals));
    mockGoodsReturnService.getReturnEligibleAssets.and.returnValue(of(mockEligibleAssets));

    await TestBed.configureTestingModule({
      imports: [GoodsReturnCreateModalComponent],
      providers: [
        { provide: GoodsReturnService, useValue: mockGoodsReturnService },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(GoodsReturnCreateModalComponent);
    component = fixture.componentInstance;
    component.companyId = 'comp-1';
    component.availableReceipts = [mockReceipt];
    fixture.detectChanges();
  });

  it('should initialize on step 1 with source selection', () => {
    expect(component).toBeTruthy();
    expect(component.step).toBe('select_source');
    expect(component.receiptsWithReversals.length).toBe(1);
  });

  it('should load reversals when a receipt is selected and auto-select if only 1 exists', () => {
    component.selectedReceiptId = 'receipt-1';
    component.onReceiptSelected();
    expect(mockGoodsReturnService.listGoodsReceiptReversals).toHaveBeenCalledWith('comp-1', 'receipt-1');
    expect(component.receiptReversals.length).toBe(1);
    expect(component.selectedReversalId).toBe('rev-1');
  });

  it('should transition to step 2 and fetch eligible assets', () => {
    component.selectedReceiptId = 'receipt-1';
    component.selectedReversalId = 'rev-1';
    component.proceedToAssets();

    expect(component.step).toBe('select_assets');
    expect(mockGoodsReturnService.getReturnEligibleAssets).toHaveBeenCalledWith('comp-1', 'rev-1');
    expect(component.eligibleAssets.length).toBe(3);
    expect(component.selectableAssetCount).toBe(1); // Only ra-1 is eligible & not reserved
  });

  it('should toggle selection for eligible assets and prevent selection of reserved/ineligible ones', () => {
    component.selectedReversalId = 'rev-1';
    component.loadEligibleAssets('rev-1');

    // Select eligible asset
    expect(component.isAssetSelected('ra-1')).toBeFalse();
    component.toggleAsset('ra-1');
    expect(component.isAssetSelected('ra-1')).toBeTrue();

    // Select all eligible toggles only eligible, unreserved assets
    component.selectedReversalAssetIds.clear();
    component.selectAllEligible();
    expect(component.isAssetSelected('ra-1')).toBeTrue();
    expect(component.isAssetSelected('ra-2')).toBeFalse(); // Actively reserved
    expect(component.isAssetSelected('ra-3')).toBeFalse(); // Ineligible status
  });

  it('should validate form completeness (min 1 asset and non-empty reason)', () => {
    component.selectedReversalAssetIds.clear();
    component.returnReason = '';
    expect(component.canSubmit()).toBeFalse();

    component.toggleAsset('ra-1');
    expect(component.canSubmit()).toBeFalse(); // Reason still empty

    component.returnReason = '   ';
    expect(component.canSubmit()).toBeFalse(); // Whitespace reason

    component.returnReason = 'Vendor recall batch #10';
    expect(component.canSubmit()).toBeTrue(); // Valid
  });

  it('should successfully submit Goods Return creation and emit returnCreated', () => {
    const mockCreated: GoodsReturn = {
      id: 'grr-new-1',
      company_id: 'comp-1',
      return_number: 'GRR-20261107-0001',
      supplier_id: 'sup-1',
      purchase_order_id: 'po-1',
      original_goods_receipt_id: 'receipt-1',
      goods_receipt_reversal_id: 'rev-1',
      return_date: '2026-11-07',
      status: 'draft',
      return_reason: 'Vendor recall batch #10',
      vendor_reference: 'RMA-999',
      dispatch_reference: null,
      transport_details: null,
      notes: 'Please pack in anti-static bags',
      policy_strict_approval_applied: null,
      created_by_id: 'user-1',
      created_at: '2026-11-07T12:00:00Z',
      approved_by_id: null,
      approved_at: null,
      dispatched_by_id: null,
      dispatched_at: null,
      completed_by_id: null,
      completed_at: null,
      cancelled_by_id: null,
      cancelled_at: null,
      cancellation_reason: null,
      lines: [],
    };
    mockGoodsReturnService.createGoodsReturn.and.returnValue(of(mockCreated));

    spyOn(component.returnCreated, 'emit');

    component.selectedReversalId = 'rev-1';
    component.toggleAsset('ra-1');
    component.returnReason = 'Vendor recall batch #10';
    component.vendorReference = 'RMA-999';
    component.notes = 'Please pack in anti-static bags';

    component.submitReturn();

    expect(mockGoodsReturnService.createGoodsReturn).toHaveBeenCalledWith('comp-1', {
      goods_receipt_reversal_id: 'rev-1',
      return_date: component.returnDate,
      return_reason: 'Vendor recall batch #10',
      vendor_reference: 'RMA-999',
      notes: 'Please pack in anti-static bags',
      lines: [
        {
          goods_receipt_reversal_asset_id: 'ra-1',
          return_condition: 'as_received',
          notes: null,
        },
      ],
    });
    expect(component.returnCreated.emit).toHaveBeenCalledWith(mockCreated);
  });

  it('should handle HTTP 409 reservation conflict: display conflict warning and refresh reservation state', () => {
    mockGoodsReturnService.createGoodsReturn.and.returnValue(
      throwError(() => ({
        status: 409,
        error: { detail: 'One or more selected assets are already actively reserved in another Goods Return.' },
      }))
    );

    // Initial state: ra-1 is selected
    component.selectedReversalId = 'rev-1';
    component.toggleAsset('ra-1');
    component.returnReason = 'Vendor recall batch #10';
    component.vendorReference = 'RMA-999';

    // Mock refresh where ra-1 becomes actively reserved by a competing operator
    const refreshedAssets: ReturnEligibleAssetItem[] = [
      {
        ...mockEligibleAssets[0],
        is_actively_reserved: true,
        active_reservation_return_number: 'GRR-COMPETING-001',
        is_eligible: false,
      },
    ];
    mockGoodsReturnService.getReturnEligibleAssets.and.returnValue(of(refreshedAssets));

    component.submitReturn();

    expect(component.submitting).toBeFalse();
    expect(component.conflictWarning).toContain('Reservation Conflict (409)');
    // Input state preserved
    expect(component.returnReason).toBe('Vendor recall batch #10');
    expect(component.vendorReference).toBe('RMA-999');
    // Newly reserved asset deselected automatically by loadEligibleAssets
    expect(component.isAssetSelected('ra-1')).toBeFalse();
  });

  it('should handle general API error on submission without resetting user input', () => {
    mockGoodsReturnService.createGoodsReturn.and.returnValue(
      throwError(() => new Error('Network timeout'))
    );

    component.selectedReversalId = 'rev-1';
    component.toggleAsset('ra-1');
    component.returnReason = 'Vendor recall batch #10';

    component.submitReturn();

    expect(component.submitting).toBeFalse();
    expect(component.error).toBe('Network timeout');
    expect(component.returnReason).toBe('Vendor recall batch #10');
    expect(component.isAssetSelected('ra-1')).toBeTrue();
  });

  it('should emit close on onClose', () => {
    spyOn(component.close, 'emit');
    component.onClose();
    expect(component.close.emit).toHaveBeenCalled();
  });
});
