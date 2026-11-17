import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import {
  GoodsReceiptReversalRead,
  GoodsReturnService,
} from '../../../services/goods-return.service';
import { GoodsReceipt } from '../../../services/registry.service';
import { GoodsReceiptHistoryModalComponent } from './goods-receipt-history-modal.component';

describe('GoodsReceiptHistoryModalComponent', () => {
  let component: GoodsReceiptHistoryModalComponent;
  let fixture: ComponentFixture<GoodsReceiptHistoryModalComponent>;
  let mockGoodsReturnService: jasmine.SpyObj<GoodsReturnService>;

  const mockReceipt: GoodsReceipt = {
    id: 'receipt-uuid-1',
    company_id: 'company-uuid-1',
    purchase_order_id: 'po-uuid-1',
    receipt_number: 'GRN-20261107-001',
    received_date: '2026-11-07',
    delivery_reference: 'DEL-001',
    notes: null,
    status: 'partially_reversed',
    created_at: '2026-11-07T10:00:00Z',
    lines: [],
  };

  const mockReversals: GoodsReceiptReversalRead[] = [
    {
      id: 'rev-uuid-1',
      company_id: 'company-uuid-1',
      goods_receipt_id: 'receipt-uuid-1',
      purchase_order_id: 'po-uuid-1',
      reversal_reference: 'REV-20261107-0001',
      reversed_at: '2026-11-07T11:30:00Z',
      reversed_by_id: 'user-uuid-1',
      reason: 'Defective screen batch',
      created_at: '2026-11-07T11:30:00Z',
      lines: [
        {
          id: 'rev-line-1',
          company_id: 'company-uuid-1',
          reversal_id: 'rev-uuid-1',
          goods_receipt_line_id: 'grn-line-1',
          purchase_order_line_id: 'po-line-1',
          quantity_reversed: 2,
          notes: null,
          created_at: '2026-11-07T11:30:00Z',
          assets: [
            {
              id: 'rev-asset-1',
              company_id: 'company-uuid-1',
              reversal_id: 'rev-uuid-1',
              reversal_line_id: 'rev-line-1',
              goods_receipt_line_id: 'grn-line-1',
              asset_id: 'ast-1',
              asset_number: 'AST-001',
              serial_number: 'SN-001',
              created_at: '2026-11-07T11:30:00Z',
            },
          ],
        },
      ],
    },
  ];

  beforeEach(async () => {
    mockGoodsReturnService = jasmine.createSpyObj('GoodsReturnService', [
      'listGoodsReceiptReversals',
    ]);
    mockGoodsReturnService.listGoodsReceiptReversals.and.returnValue(of(mockReversals));

    await TestBed.configureTestingModule({
      imports: [GoodsReceiptHistoryModalComponent],
      providers: [
        { provide: GoodsReturnService, useValue: mockGoodsReturnService },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(GoodsReceiptHistoryModalComponent);
    component = fixture.componentInstance;
    component.companyId = 'company-uuid-1';
    component.receipt = mockReceipt;
    fixture.detectChanges();
  });

  it('should initialize and load reversal history', () => {
    expect(component).toBeTruthy();
    expect(mockGoodsReturnService.listGoodsReceiptReversals).toHaveBeenCalledWith(
      'company-uuid-1',
      'receipt-uuid-1'
    );
    expect(component.loading).toBeFalse();
    expect(component.reversals).toEqual(mockReversals);
  });

  it('should handle load error gracefully', () => {
    mockGoodsReturnService.listGoodsReceiptReversals.and.returnValue(
      throwError(() => new Error('Network error'))
    );
    component.loadHistory();
    expect(component.loading).toBeFalse();
    expect(component.error).toBe('Network error');
  });

  it('should emit close on onClose', () => {
    spyOn(component.close, 'emit');
    component.onClose();
    expect(component.close.emit).toHaveBeenCalled();
  });
});
