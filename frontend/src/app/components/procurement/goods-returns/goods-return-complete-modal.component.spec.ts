import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import {
  GoodsReturn,
  GoodsReturnLine,
  GoodsReturnService,
} from '../../../services/goods-return.service';
import { GoodsReturnCompleteModalComponent } from './goods-return-complete-modal.component';

describe('GoodsReturnCompleteModalComponent', () => {
  let component: GoodsReturnCompleteModalComponent;
  let fixture: ComponentFixture<GoodsReturnCompleteModalComponent>;
  let mockGoodsReturnService: jasmine.SpyObj<GoodsReturnService>;

  const mockReturn: GoodsReturn = {
    id: 'grr-101',
    company_id: 'comp-1',
    return_number: 'GRR-20261108-0001',
    supplier_id: 'sup-1',
    purchase_order_id: 'po-1',
    original_goods_receipt_id: 'grn-1',
    goods_receipt_reversal_id: 'rev-1',
    return_date: '2026-11-08',
    status: 'partially_returned_to_warehouse',
    return_reason: 'Defective batch',
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
        goods_receipt_reversal_asset_id: 'ra-1',
        goods_receipt_reversal_line_id: 'rl-1',
        goods_receipt_line_id: 'gl-1',
        asset_id: 'ast-1',
        asset_number: 'AST-2026-0001',
        serial_number: 'SN-ABC-1',
        return_condition: 'damaged',
        notes: 'Cracked screen',
        created_at: '2026-11-08T08:00:00Z',
      },
      {
        id: 'grr-line-2',
        company_id: 'comp-1',
        goods_return_id: 'grr-101',
        goods_receipt_reversal_id: 'rev-1',
        goods_receipt_reversal_asset_id: 'ra-2',
        goods_receipt_reversal_line_id: 'rl-1',
        goods_receipt_line_id: 'gl-1',
        asset_id: 'ast-2',
        asset_number: 'AST-2026-0002',
        serial_number: 'SN-ABC-2',
        return_condition: 'as_received',
        notes: null,
        created_at: '2026-11-08T08:00:00Z',
      },
    ],
  };

  const outstandingLine: GoodsReturnLine = mockReturn.lines[1]; // Asset 2 in transit

  beforeEach(async () => {
    mockGoodsReturnService = jasmine.createSpyObj('GoodsReturnService', [
      'completeGoodsReturn',
    ]);

    await TestBed.configureTestingModule({
      imports: [GoodsReturnCompleteModalComponent],
      providers: [{ provide: GoodsReturnService, useValue: mockGoodsReturnService }],
    }).compileComponents();

    fixture = TestBed.createComponent(GoodsReturnCompleteModalComponent);
    component = fixture.componentInstance;
    component.companyId = 'comp-1';
    component.goodsReturn = mockReturn;
    component.outstandingLines = [outstandingLine];
    component.supplierName = 'Acme Corp';
    component.receivedCount = 1;
    fixture.detectChanges();
  });

  it('should create the completion modal component', () => {
    expect(component).toBeTruthy();
  });

  describe('Modal Rendering and Content Display', () => {
    it('renders return reference, supplier name, and counts accurately', () => {
      const compiled = fixture.nativeElement as HTMLElement;
      expect(compiled.textContent).toContain('GRR-20261108-0001');
      expect(compiled.textContent).toContain('Acme Corp');
      expect(compiled.textContent).toContain('Total Assets:');
      expect(compiled.textContent).toContain('Warehouse Received:');
      expect(compiled.textContent).toContain('Awaiting Vendor Acceptance:');
    });

    it('renders the list of outstanding assets and excludes warehouse-received assets', () => {
      const compiled = fixture.nativeElement as HTMLElement;
      expect(compiled.textContent).toContain('AST-2026-0002');
      expect(compiled.textContent).toContain('SN-ABC-2');
      expect(compiled.textContent).not.toContain('AST-2026-0001'); // received asset excluded
    });

    it('displays the lifecycle effects warning explaining terminal completion', () => {
      const compiled = fixture.nativeElement as HTMLElement;
      expect(compiled.textContent).toContain('Terminal Lifecycle Action');
      expect(compiled.textContent).toContain('return_pending');
      expect(compiled.textContent).toContain('returned_to_vendor');
      expect(compiled.textContent).toContain('fulfilled');
    });
  });

  describe('Validation and Submission Controls', () => {
    it('disables submission when confirmation checkbox is unchecked', () => {
      component.confirmed = false;
      expect(component.isFormValid).toBeFalse();

      component.onSubmit();
      expect(component.validationError).toContain('Please check the confirmation box');
      expect(mockGoodsReturnService.completeGoodsReturn).not.toHaveBeenCalled();
    });

    it('disables submission when there are no outstanding lines', () => {
      component.outstandingLines = [];
      component.confirmed = true;
      expect(component.isFormValid).toBeFalse();

      component.onSubmit();
      expect(component.validationError).toContain('No outstanding in-transit assets remain');
      expect(mockGoodsReturnService.completeGoodsReturn).not.toHaveBeenCalled();
    });

    it('enables submission when confirmed and outstanding lines exist, calling completeGoodsReturn with no payload', () => {
      const updatedReturn: GoodsReturn = { ...mockReturn, status: 'completed' };
      mockGoodsReturnService.completeGoodsReturn.and.returnValue(of(updatedReturn));
      spyOn(component.completed, 'emit');

      component.confirmed = true;
      expect(component.isFormValid).toBeTrue();

      component.onSubmit();

      expect(mockGoodsReturnService.completeGoodsReturn).toHaveBeenCalledWith('comp-1', 'grr-101');
      expect(component.submitting).toBeFalse();
      expect(component.completed.emit).toHaveBeenCalledWith(updatedReturn);
    });

    it('disables submit button and prevents duplicate calls while submitting', () => {
      mockGoodsReturnService.completeGoodsReturn.and.returnValue(of(mockReturn));

      component.confirmed = true;
      component.submitting = true;
      expect(component.isFormValid).toBeFalse();

      component.onSubmit();
      expect(mockGoodsReturnService.completeGoodsReturn).not.toHaveBeenCalled();
    });
  });

  describe('Error Handling and Conflict Recovery', () => {
    beforeEach(() => {
      component.confirmed = true;
    });

    it('handles HTTP 401 session expiration cleanly', () => {
      mockGoodsReturnService.completeGoodsReturn.and.returnValue(
        throwError(() => ({ status: 401, error: { detail: 'Unauthorized' } }))
      );

      component.onSubmit();

      expect(component.submitting).toBeFalse();
      expect(component.error).toContain('Authentication session expired');
      expect(component.confirmed).toBeTrue(); // preserved
    });

    it('handles HTTP 403 permission error', () => {
      mockGoodsReturnService.completeGoodsReturn.and.returnValue(
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
      expect(component.confirmed).toBeTrue();
    });

    it('handles HTTP 404 return not found, emits notFoundOccurred, and resets confirmation', () => {
      mockGoodsReturnService.completeGoodsReturn.and.returnValue(
        throwError(() => ({
          status: 404,
          error: { detail: 'Goods return not found' },
        }))
      );
      spyOn(component.notFoundOccurred, 'emit');
      spyOn(component.conflictOccurred, 'emit');

      component.onSubmit();

      expect(component.submitting).toBeFalse();
      expect(component.error).toContain('Goods return not found');
      expect(component.notFoundOccurred.emit).toHaveBeenCalled();
      expect(component.conflictOccurred.emit).not.toHaveBeenCalled();
      expect(component.confirmed).toBeFalse();
    });

    it('handles HTTP 409 conflict, displays backend message, emits conflictOccurred, and resets confirmation', () => {
      const conflictMsg =
        'All items in this return have already been received into the warehouse; cannot complete as vendor-accepted.';
      mockGoodsReturnService.completeGoodsReturn.and.returnValue(
        throwError(() => ({
          status: 409,
          error: { detail: conflictMsg },
        }))
      );
      spyOn(component.conflictOccurred, 'emit');
      spyOn(component.notFoundOccurred, 'emit');

      component.onSubmit();

      expect(component.submitting).toBeFalse();
      expect(component.error).toBe(conflictMsg);
      expect(component.conflictOccurred.emit).toHaveBeenCalled();
      expect(component.notFoundOccurred.emit).not.toHaveBeenCalled();
      expect(component.confirmed).toBeFalse();
    });

    it('handles generic 500 error safely without closing modal', () => {
      mockGoodsReturnService.completeGoodsReturn.and.returnValue(
        throwError(() => ({ status: 500, message: 'Database connection failed' }))
      );

      component.onSubmit();

      expect(component.submitting).toBeFalse();
      expect(component.error).toContain('Database connection failed');
      expect(component.confirmed).toBeTrue();
    });
  });

  describe('Keyboard and Dismissal Safeguards', () => {
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
