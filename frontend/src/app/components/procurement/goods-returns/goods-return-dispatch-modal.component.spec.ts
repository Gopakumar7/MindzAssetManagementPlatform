import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { GoodsReturn, GoodsReturnService } from '../../../services/goods-return.service';
import { GoodsReturnDispatchModalComponent } from './goods-return-dispatch-modal.component';

describe('GoodsReturnDispatchModalComponent', () => {
  let component: GoodsReturnDispatchModalComponent;
  let fixture: ComponentFixture<GoodsReturnDispatchModalComponent>;
  let mockGoodsReturnService: jasmine.SpyObj<GoodsReturnService>;

  const testReturn: GoodsReturn = {
    id: 'grr-101',
    company_id: 'comp-1',
    return_number: 'GRR-20261107-0001',
    supplier_id: 'sup-1',
    purchase_order_id: 'po-1',
    original_goods_receipt_id: 'rec-1',
    goods_receipt_reversal_id: 'rev-1',
    return_date: '2026-11-07',
    status: 'approved',
    return_reason: 'Defective batch',
    vendor_reference: 'RMA-999',
    dispatch_reference: null,
    transport_details: null,
    notes: null,
    policy_strict_approval_applied: true,
    created_by_id: 'user-1',
    created_at: '2026-11-07T10:00:00Z',
    approved_by_id: 'user-2',
    approved_at: '2026-11-07T11:00:00Z',
    dispatched_by_id: null,
    dispatched_at: null,
    completed_by_id: null,
    completed_at: null,
    cancelled_by_id: null,
    cancelled_at: null,
    cancellation_reason: null,
    lines: [
      {
        id: 'line-1',
        company_id: 'comp-1',
        goods_return_id: 'grr-101',
        goods_receipt_reversal_id: 'rev-1',
        goods_receipt_reversal_asset_id: 'ra-1',
        goods_receipt_reversal_line_id: 'rl-1',
        goods_receipt_line_id: 'gl-1',
        asset_id: 'ast-1',
        asset_number: 'AST-0001',
        serial_number: 'SN-001',
        return_condition: 'as_received',
        notes: null,
        created_at: '2026-11-07T10:00:00Z',
      },
    ],
  };

  beforeEach(async () => {
    mockGoodsReturnService = jasmine.createSpyObj('GoodsReturnService', ['dispatchGoodsReturn']);

    await TestBed.configureTestingModule({
      imports: [GoodsReturnDispatchModalComponent],
      providers: [{ provide: GoodsReturnService, useValue: mockGoodsReturnService }],
    }).compileComponents();

    fixture = TestBed.createComponent(GoodsReturnDispatchModalComponent);
    component = fixture.componentInstance;
    component.companyId = 'comp-1';
    component.goodsReturn = testReturn;
    fixture.detectChanges();
  });

  it('should initialize with correct asset count and invalid form state', () => {
    expect(component).toBeTruthy();
    expect(component.assetCount).toBe(1);
    expect(component.isFormValid).toBeFalse();
  });

  it('validates form: requires dispatch_reference and confirmation checkbox', () => {
    component.dispatchReference = '   ';
    component.confirmed = true;
    expect(component.isFormValid).toBeFalse();

    component.dispatchReference = 'WAYBILL-123';
    component.confirmed = false;
    expect(component.isFormValid).toBeFalse();

    component.confirmed = true;
    expect(component.isFormValid).toBeTrue();
  });

  it('submits valid dispatch payload and emits dispatched event on success', () => {
    const updated = { ...testReturn, status: 'dispatched' as const, dispatch_reference: 'WAYBILL-123' };
    mockGoodsReturnService.dispatchGoodsReturn.and.returnValue(of(updated));
    spyOn(component.dispatched, 'emit');

    component.dispatchReference = 'WAYBILL-123';
    component.transportDetails = 'DHL Air Express';
    component.notes = 'Signed at warehouse gate';
    component.confirmed = true;

    component.onSubmit();

    expect(mockGoodsReturnService.dispatchGoodsReturn).toHaveBeenCalledWith('comp-1', 'grr-101', {
      dispatch_reference: 'WAYBILL-123',
      transport_details: 'DHL Air Express',
      notes: 'Signed at warehouse gate',
    });
    expect(component.dispatched.emit).toHaveBeenCalledWith(updated);
    expect(component.submitting).toBeFalse();
  });

  it('handles HTTP 409 conflict and preserves user inputs', () => {
    mockGoodsReturnService.dispatchGoodsReturn.and.returnValue(
      throwError(() => ({ status: 409, error: { detail: "Goods return in status 'cancelled' cannot be dispatched" } }))
    );

    component.dispatchReference = 'WAYBILL-123';
    component.confirmed = true;
    component.onSubmit();

    expect(component.submitting).toBeFalse();
    expect(component.error).toBe("Goods return in status 'cancelled' cannot be dispatched");
    expect(component.dispatchReference).toBe('WAYBILL-123');
    expect(component.confirmed).toBeTrue();
  });

  it('handles HTTP 403 authorization error', () => {
    mockGoodsReturnService.dispatchGoodsReturn.and.returnValue(
      throwError(() => ({ status: 403, error: { detail: 'Missing required permission procurement.manage' } }))
    );

    component.dispatchReference = 'WAYBILL-123';
    component.confirmed = true;
    component.onSubmit();

    expect(component.submitting).toBeFalse();
    expect(component.error).toBe('Missing required permission procurement.manage');
  });

  it('emits close event when cancel button is clicked', () => {
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
