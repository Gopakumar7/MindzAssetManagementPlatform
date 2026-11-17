import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import {
  GoodsReturn,
  GoodsReturnService,
  GoodsReturnWarehouseReceipt,
  GoodsReturnWarehouseReceiptLine,
} from '../../../services/goods-return.service';
import { GoodsReturnReceiptCorrectionModalComponent } from './goods-return-receipt-correction-modal.component';

describe('GoodsReturnReceiptCorrectionModalComponent', () => {
  let component: GoodsReturnReceiptCorrectionModalComponent;
  let fixture: ComponentFixture<GoodsReturnReceiptCorrectionModalComponent>;
  let mockGoodsReturnService: jasmine.SpyObj<GoodsReturnService>;

  const mockReturn: GoodsReturn = {
    id: 'grr-101',
    company_id: 'comp-1',
    return_number: 'GRR-20261108-001',
    supplier_id: 'sup-1',
    purchase_order_id: 'po-1',
    original_goods_receipt_id: 'grn-1',
    goods_receipt_reversal_id: 'rev-1',
    return_date: '2026-11-08',
    status: 'partially_returned_to_warehouse',
    return_reason: 'Defective goods batch',
    vendor_reference: 'RMA-999',
    dispatch_reference: 'DISP-777',
    transport_details: 'DHL Express',
    notes: 'Urgent return',
    policy_strict_approval_applied: true,
    created_by_id: 'user-creator',
    created_at: '2026-11-08T08:00:00Z',
    approved_by_id: 'user-approver',
    approved_at: '2026-11-08T09:00:00Z',
    dispatched_by_id: 'user-dispatcher',
    dispatched_at: '2026-11-08T10:00:00Z',
    completed_by_id: null,
    completed_at: null,
    cancelled_by_id: null,
    cancelled_at: null,
    cancellation_reason: null,
    lines: [
      {
        id: 'grr-line-1',
        company_id: 'comp-1',
        goods_return_id: 'grr-101',
        goods_receipt_reversal_id: 'rev-1',
        goods_receipt_reversal_asset_id: 'rev-ast-1',
        goods_receipt_reversal_line_id: 'rev-line-1',
        goods_receipt_line_id: 'grn-line-1',
        asset_id: 'ast-1',
        asset_number: 'AST-2026-0001',
        serial_number: 'SN-ABC-123',
        return_condition: 'damaged',
        notes: 'Screen cracked',
        created_at: '2026-11-08T08:00:00Z',
      },
    ],
  };

  const mockReceiptLine: GoodsReturnWarehouseReceiptLine = {
    id: 'wrl-1',
    company_id: 'comp-1',
    warehouse_receipt_id: 'wr-1',
    goods_return_id: 'grr-101',
    goods_return_line_id: 'grr-line-1',
    asset_id: 'ast-1',
    condition_on_return: 'damaged',
    notes: 'Received in broken packaging',
    is_corrected: false,
    correction_reason: null,
    corrected_at: null,
    corrected_by_id: null,
    created_at: '2026-11-08T11:00:00Z',
  };

  const mockReceipt: GoodsReturnWarehouseReceipt = {
    id: 'wr-1',
    company_id: 'comp-1',
    goods_return_id: 'grr-101',
    receipt_number: 'WR-20261108-01',
    receipt_date: '2026-11-08',
    received_at: '2026-11-08T11:00:00Z',
    received_by_id: 'user-wh-clerk',
    warehouse_location_id: 'loc-wh-1',
    dispatch_reference: 'DISP-777',
    reason: 'Physical delivery back to dock',
    notes: 'Truck arrived 10:30',
    created_at: '2026-11-08T11:00:00Z',
    lines: [mockReceiptLine],
  };

  beforeEach(async () => {
    mockGoodsReturnService = jasmine.createSpyObj('GoodsReturnService', [
      'correctWarehouseReceiptLine',
    ]);

    await TestBed.configureTestingModule({
      imports: [GoodsReturnReceiptCorrectionModalComponent],
      providers: [{ provide: GoodsReturnService, useValue: mockGoodsReturnService }],
    }).compileComponents();

    fixture = TestBed.createComponent(GoodsReturnReceiptCorrectionModalComponent);
    component = fixture.componentInstance;
    component.companyId = 'comp-1';
    component.goodsReturn = mockReturn;
    component.receipt = mockReceipt;
    component.receiptLine = mockReceiptLine;
    component.assetNumber = 'AST-2026-0001';
    component.serialNumber = 'SN-ABC-123';
    fixture.detectChanges();
  });

  it('should create the correction modal component', () => {
    expect(component).toBeTruthy();
  });

  describe('Modal Rendering and Read-Only Context', () => {
    it('renders original receipt and asset details correctly', () => {
      const compiled = fixture.nativeElement as HTMLElement;
      expect(compiled.textContent).toContain('AST-2026-0001');
      expect(compiled.textContent).toContain('SN-ABC-123');
      expect(compiled.textContent).toContain('WR-20261108-01');
      expect(compiled.textContent).toContain('2026-11-08');
      expect(compiled.textContent).toContain('damaged');
      expect(compiled.textContent).toContain('Received in broken packaging');
      expect(compiled.textContent).toContain('Truck arrived 10:30');
    });

    it('falls back to default labels when assetNumber or serialNumber are omitted', () => {
      component.assetNumber = undefined;
      component.serialNumber = null;
      fixture.detectChanges();

      const compiled = fixture.nativeElement as HTMLElement;
      expect(compiled.textContent).toContain('AST-N/A');
      expect(compiled.textContent).toContain('—');
    });

    it('displays the lifecycle effects notice', () => {
      const compiled = fixture.nativeElement as HTMLElement;
      expect(compiled.textContent).toContain('Lifecycle Effects Notice');
      expect(compiled.textContent).toContain('return_pending');
      expect(compiled.textContent).toContain('vendor-return asset reservation');
    });
  });

  describe('Validation and Submission Controls', () => {
    it('rejects an empty reason', () => {
      component.correctionReason = '';
      component.confirmed = true;
      expect(component.isReasonValid).toBeFalse();
      expect(component.isFormValid).toBeFalse();

      component.onSubmit();
      expect(component.validationError).toContain('Correction reason is mandatory');
      expect(mockGoodsReturnService.correctWarehouseReceiptLine).not.toHaveBeenCalled();
    });

    it('rejects a reason with fewer than 5 characters', () => {
      component.correctionReason = 'Four';
      component.confirmed = true;
      expect(component.reasonLength).toBe(4);
      expect(component.isReasonValid).toBeFalse();
      expect(component.isFormValid).toBeFalse();

      component.onSubmit();
      expect(component.validationError).toContain('at least 5 characters');
      expect(mockGoodsReturnService.correctWarehouseReceiptLine).not.toHaveBeenCalled();
    });

    it('rejects a whitespace-only reason or whitespace padding under 5 real characters', () => {
      component.correctionReason = '   ab   ';
      component.confirmed = true;
      expect(component.trimmedReason).toBe('ab');
      expect(component.reasonLength).toBe(2);
      expect(component.isReasonValid).toBeFalse();
      expect(component.isFormValid).toBeFalse();

      component.onSubmit();
      expect(component.validationError).toContain('at least 5 characters');
      expect(mockGoodsReturnService.correctWarehouseReceiptLine).not.toHaveBeenCalled();
    });

    it('requires the confirmation checkbox even with a valid reason', () => {
      component.correctionReason = 'Scanned wrong serial into inventory dock';
      component.confirmed = false;
      expect(component.isReasonValid).toBeTrue();
      expect(component.isFormValid).toBeFalse();

      component.onSubmit();
      expect(component.validationError).toContain('confirm that you understand the lifecycle effects');
      expect(mockGoodsReturnService.correctWarehouseReceiptLine).not.toHaveBeenCalled();
    });

    it('enables form validity and submits payload when reason >= 5 characters and confirmed', () => {
      const updatedReceipt: GoodsReturnWarehouseReceipt = {
        ...mockReceipt,
        lines: [
          {
            ...mockReceiptLine,
            is_corrected: true,
            correction_reason: 'Scanned wrong serial into inventory dock',
            corrected_at: '2026-11-08T12:00:00Z',
            corrected_by_id: 'user-manager',
          },
        ],
      };

      mockGoodsReturnService.correctWarehouseReceiptLine.and.returnValue(of(updatedReceipt));
      spyOn(component.corrected, 'emit');

      component.correctionReason = '  Scanned wrong serial into inventory dock  ';
      component.notes = '  Carrier delivered replacement later  ';
      component.confirmed = true;

      expect(component.isFormValid).toBeTrue();

      component.onSubmit();

      expect(mockGoodsReturnService.correctWarehouseReceiptLine).toHaveBeenCalledWith(
        'comp-1',
        'grr-101',
        'wr-1',
        'wrl-1',
        {
          correction_reason: 'Scanned wrong serial into inventory dock',
          notes: 'Carrier delivered replacement later',
        }
      );
      expect(component.submitting).toBeFalse();
      expect(component.corrected.emit).toHaveBeenCalledWith(updatedReceipt);
    });

    it('submits null notes when optional notes are empty or whitespace', () => {
      const updatedReceipt: GoodsReturnWarehouseReceipt = { ...mockReceipt };
      mockGoodsReturnService.correctWarehouseReceiptLine.and.returnValue(of(updatedReceipt));

      component.correctionReason = 'Valid reason for correction';
      component.notes = '   ';
      component.confirmed = true;

      component.onSubmit();

      expect(mockGoodsReturnService.correctWarehouseReceiptLine).toHaveBeenCalledWith(
        jasmine.any(String),
        jasmine.any(String),
        jasmine.any(String),
        jasmine.any(String),
        {
          correction_reason: 'Valid reason for correction',
          notes: null,
        }
      );
    });

    it('disables submit button while submitting and prevents duplicate submissions', () => {
      mockGoodsReturnService.correctWarehouseReceiptLine.and.returnValue(of(mockReceipt));

      component.correctionReason = 'Valid reason for correction';
      component.confirmed = true;
      component.submitting = true;

      expect(component.isFormValid).toBeFalse();

      component.onSubmit();
      expect(mockGoodsReturnService.correctWarehouseReceiptLine).not.toHaveBeenCalled();
    });
  });

  describe('Error Handling and Stale-Data Recovery', () => {
    beforeEach(() => {
      component.correctionReason = 'Scanned wrong asset tag';
      component.notes = 'Preserve this note';
      component.confirmed = true;
    });

    it('handles HTTP 401 and displays authentication message', () => {
      mockGoodsReturnService.correctWarehouseReceiptLine.and.returnValue(
        throwError(() => ({ status: 401, error: { detail: 'Unauthorized' } }))
      );

      component.onSubmit();

      expect(component.submitting).toBeFalse();
      expect(component.error).toContain('Authentication session expired');
      expect(component.correctionReason).toBe('Scanned wrong asset tag');
      expect(component.notes).toBe('Preserve this note');
    });

    it('handles HTTP 403 and displays permission error without conflict reload', () => {
      mockGoodsReturnService.correctWarehouseReceiptLine.and.returnValue(
        throwError(() => ({
          status: 403,
          error: { detail: 'Permission procurement.manage is required.' },
        }))
      );
      spyOn(component.conflictOccurred, 'emit');

      component.onSubmit();

      expect(component.submitting).toBeFalse();
      expect(component.error).toContain('Permission procurement.manage is required.');
      expect(component.conflictOccurred.emit).not.toHaveBeenCalled();
      expect(component.correctionReason).toBe('Scanned wrong asset tag');
    });

    it('handles HTTP 404, explains line no longer exists, and triggers conflictOccurred', () => {
      mockGoodsReturnService.correctWarehouseReceiptLine.and.returnValue(
        throwError(() => ({
          status: 404,
          error: { detail: 'Warehouse receipt line wrl-1 not found.' },
        }))
      );
      spyOn(component.conflictOccurred, 'emit');

      component.onSubmit();

      expect(component.submitting).toBeFalse();
      expect(component.error).toContain('Warehouse receipt line wrl-1 not found.');
      expect(component.conflictOccurred.emit).toHaveBeenCalled();
      expect(component.correctionReason).toBe('Scanned wrong asset tag');
    });

    it('handles HTTP 409, displays backend eligibility explanation, and triggers conflictOccurred', () => {
      const conflictMsg =
        "Asset 'AST-2026-0001' cannot be corrected because it is currently assigned to user-emp-99.";
      mockGoodsReturnService.correctWarehouseReceiptLine.and.returnValue(
        throwError(() => ({
          status: 409,
          error: { detail: conflictMsg },
        }))
      );
      spyOn(component.conflictOccurred, 'emit');

      component.onSubmit();

      expect(component.submitting).toBeFalse();
      expect(component.error).toBe(conflictMsg);
      expect(component.conflictOccurred.emit).toHaveBeenCalled();
      // Form inputs must remain preserved
      expect(component.correctionReason).toBe('Scanned wrong asset tag');
      expect(component.notes).toBe('Preserve this note');
    });

    it('handles HTTP 422, displays validation feedback, and preserves inputs', () => {
      mockGoodsReturnService.correctWarehouseReceiptLine.and.returnValue(
        throwError(() => ({
          status: 422,
          error: { detail: 'String should have at least 5 characters' },
        }))
      );

      component.onSubmit();

      expect(component.submitting).toBeFalse();
      expect(component.error).toContain('String should have at least 5 characters');
      expect(component.correctionReason).toBe('Scanned wrong asset tag');
    });

    it('handles generic server errors safely and preserves inputs', () => {
      mockGoodsReturnService.correctWarehouseReceiptLine.and.returnValue(
        throwError(() => ({ status: 500, message: 'Internal Server Error' }))
      );

      component.onSubmit();

      expect(component.submitting).toBeFalse();
      expect(component.error).toContain('Internal Server Error');
      expect(component.correctionReason).toBe('Scanned wrong asset tag');
      expect(component.notes).toBe('Preserve this note');
    });
  });

  describe('Keyboard and Modal Dismissal Safeguards', () => {
    it('emits close on Escape key when not submitting', () => {
      spyOn(component.close, 'emit');
      component.submitting = false;

      const event = new KeyboardEvent('keydown', { key: 'Escape' });
      component.onEscape(event);

      expect(component.close.emit).toHaveBeenCalled();
    });

    it('suppresses Escape key dismissal while submitting is true', () => {
      spyOn(component.close, 'emit');
      component.submitting = true;

      const event = new KeyboardEvent('keydown', { key: 'Escape' });
      component.onEscape(event);

      expect(component.close.emit).not.toHaveBeenCalled();
    });

    it('suppresses onClose when submitting is true', () => {
      spyOn(component.close, 'emit');
      component.submitting = true;

      component.onClose();

      expect(component.close.emit).not.toHaveBeenCalled();
    });
  });
});
