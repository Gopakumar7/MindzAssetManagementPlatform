import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { GoodsReturnService } from './goods-return.service';

describe('GoodsReturnService', () => {
  let service: GoodsReturnService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        GoodsReturnService,
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });
    service = TestBed.inject(GoodsReturnService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should request return eligible assets', () => {
    service.getReturnEligibleAssets('comp-1', 'rev-1').subscribe((res) => {
      expect(res).toEqual([]);
    });

    const req = httpMock.expectOne('/api/v1/companies/comp-1/goods-receipt-reversals/rev-1/return-eligible-assets');
    expect(req.request.method).toBe('GET');
    req.flush([]);
  });

  it('should request goods return creation', () => {
    const payload = {
      goods_receipt_reversal_id: 'rev-1',
      return_date: '2026-11-06',
      return_reason: 'Return reason',
      lines: [{ goods_receipt_reversal_asset_id: 'ra-1' }],
    };

    service.createGoodsReturn('comp-1', payload).subscribe((res) => {
      expect(res.return_number).toBe('GRR-00001');
    });

    const req = httpMock.expectOne('/api/v1/companies/comp-1/goods-returns');
    expect(req.request.method).toBe('POST');
    req.flush({ return_number: 'GRR-00001' });
  });

  it('should request goods receipt reversal check', () => {
    service.getGoodsReceiptReversalCheck('comp-1', 'rec-1').subscribe((res) => {
      expect(res.is_reversible).toBeTrue();
      expect(res.unreversed_accepted_quantity).toBe(2);
    });

    const req = httpMock.expectOne('/api/v1/companies/comp-1/goods-receipts/rec-1/reversal-check');
    expect(req.request.method).toBe('GET');
    req.flush({
      goods_receipt_id: 'rec-1',
      receipt_number: 'GRN-001',
      status: 'completed',
      is_reversible: true,
      total_accepted_quantity: 3,
      total_quantity_reversed: 1,
      unreversed_accepted_quantity: 2,
      lines: [],
      assets: [],
    });
  });

  it('should request goods receipt reversal execution', () => {
    const payload = {
      reason: 'Defective shipment batch',
      lines: [
        {
          goods_receipt_line_id: 'line-1',
          asset_ids: ['ast-1', 'ast-2'],
          notes: 'Defective screen',
        },
      ],
    };

    service.reverseGoodsReceipt('comp-1', 'rec-1', payload).subscribe((res) => {
      expect(res.reversal_reference).toBe('REV-001');
    });

    const req = httpMock.expectOne('/api/v1/companies/comp-1/goods-receipts/rec-1/reverse');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(payload);
    req.flush({
      id: 'rev-uuid-1',
      company_id: 'comp-1',
      goods_receipt_id: 'rec-1',
      purchase_order_id: 'po-1',
      reversal_reference: 'REV-001',
      reversed_at: '2026-11-07T12:00:00Z',
      reversed_by_id: 'user-1',
      reason: 'Defective shipment batch',
      created_at: '2026-11-07T12:00:00Z',
      lines: [],
    });
  });

  it('should request goods receipt historical reversals', () => {
    service.listGoodsReceiptReversals('comp-1', 'rec-1').subscribe((res) => {
      expect(res.length).toBe(1);
      expect(res[0].reversal_reference).toBe('REV-001');
    });

    const req = httpMock.expectOne('/api/v1/companies/comp-1/goods-receipts/rec-1/reversals');
    expect(req.request.method).toBe('GET');
    req.flush([
      {
        id: 'rev-uuid-1',
        company_id: 'comp-1',
        goods_receipt_id: 'rec-1',
        purchase_order_id: 'po-1',
        reversal_reference: 'REV-001',
        reversed_at: '2026-11-07T12:00:00Z',
        reversed_by_id: 'user-1',
        reason: 'Prior defect reversal',
        created_at: '2026-11-07T12:00:00Z',
        lines: [],
      },
    ]);
  });

  it('should request single goods return by ID', () => {
    service.getGoodsReturn('comp-1', 'grr-1').subscribe((res) => {
      expect(res.return_number).toBe('GRR-00001');
    });

    const req = httpMock.expectOne('/api/v1/companies/comp-1/goods-returns/grr-1');
    expect(req.request.method).toBe('GET');
    req.flush({ id: 'grr-1', return_number: 'GRR-00001', status: 'draft', lines: [] });
  });

  it('should request return line deselect (delete)', () => {
    service.deselectReturnLine('comp-1', 'grr-1', 'line-1').subscribe((res) => {
      expect(res.lines.length).toBe(0);
    });

    const req = httpMock.expectOne('/api/v1/companies/comp-1/goods-returns/grr-1/lines/line-1');
    expect(req.request.method).toBe('DELETE');
    req.flush({ id: 'grr-1', return_number: 'GRR-00001', status: 'draft', lines: [] });
  });

  it('should request goods return approval', () => {
    service.approveGoodsReturn('comp-1', 'grr-1').subscribe((res) => {
      expect(res.status).toBe('approved');
    });

    const req = httpMock.expectOne('/api/v1/companies/comp-1/goods-returns/grr-1/approve');
    expect(req.request.method).toBe('POST');
    req.flush({ id: 'grr-1', return_number: 'GRR-00001', status: 'approved' });
  });

  it('should request goods return dispatch', () => {
    const payload = { dispatch_reference: 'WB-12345', transport_details: 'Carrier X' };
    service.dispatchGoodsReturn('comp-1', 'grr-1', payload).subscribe((res) => {
      expect(res.status).toBe('dispatched');
      expect(res.dispatch_reference).toBe('WB-12345');
    });

    const req = httpMock.expectOne('/api/v1/companies/comp-1/goods-returns/grr-1/dispatch');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(payload);
    req.flush({ id: 'grr-1', return_number: 'GRR-00001', status: 'dispatched', dispatch_reference: 'WB-12345' });
  });

  it('should request goods return cancellation', () => {
    const payload = { cancellation_reason: 'RMA cancelled' };
    service.cancelGoodsReturn('comp-1', 'grr-1', payload).subscribe((res) => {
      expect(res.status).toBe('cancelled');
    });

    const req = httpMock.expectOne('/api/v1/companies/comp-1/goods-returns/grr-1/cancel');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(payload);
    req.flush({ id: 'grr-1', return_number: 'GRR-00001', status: 'cancelled' });
  });

  it('should request company settings', () => {
    service.getCompanySettings('comp-1').subscribe((res) => {
      expect(res['procurement_different_person_return_approval']).toBeTrue();
    });

    const req = httpMock.expectOne('/api/v1/companies/comp-1/settings');
    expect(req.request.method).toBe('GET');
    req.flush({ procurement_different_person_return_approval: true });
  });

  it('should request warehouse receipts list', () => {
    service.listWarehouseReceipts('comp-1', 'grr-1').subscribe((res) => {
      expect(res.length).toBe(1);
      expect(res[0].receipt_number).toBe('WR-GRR-00001-01');
    });

    const req = httpMock.expectOne('/api/v1/companies/comp-1/goods-returns/grr-1/warehouse-receipts');
    expect(req.request.method).toBe('GET');
    req.flush([
      {
        id: 'wr-1',
        company_id: 'comp-1',
        goods_return_id: 'grr-1',
        receipt_number: 'WR-GRR-00001-01',
        receipt_date: '2026-11-07',
        received_at: '2026-11-07T10:00:00Z',
        received_by_id: 'usr-1',
        warehouse_location_id: null,
        dispatch_reference: 'WB-123',
        reason: 'Carrier delivery returned to warehouse',
        notes: null,
        created_at: '2026-11-07T10:00:00Z',
        lines: [],
      },
    ]);
  });

  it('should request warehouse receipt creation', () => {
    const payload = {
      receipt_date: '2026-11-07',
      reason: 'Physical return',
      lines: [{ goods_return_line_id: 'line-1', condition_on_return: 'intact' }],
    };

    service.createWarehouseReceipt('comp-1', 'grr-1', payload).subscribe((res) => {
      expect(res.receipt_number).toBe('WR-GRR-00001-01');
    });

    const req = httpMock.expectOne('/api/v1/companies/comp-1/goods-returns/grr-1/warehouse-receipts');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(payload);
    req.flush({
      id: 'wr-1',
      receipt_number: 'WR-GRR-00001-01',
      lines: [],
    });
  });

  it('should request warehouse receipt line correction with optional notes', () => {
    const payload = {
      correction_reason: 'Clerical mistake: item was not received',
      notes: 'Supervisor verified',
    };

    service.correctWarehouseReceiptLine('comp-1', 'grr-1', 'wr-1', 'wrl-1', payload).subscribe((res) => {
      expect(res.receipt_number).toBe('WR-GRR-00001-01');
    });

    const req = httpMock.expectOne('/api/v1/companies/comp-1/goods-returns/grr-1/warehouse-receipts/wr-1/lines/wrl-1/correct');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(payload);
    req.flush({
      id: 'wr-1',
      receipt_number: 'WR-GRR-00001-01',
      lines: [{ id: 'wrl-1', is_corrected: true, correction_reason: payload.correction_reason }],
    });
  });

  it('should request goods return completion with empty body', () => {
    service.completeGoodsReturn('comp-1', 'grr-1').subscribe((res) => {
      expect(res.status).toBe('completed');
    });

    const req = httpMock.expectOne('/api/v1/companies/comp-1/goods-returns/grr-1/complete');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({});
    req.flush({ id: 'grr-1', return_number: 'GRR-00001', status: 'completed' });
  });
});
