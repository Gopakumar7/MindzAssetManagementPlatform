import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { GoodsReturn, GoodsReturnService } from '../../../services/goods-return.service';
import { GoodsReturnCancelModalComponent } from './goods-return-cancel-modal.component';

describe('GoodsReturnCancelModalComponent', () => {
  let component: GoodsReturnCancelModalComponent;
  let fixture: ComponentFixture<GoodsReturnCancelModalComponent>;
  let mockGoodsReturnService: jasmine.SpyObj<GoodsReturnService>;

  const testReturn: GoodsReturn = {
    id: 'grr-201',
    company_id: 'comp-1',
    return_number: 'GRR-20261107-0002',
    supplier_id: 'sup-1',
    purchase_order_id: 'po-1',
    original_goods_receipt_id: 'rec-1',
    goods_receipt_reversal_id: 'rev-1',
    return_date: '2026-11-07',
    status: 'draft',
    return_reason: 'Return reason',
    vendor_reference: null,
    dispatch_reference: null,
    transport_details: null,
    notes: null,
    policy_strict_approval_applied: null,
    created_by_id: 'user-1',
    created_at: '2026-11-07T10:00:00Z',
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

  beforeEach(async () => {
    mockGoodsReturnService = jasmine.createSpyObj('GoodsReturnService', ['cancelGoodsReturn']);

    await TestBed.configureTestingModule({
      imports: [GoodsReturnCancelModalComponent],
      providers: [{ provide: GoodsReturnService, useValue: mockGoodsReturnService }],
    }).compileComponents();

    fixture = TestBed.createComponent(GoodsReturnCancelModalComponent);
    component = fixture.componentInstance;
    component.companyId = 'comp-1';
    component.goodsReturn = testReturn;
    fixture.detectChanges();
  });

  it('should initialize with invalid state requiring at least 3 chars reason', () => {
    expect(component).toBeTruthy();
    expect(component.isReasonValid).toBeFalse();
    expect(component.isFormValid).toBeFalse();
  });

  it('validates cancellation reason length correctly', () => {
    component.cancellationReason = '  ab  ';
    expect(component.isReasonValid).toBeFalse();

    component.cancellationReason = 'RMA cancelled by vendor';
    expect(component.isReasonValid).toBeTrue();
    expect(component.isFormValid).toBeTrue();
  });

  it('submits cancellation reason and emits cancelled event', () => {
    const updated = {
      ...testReturn,
      status: 'cancelled' as const,
      cancellation_reason: 'Vendor rejected RMA authorization',
    };
    mockGoodsReturnService.cancelGoodsReturn.and.returnValue(of(updated));
    spyOn(component.cancelled, 'emit');

    component.cancellationReason = 'Vendor rejected RMA authorization';
    component.onSubmit();

    expect(mockGoodsReturnService.cancelGoodsReturn).toHaveBeenCalledWith('comp-1', 'grr-201', {
      cancellation_reason: 'Vendor rejected RMA authorization',
    });
    expect(component.cancelled.emit).toHaveBeenCalledWith(updated);
    expect(component.submitting).toBeFalse();
  });

  it('handles HTTP 409 error without clearing entered reason', () => {
    mockGoodsReturnService.cancelGoodsReturn.and.returnValue(
      throwError(() => ({
        status: 409,
        error: { detail: "Goods return in status 'dispatched' cannot be cancelled" },
      }))
    );

    component.cancellationReason = 'Vendor rejected RMA authorization';
    component.onSubmit();

    expect(component.submitting).toBeFalse();
    expect(component.error).toBe("Goods return in status 'dispatched' cannot be cancelled");
    expect(component.cancellationReason).toBe('Vendor rejected RMA authorization');
  });

  it('emits close event when Keep Return is clicked', () => {
    spyOn(component.close, 'emit');
    component.onClose();
    expect(component.close.emit).toHaveBeenCalled();
  });

  it('dismisses modal on Escape key press when not submitting', () => {
    spyOn(component.close, 'emit');
    const event = new KeyboardEvent('keydown', { key: 'Escape' });
    spyOn(event, 'stopPropagation');
    component.onEscape(event);

    expect(event.stopPropagation).toHaveBeenCalled();
    expect(component.close.emit).toHaveBeenCalled();
  });

  it('ignores Escape key press when submission is actively in progress', () => {
    spyOn(component.close, 'emit');
    component.submitting = true;
    const event = new KeyboardEvent('keydown', { key: 'Escape' });
    component.onEscape(event);

    expect(component.close.emit).not.toHaveBeenCalled();
  });
});
