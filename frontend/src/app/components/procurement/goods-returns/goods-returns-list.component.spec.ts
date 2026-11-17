import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { GoodsReturn, GoodsReturnService } from '../../../services/goods-return.service';
import { GoodsReturnsListComponent } from './goods-returns-list.component';

describe('GoodsReturnsListComponent', () => {
  let component: GoodsReturnsListComponent;
  let fixture: ComponentFixture<GoodsReturnsListComponent>;
  let mockGoodsReturnService: jasmine.SpyObj<GoodsReturnService>;

  const mockReturns: GoodsReturn[] = [
    {
      id: 'grr-1',
      company_id: 'comp-1',
      return_number: 'GRR-20261107-0001',
      supplier_id: 'sup-1',
      purchase_order_id: 'po-1',
      original_goods_receipt_id: 'grn-1',
      goods_receipt_reversal_id: 'rev-1',
      return_date: '2026-11-07',
      status: 'draft',
      return_reason: 'Defective screen batch RMA-101',
      vendor_reference: 'RMA-101',
      dispatch_reference: null,
      transport_details: null,
      notes: 'Urgent replacement requested',
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
      lines: [
        {
          id: 'line-1',
          company_id: 'comp-1',
          goods_return_id: 'grr-1',
          goods_receipt_reversal_id: 'rev-1',
          goods_receipt_reversal_asset_id: 'ra-1',
          goods_receipt_reversal_line_id: 'rl-1',
          goods_receipt_line_id: 'gl-1',
          asset_id: 'ast-1',
          asset_number: 'AST-001',
          serial_number: 'SN-001',
          return_condition: 'as_received',
          notes: null,
          created_at: '2026-11-07T12:00:00Z',
        },
      ],
    },
    {
      id: 'grr-2',
      company_id: 'comp-1',
      return_number: 'GRR-20261107-0002',
      supplier_id: 'sup-2',
      purchase_order_id: 'po-2',
      original_goods_receipt_id: 'grn-2',
      goods_receipt_reversal_id: 'rev-2',
      return_date: '2026-11-06',
      status: 'completed',
      return_reason: 'Incorrect model delivered',
      vendor_reference: 'RMA-999',
      dispatch_reference: 'DISP-202',
      transport_details: 'DHL Express',
      notes: null,
      policy_strict_approval_applied: false,
      created_by_id: 'user-2',
      created_at: '2026-11-06T10:00:00Z',
      approved_by_id: 'user-1',
      approved_at: '2026-11-06T11:00:00Z',
      dispatched_by_id: 'user-1',
      dispatched_at: '2026-11-06T13:00:00Z',
      completed_by_id: 'user-1',
      completed_at: '2026-11-06T16:00:00Z',
      cancelled_by_id: null,
      cancelled_at: null,
      cancellation_reason: null,
      lines: [],
    },
  ];

  beforeEach(async () => {
    mockGoodsReturnService = jasmine.createSpyObj('GoodsReturnService', ['listGoodsReturns']);
    mockGoodsReturnService.listGoodsReturns.and.returnValue(of(mockReturns));

    await TestBed.configureTestingModule({
      imports: [GoodsReturnsListComponent],
      providers: [
        { provide: GoodsReturnService, useValue: mockGoodsReturnService },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(GoodsReturnsListComponent);
    component = fixture.componentInstance;
    component.companyId = 'comp-1';
    component.canRead = true;
    component.canManage = true;
    component.suppliers = [
      { id: 'sup-1', company_id: 'comp-1', code: 'SUP01', name: 'Acme Hardware', email: null, phone: null, notes: null, is_active: true, created_at: '2026-11-01T10:00:00Z' },
      { id: 'sup-2', company_id: 'comp-1', code: 'SUP02', name: 'Global Tech', email: null, phone: null, notes: null, is_active: true, created_at: '2026-11-01T10:00:00Z' },
    ];
    component.purchaseOrders = [
      {
        id: 'po-1',
        company_id: 'comp-1',
        supplier_id: 'sup-1',
        order_number: 'PO-2026-001',
        ordered_date: '2026-11-01',
        expected_date: null,
        status: 'received',
        notes: null,
        created_at: '2026-11-01T10:00:00Z',
        lines: [],
      },
    ];
    fixture.detectChanges();
  });

  it('should initialize and load Goods Returns for the company', () => {
    expect(component).toBeTruthy();
    expect(mockGoodsReturnService.listGoodsReturns).toHaveBeenCalledWith('comp-1', {});
    expect(component.returns.length).toBe(2);
    expect(component.totalCount).toBe(2);
    expect(component.draftCount).toBe(1);
    expect(component.completedCount).toBe(1);
  });

  it('should handle empty returns response', () => {
    mockGoodsReturnService.listGoodsReturns.and.returnValue(of([]));
    component.loadReturns();
    expect(component.returns.length).toBe(0);
    expect(component.filteredReturns.length).toBe(0);
    expect(component.totalCount).toBe(0);
  });

  it('should handle API load error gracefully', () => {
    mockGoodsReturnService.listGoodsReturns.and.returnValue(
      throwError(() => ({ error: { detail: 'Database connection failed' } }))
    );
    component.loadReturns();
    expect(component.loading).toBeFalse();
    expect(component.error).toBe('Database connection failed');
  });

  it('should filter returns by search term', () => {
    component.searchTerm = 'RMA-101';
    expect(component.filteredReturns.length).toBe(1);
    expect(component.filteredReturns[0].return_number).toBe('GRR-20261107-0001');

    component.searchTerm = 'Global Tech';
    expect(component.filteredReturns.length).toBe(1);
    expect(component.filteredReturns[0].return_number).toBe('GRR-20261107-0002');

    component.searchTerm = 'NonExistent';
    expect(component.filteredReturns.length).toBe(0);
  });

  it('should support filtering across all seven canonical lifecycle states', () => {
    const states: ('draft' | 'approved' | 'dispatched' | 'partially_returned_to_warehouse' | 'returned_to_warehouse' | 'completed' | 'cancelled')[] = [
      'draft',
      'approved',
      'dispatched',
      'partially_returned_to_warehouse',
      'returned_to_warehouse',
      'completed',
      'cancelled',
    ];

    for (const status of states) {
      component.onStatusFilterChange(status);
      expect(mockGoodsReturnService.listGoodsReturns).toHaveBeenCalledWith('comp-1', { status });
    }

    component.onStatusFilterChange('all');
    expect(mockGoodsReturnService.listGoodsReturns).toHaveBeenCalledWith('comp-1', {});
  });

  it('should reload when companyId input changes', () => {
    mockGoodsReturnService.listGoodsReturns.calls.reset();
    component.companyId = 'comp-2';
    component.ngOnChanges({
      companyId: {
        currentValue: 'comp-2',
        previousValue: 'comp-1',
        firstChange: false,
        isFirstChange: () => false,
      },
    });
    expect(mockGoodsReturnService.listGoodsReturns).toHaveBeenCalledWith('comp-2', {});
  });

  it('should respect permission-based visibility: suppress listing when canRead is false', () => {
    mockGoodsReturnService.listGoodsReturns.calls.reset();
    component.canRead = false;
    component.loadReturns();
    expect(mockGoodsReturnService.listGoodsReturns).not.toHaveBeenCalled();
  });

  it('should emit createReturn when create button is clicked', () => {
    spyOn(component.createReturn, 'emit');
    component.onCreateReturn();
    expect(component.createReturn.emit).toHaveBeenCalled();
  });

  it('should emit selectReturn when a return item is chosen', () => {
    spyOn(component.selectReturn, 'emit');
    component.onSelectReturn(mockReturns[0]);
    expect(component.selectReturn.emit).toHaveBeenCalledWith(mockReturns[0]);
  });
});
