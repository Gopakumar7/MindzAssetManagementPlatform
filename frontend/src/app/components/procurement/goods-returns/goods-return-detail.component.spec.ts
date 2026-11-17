import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';

import {
  GoodsReturn,
  GoodsReturnService,
  GoodsReturnWarehouseReceipt,
} from '../../../services/goods-return.service';
import { GoodsReturnDetailComponent } from './goods-return-detail.component';

describe('GoodsReturnDetailComponent', () => {
  let component: GoodsReturnDetailComponent;
  let fixture: ComponentFixture<GoodsReturnDetailComponent>;
  let mockGoodsReturnService: jasmine.SpyObj<GoodsReturnService>;

  const baseDraftReturn: GoodsReturn = {
    id: 'grr-1',
    company_id: 'comp-1',
    return_number: 'GRR-20261107-0001',
    supplier_id: 'sup-1',
    purchase_order_id: 'po-1',
    original_goods_receipt_id: 'rec-1',
    goods_receipt_reversal_id: 'rev-1',
    return_date: '2026-11-07',
    status: 'draft',
    return_reason: 'RMA Defective Batch',
    vendor_reference: 'RMA-VENDOR-100',
    dispatch_reference: null,
    transport_details: null,
    notes: 'Urgent replacement requested',
    policy_strict_approval_applied: null,
    created_by_id: 'user-creator',
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
        asset_number: 'AST-0001',
        serial_number: 'SN-0001',
        return_condition: 'damaged',
        notes: 'Chacked chassis',
        created_at: '2026-11-07T10:00:00Z',
      },
      {
        id: 'line-2',
        company_id: 'comp-1',
        goods_return_id: 'grr-1',
        goods_receipt_reversal_id: 'rev-1',
        goods_receipt_reversal_asset_id: 'ra-2',
        goods_receipt_reversal_line_id: 'rl-1',
        goods_receipt_line_id: 'gl-1',
        asset_id: 'ast-2',
        asset_number: 'AST-0002',
        serial_number: 'SN-0002',
        return_condition: 'as_received',
        notes: null,
        created_at: '2026-11-07T10:00:00Z',
      },
    ],
  };

  beforeEach(async () => {
    mockGoodsReturnService = jasmine.createSpyObj('GoodsReturnService', [
      'getGoodsReturn',
      'getCompanySettings',
      'deselectReturnLine',
      'approveGoodsReturn',
      'dispatchGoodsReturn',
      'cancelGoodsReturn',
      'listWarehouseReceipts',
    ]);

    mockGoodsReturnService.getGoodsReturn.and.returnValue(of(baseDraftReturn));
    mockGoodsReturnService.listWarehouseReceipts.and.returnValue(of([]));
    mockGoodsReturnService.getCompanySettings.and.returnValue(
      of({ procurement_different_person_return_approval: true })
    );

    await TestBed.configureTestingModule({
      imports: [GoodsReturnDetailComponent],
      providers: [{ provide: GoodsReturnService, useValue: mockGoodsReturnService }],
    }).compileComponents();

    fixture = TestBed.createComponent(GoodsReturnDetailComponent);
    component = fixture.componentInstance;
    component.companyId = 'comp-1';
    component.returnId = 'grr-1';
    component.canRead = true;
    component.canManage = true;
    component.currentUserId = 'user-other';
    component.suppliers = [
      {
        id: 'sup-1',
        company_id: 'comp-1',
        code: 'SUP01',
        name: 'Alpha Hardware',
        email: null,
        phone: null,
        notes: null,
        is_active: true,
        created_at: '2026-11-01T10:00:00Z',
      },
    ];
    component.purchaseOrders = [
      {
        id: 'po-1',
        company_id: 'comp-1',
        supplier_id: 'sup-1',
        order_number: 'PO-2026-0001',
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

  it('loads and displays return details, supplier, and PO lineage', () => {
    expect(component).toBeTruthy();
    expect(mockGoodsReturnService.getGoodsReturn).toHaveBeenCalledWith('comp-1', 'grr-1');
    expect(component.goodsReturn?.return_number).toBe('GRR-20261107-0001');
    expect(component.supplierName('sup-1')).toContain('Alpha Hardware');
    expect(component.purchaseOrderNumber('po-1')).toBe('PO-2026-0001');
    expect(component.goodsReturn?.lines.length).toBe(2);
  });

  it('handles loading error gracefully', () => {
    mockGoodsReturnService.getGoodsReturn.and.returnValue(
      throwError(() => ({ status: 404, error: { detail: 'Goods return not found' } }))
    );

    component.loadReturn();
    expect(component.loading).toBeFalse();
    expect(component.error).toBe('Goods return not found');
  });

  it('renders all 7 canonical states correctly in the DOM lifecycle stepper', () => {
    const states: ('draft' | 'approved' | 'dispatched' | 'partially_returned_to_warehouse' | 'returned_to_warehouse' | 'completed' | 'cancelled')[] = [
      'draft',
      'approved',
      'dispatched',
      'partially_returned_to_warehouse',
      'returned_to_warehouse',
      'completed',
      'cancelled',
    ];

    for (const st of states) {
      component.goodsReturn = {
        ...baseDraftReturn,
        status: st,
        approved_at: st !== 'draft' ? '2026-11-07T11:00:00Z' : null,
        approved_by_id: st !== 'draft' ? 'user-approver' : null,
        dispatched_at: !['draft', 'approved'].includes(st) ? '2026-11-07T12:00:00Z' : null,
        dispatched_by_id: !['draft', 'approved'].includes(st) ? 'user-dispatcher' : null,
        completed_at: st === 'completed' ? '2026-11-07T16:00:00Z' : null,
        completed_by_id: st === 'completed' ? 'user-completer' : null,
        cancelled_at: st === 'cancelled' ? '2026-11-07T14:00:00Z' : null,
        cancelled_by_id: st === 'cancelled' ? 'user-canceller' : null,
        cancellation_reason: st === 'cancelled' ? 'Vendor RMA revoked' : null,
      };
      component['changeDetector'].markForCheck();
      fixture.detectChanges();

      const compiled = fixture.nativeElement as HTMLElement;
      const stepElem = compiled.querySelector(`[data-step="${st}"]`);
      expect(stepElem).withContext(`Step element for status '${st}' must exist in DOM`).toBeTruthy();
      expect(stepElem?.classList.contains('step-current')).withContext(`Step element for status '${st}' must have .step-current`).toBeTrue();

      // Check lifecycleSteps property length reflects all 7 canonical states
      expect(component.lifecycleSteps.length).toBe(7);
    }
  });

  it('FIND-01 regression: direct vendor completion does not falsely mark warehouse steps completed in DOM', () => {
    component.goodsReturn = {
      ...baseDraftReturn,
      status: 'completed',
      approved_at: '2026-11-07T11:00:00Z',
      approved_by_id: 'user-approver',
      dispatched_at: '2026-11-07T12:00:00Z',
      dispatched_by_id: 'user-dispatcher',
      completed_at: '2026-11-07T16:00:00Z',
      completed_by_id: 'user-vendor-ack',
    };
    component['changeDetector'].markForCheck();
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;

    // Completed step must be current and completed
    const completedStep = compiled.querySelector('[data-step="completed"]');
    expect(completedStep?.classList.contains('step-current')).toBeTrue();
    expect(completedStep?.classList.contains('step-completed')).toBeTrue();

    // Initiation steps must be completed
    const draftStep = compiled.querySelector('[data-step="draft"]');
    const approvedStep = compiled.querySelector('[data-step="approved"]');
    const dispatchedStep = compiled.querySelector('[data-step="dispatched"]');
    expect(draftStep?.classList.contains('step-completed')).toBeTrue();
    expect(approvedStep?.classList.contains('step-completed')).toBeTrue();
    expect(dispatchedStep?.classList.contains('step-completed')).toBeTrue();

    // Critical assertion: Warehouse intake steps must NOT be marked completed!
    const partialWhStep = compiled.querySelector('[data-step="partially_returned_to_warehouse"]');
    const returnedWhStep = compiled.querySelector('[data-step="returned_to_warehouse"]');
    expect(partialWhStep?.classList.contains('step-completed')).toBeFalse();
    expect(returnedWhStep?.classList.contains('step-completed')).toBeFalse();
    expect(partialWhStep?.classList.contains('step-current')).toBeFalse();
    expect(returnedWhStep?.classList.contains('step-current')).toBeFalse();

    // Terminal completed banner
    expect(compiled.querySelector('.terminal-completed')).toBeTruthy();
  });

  it('FIND-01 regression: returned_to_warehouse is terminal physical outcome and does not progress to completed', () => {
    component.goodsReturn = {
      ...baseDraftReturn,
      status: 'returned_to_warehouse',
      approved_at: '2026-11-07T11:00:00Z',
      approved_by_id: 'user-approver',
      dispatched_at: '2026-11-07T12:00:00Z',
      dispatched_by_id: 'user-dispatcher',
    };
    component['changeDetector'].markForCheck();
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;

    // returned_to_warehouse step is current
    const returnedWhStep = compiled.querySelector('[data-step="returned_to_warehouse"]');
    expect(returnedWhStep?.classList.contains('step-current')).toBeTrue();

    // completed step must NOT be current nor completed
    const completedStep = compiled.querySelector('[data-step="completed"]');
    expect(completedStep?.classList.contains('step-current')).toBeFalse();
    expect(completedStep?.classList.contains('step-completed')).toBeFalse();

    // Terminal warehouse intake banner must be rendered explaining physical fulfillment
    const whBanner = compiled.querySelector('.terminal-warehouse-intake');
    expect(whBanner).toBeTruthy();
    expect(whBanner?.textContent).toContain('Terminal Physical Outcome: Returned to Warehouse');
    expect(whBanner?.textContent).toContain('cannot transition to vendor completed');
  });

  it('FIND-01 regression: correction-driven state changes do not render fictitious milestones in DOM', () => {
    // Return corrected back to partially_returned_to_warehouse
    component.goodsReturn = {
      ...baseDraftReturn,
      status: 'partially_returned_to_warehouse',
      approved_at: '2026-11-07T11:00:00Z',
      approved_by_id: 'user-approver',
      dispatched_at: '2026-11-07T12:00:00Z',
      dispatched_by_id: 'user-dispatcher',
    };
    component['changeDetector'].markForCheck();
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    const partialWh = compiled.querySelector('[data-step="partially_returned_to_warehouse"]');
    const returnedWh = compiled.querySelector('[data-step="returned_to_warehouse"]');
    const completedStep = compiled.querySelector('[data-step="completed"]');

    expect(partialWh?.classList.contains('step-current')).toBeTrue();
    expect(returnedWh?.classList.contains('step-current')).toBeFalse();
    expect(returnedWh?.classList.contains('step-completed')).toBeFalse();
    expect(completedStep?.classList.contains('step-current')).toBeFalse();
    expect(completedStep?.classList.contains('step-completed')).toBeFalse();

    // Return corrected all the way back to dispatched
    component.goodsReturn = {
      ...component.goodsReturn,
      status: 'dispatched',
    };
    component['changeDetector'].markForCheck();
    fixture.detectChanges();

    const dispatchedStep = compiled.querySelector('[data-step="dispatched"]');
    expect(dispatchedStep?.classList.contains('step-current')).toBeTrue();
    expect(compiled.querySelector('[data-step="partially_returned_to_warehouse"]')?.classList.contains('step-current')).toBeFalse();
    expect(compiled.querySelector('[data-step="partially_returned_to_warehouse"]')?.classList.contains('step-completed')).toBeFalse();
    expect(compiled.querySelector('[data-step="returned_to_warehouse"]')?.classList.contains('step-current')).toBeFalse();
    expect(compiled.querySelector('[data-step="returned_to_warehouse"]')?.classList.contains('step-completed')).toBeFalse();
  });

  it('displays distinct terminal outcomes for completed and cancelled', () => {
    // Completed terminal state
    component.goodsReturn = {
      ...baseDraftReturn,
      status: 'completed',
      completed_at: '2026-11-07T16:00:00Z',
      completed_by_id: 'user-wh',
    };
    component['changeDetector'].markForCheck();
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.terminal-completed')).toBeTruthy();
    expect(compiled.textContent).toContain('Terminal Outcome: Return Completed');

    // Cancelled terminal state
    component.goodsReturn = {
      ...baseDraftReturn,
      status: 'cancelled',
      cancelled_at: '2026-11-07T12:00:00Z',
      cancelled_by_id: 'user-admin',
      cancellation_reason: 'RMA cancelled by vendor',
    };
    component['changeDetector'].markForCheck();
    fixture.detectChanges();
    expect(compiled.querySelector('.terminal-cancelled')).toBeTruthy();
    expect(compiled.textContent).toContain('Terminal Outcome: Return Cancelled');
    expect(compiled.textContent).toContain('RMA cancelled by vendor');
  });

  // --- Section B: Line Removal ---
  it('allows line removal in draft state with confirmation and refreshes return', () => {
    const updatedReturn: GoodsReturn = {
      ...baseDraftReturn,
      lines: [baseDraftReturn.lines[1]], // only line-2 remains
    };
    mockGoodsReturnService.deselectReturnLine.and.returnValue(of(updatedReturn));
    spyOn(component.returnUpdated, 'emit');

    component.promptRemoveLine('line-1');
    expect(component.confirmLineRemovalId).toBe('line-1');

    component.executeRemoveLine('line-1');
    expect(mockGoodsReturnService.deselectReturnLine).toHaveBeenCalledWith('comp-1', 'grr-1', 'line-1');
    expect(component.goodsReturn?.lines.length).toBe(1);
    expect(component.actionMessage).toContain('Line removed');
    expect(component.returnUpdated.emit).toHaveBeenCalledWith(updatedReturn);
  });

  it('cancels line removal prompt without executing delete', () => {
    component.promptRemoveLine('line-1');
    expect(component.confirmLineRemovalId).toBe('line-1');

    component.cancelRemoveLine();
    expect(component.confirmLineRemovalId).toBeNull();
    expect(mockGoodsReturnService.deselectReturnLine).not.toHaveBeenCalled();
  });

  it('handles HTTP 409 conflict during line removal and refreshes server state', () => {
    mockGoodsReturnService.deselectReturnLine.and.returnValue(
      throwError(() => ({ status: 409, error: { detail: "Cannot remove line from return in status 'approved'" } }))
    );
    spyOn(component, 'loadReturn');

    component.executeRemoveLine('line-1');
    expect(component.actionError).toContain("Cannot remove line from return in status 'approved'");
    expect(component.loadReturn).toHaveBeenCalled();
  });

  it('disallows line removal when return is not in draft status', () => {
    component.goodsReturn = { ...baseDraftReturn, status: 'approved' };
    expect(component.canRemoveLines).toBeFalse();
    component.promptRemoveLine('line-1');
    expect(component.confirmLineRemovalId).toBeNull();
  });

  // --- Section C: Approval & Segregation of Duties ---
  it('enables approval for eligible different-person user and handles successful approval', () => {
    component.currentUserId = 'user-different';
    component.policyStrictApproval = true;
    expect(component.isCreator).toBeFalse();
    expect(component.isSelfApprovalBlocked).toBeFalse();
    expect(component.canApprove).toBeTrue();

    const approvedReturn: GoodsReturn = {
      ...baseDraftReturn,
      status: 'approved',
      approved_by_id: 'user-different',
      approved_at: '2026-11-07T11:00:00Z',
    };
    mockGoodsReturnService.approveGoodsReturn.and.returnValue(of(approvedReturn));
    spyOn(component.returnUpdated, 'emit');

    component.onApprove();
    expect(mockGoodsReturnService.approveGoodsReturn).toHaveBeenCalledWith('comp-1', 'grr-1');
    expect(component.goodsReturn?.status).toBe('approved');
    expect(component.actionMessage).toContain('approved successfully');
    expect(component.returnUpdated.emit).toHaveBeenCalledWith(approvedReturn);
  });

  it('proactively blocks approval when user is creator and segregation-of-duties policy is strict', () => {
    component.currentUserId = 'user-creator';
    component.policyStrictApproval = true;

    expect(component.isCreator).toBeTrue();
    expect(component.isSelfApprovalBlocked).toBeTrue();
    expect(component.canApprove).toBeFalse();

    component['changeDetector'].markForCheck();
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.sod-blocked')).toBeTruthy();
    expect(compiled.textContent).toContain('Self-Approval Prohibited');
  });

  it('allows creator approval when segregation-of-duties policy is overridden (permissive)', () => {
    component.currentUserId = 'user-creator';
    component.policyStrictApproval = false;

    expect(component.isCreator).toBeTrue();
    expect(component.isSelfApprovalBlocked).toBeFalse();
    expect(component.canApprove).toBeTrue();

    component['changeDetector'].markForCheck();
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.sod-warning')).toBeTruthy();
    expect(compiled.textContent).toContain('Policy Override Active');
  });

  it('handles backend HTTP 403 segregation of duties error', () => {
    component.currentUserId = 'user-different';
    mockGoodsReturnService.approveGoodsReturn.and.returnValue(
      throwError(() => ({
        status: 403,
        error: { detail: 'Segregation of duties violation: Return approver must be different from the creator.' },
      }))
    );

    component.onApprove();
    expect(component.approving).toBeFalse();
    expect(component.actionError).toContain('Segregation of duties violation');
  });

  it('handles backend HTTP 409 conflict on approval and refreshes return', () => {
    component.currentUserId = 'user-different';
    mockGoodsReturnService.approveGoodsReturn.and.returnValue(
      throwError(() => ({
        status: 409,
        error: { detail: "Goods return in status 'cancelled' cannot be approved" },
      }))
    );
    spyOn(component, 'loadReturn');

    component.onApprove();
    expect(component.approving).toBeFalse();
    expect(component.actionError).toContain('Goods return in status');
    expect(component.loadReturn).toHaveBeenCalled();
  });

  // --- Section D: Dispatch & Cancellation Modals ---
  it('opens dispatch modal strictly when in approved state', () => {
    component.goodsReturn = { ...baseDraftReturn, status: 'draft' };
    expect(component.canDispatch).toBeFalse();
    component.openDispatchModal();
    expect(component.showDispatchModal).toBeFalse();

    component.goodsReturn = { ...baseDraftReturn, status: 'approved' };
    expect(component.canDispatch).toBeTrue();
    component.openDispatchModal();
    expect(component.showDispatchModal).toBeTrue();
  });

  it('handles dispatch completion', () => {
    const dispatchedReturn: GoodsReturn = {
      ...baseDraftReturn,
      status: 'dispatched',
      dispatch_reference: 'WB-999',
    };
    spyOn(component.returnUpdated, 'emit');

    component.onDispatched(dispatchedReturn);
    expect(component.showDispatchModal).toBeFalse();
    expect(component.goodsReturn?.status).toBe('dispatched');
    expect(component.actionMessage).toContain('WB-999');
    expect(component.returnUpdated.emit).toHaveBeenCalledWith(dispatchedReturn);
  });

  it('allows cancellation in draft or approved state, but blocks in dispatched state', () => {
    component.goodsReturn = { ...baseDraftReturn, status: 'draft' };
    expect(component.canCancel).toBeTrue();

    component.goodsReturn = { ...baseDraftReturn, status: 'approved' };
    expect(component.canCancel).toBeTrue();

    component.goodsReturn = { ...baseDraftReturn, status: 'dispatched' };
    expect(component.canCancel).toBeFalse();
  });

  it('handles cancellation completion', () => {
    const cancelledReturn: GoodsReturn = {
      ...baseDraftReturn,
      status: 'cancelled',
      cancellation_reason: 'Defect resolved locally',
    };
    spyOn(component.returnUpdated, 'emit');

    component.onCancelled(cancelledReturn);
    expect(component.showCancelModal).toBeFalse();
    expect(component.goodsReturn?.status).toBe('cancelled');
    expect(component.actionMessage).toContain('has been cancelled');
    expect(component.returnUpdated.emit).toHaveBeenCalledWith(cancelledReturn);
  });

  it('reloads when companyId or returnId inputs change', () => {
    mockGoodsReturnService.getGoodsReturn.calls.reset();
    component.returnId = 'grr-2';
    component.ngOnChanges({
      returnId: {
        currentValue: 'grr-2',
        previousValue: 'grr-1',
        firstChange: false,
        isFirstChange: () => false,
      },
    });

    expect(mockGoodsReturnService.getGoodsReturn).toHaveBeenCalledWith('comp-1', 'grr-2');
  });

  it('emits back event when back button is clicked', () => {
    spyOn(component.back, 'emit');
    component.onBack();
    expect(component.back.emit).toHaveBeenCalled();
  });

  // =========================================================================
  // Stage 4A: Receipt History and Asset Classification Tests
  // =========================================================================

  describe('Stage 4A: Receipt History & Asset Classification', () => {
    const mockReceipt = {
      id: 'wr-1',
      company_id: 'comp-1',
      goods_return_id: 'grr-1',
      receipt_number: 'WR-GRR-20261107-01',
      receipt_date: '2026-11-07',
      received_at: '2026-11-07T14:30:00Z',
      received_by_id: 'user-wh-clerk',
      warehouse_location_id: null,
      dispatch_reference: 'WB-CARRIER-99',
      reason: 'Carrier delivery returned to warehouse',
      notes: 'Chassis inspection verified',
      created_at: '2026-11-07T14:30:00Z',
      lines: [
        {
          id: 'wrl-1',
          company_id: 'comp-1',
          warehouse_receipt_id: 'wr-1',
          goods_return_id: 'grr-1',
          goods_return_line_id: 'line-1',
          asset_id: 'ast-1',
          condition_on_return: 'intact',
          notes: 'Box intact',
          is_corrected: false,
          correction_reason: null,
          corrected_at: null,
          corrected_by_id: null,
          created_at: '2026-11-07T14:30:00Z',
        },
      ],
    };

    it('loads and displays warehouse receipts in Section C with headers and individual lines', () => {
      component.goodsReturn = { ...baseDraftReturn, status: 'partially_returned_to_warehouse' };
      component.warehouseReceipts = [mockReceipt];
      component.expandedReceiptIds = new Set(['wr-1']);
      fixture.detectChanges();

      const sectionC = fixture.nativeElement.querySelector('#warehouse-receipts-section');
      expect(sectionC).toBeTruthy();
      expect(sectionC.textContent).toContain('WR-GRR-20261107-01');
      expect(sectionC.textContent).toContain('Carrier delivery returned to warehouse');
      expect(sectionC.textContent).toContain('AST-0001');
      expect(sectionC.textContent).toContain('ACTIVE INTAKE');
      expect(sectionC.textContent).toContain('intact');
    });

    it('displays corrected receipt lines with correction reason, timestamp, and metadata', () => {
      const correctedReceipt = {
        ...mockReceipt,
        lines: [
          {
            id: 'wrl-1',
            company_id: 'comp-1',
            warehouse_receipt_id: 'wr-1',
            goods_return_id: 'grr-1',
            goods_return_line_id: 'line-1',
            asset_id: 'ast-1',
            condition_on_return: 'damaged',
            notes: 'Initial scan\n[Correction]: Wrong barcode scanned',
            is_corrected: true,
            correction_reason: 'Clerical mistake: item was not actually returned',
            corrected_at: '2026-11-07T16:00:00Z',
            corrected_by_id: 'user-supervisor',
            created_at: '2026-11-07T14:30:00Z',
          },
        ],
      };

      component.goodsReturn = { ...baseDraftReturn, status: 'dispatched' };
      component.warehouseReceipts = [correctedReceipt];
      component.expandedReceiptIds = new Set(['wr-1']);
      fixture.detectChanges();

      const sectionC = fixture.nativeElement.querySelector('#warehouse-receipts-section');
      expect(sectionC.textContent).toContain('CORRECTED');
      expect(sectionC.textContent).toContain('Clerical mistake: item was not actually returned');
      expect(sectionC.textContent).toContain('Contains Corrected Lines');
    });

    it('correctly classifies assets across GRR lifecycle states and computes summary counts', () => {
      // 1. Dispatched: zero receipts -> both lines In Transit
      component.goodsReturn = { ...baseDraftReturn, status: 'dispatched' };
      component.warehouseReceipts = [];
      expect(component.lineCountsSummary.total).toBe(2);
      expect(component.lineCountsSummary.inTransit).toBe(2);
      expect(component.lineCountsSummary.receivedWarehouse).toBe(0);
      expect(component.classifiedLines[0].classification).toBe('in_transit');
      expect(component.classifiedLines[1].classification).toBe('in_transit');

      // 2. Partially returned: line 1 received -> received_warehouse, line 2 -> in_transit
      component.goodsReturn = { ...baseDraftReturn, status: 'partially_returned_to_warehouse' };
      component.warehouseReceipts = [mockReceipt];
      expect(component.lineCountsSummary.total).toBe(2);
      expect(component.lineCountsSummary.receivedWarehouse).toBe(1);
      expect(component.lineCountsSummary.inTransit).toBe(1);
      expect(component.classifiedLines[0].classification).toBe('received_warehouse');
      expect(component.classifiedLines[1].classification).toBe('in_transit');

      // 3. Completed: line 1 was received in warehouse, line 2 was accepted by vendor (NOT in transit!)
      component.goodsReturn = { ...baseDraftReturn, status: 'completed' };
      component.warehouseReceipts = [mockReceipt];
      expect(component.lineCountsSummary.receivedWarehouse).toBe(1);
      expect(component.lineCountsSummary.acceptedVendor).toBe(1);
      expect(component.lineCountsSummary.inTransit).toBe(0);
      expect(component.classifiedLines[0].classification).toBe('received_warehouse');
      expect(component.classifiedLines[1].classification).toBe('accepted_vendor');

      // 4. Returned to warehouse: both lines received
      const fullReceipt = {
        ...mockReceipt,
        lines: [
          mockReceipt.lines[0],
          {
            ...mockReceipt.lines[0],
            id: 'wrl-2',
            goods_return_line_id: 'line-2',
            asset_id: 'ast-2',
          },
        ],
      };
      component.goodsReturn = { ...baseDraftReturn, status: 'returned_to_warehouse' };
      component.warehouseReceipts = [fullReceipt];
      expect(component.lineCountsSummary.receivedWarehouse).toBe(2);
      expect(component.lineCountsSummary.inTransit).toBe(0);
      expect(component.classifiedLines[0].classification).toBe('received_warehouse');
      expect(component.classifiedLines[1].classification).toBe('received_warehouse');
    });

    it('correctly treats restored asset following receipt correction according to restored state and GRR lifecycle', () => {
      // Return reverted to dispatched after receipt line 1 was corrected
      const correctedReceipt = {
        ...mockReceipt,
        lines: [
          {
            ...mockReceipt.lines[0],
            is_corrected: true,
            correction_reason: 'Carrier redelivery pending',
          },
        ],
      };

      component.goodsReturn = { ...baseDraftReturn, status: 'dispatched' };
      component.warehouseReceipts = [correctedReceipt];
      fixture.detectChanges();

      const classified = component.classifiedLines;
      expect(classified[0].classification).toBe('in_transit');
      expect(classified[0].hasCorrection).toBeTrue();
      expect(classified[0].correctionHistory.length).toBe(1);
      expect(classified[0].correctionHistory[0].receiptLine.correction_reason).toBe('Carrier redelivery pending');
      expect(component.lineCountsSummary.corrected).toBe(1);
      expect(component.lineCountsSummary.inTransit).toBe(2);

      const tableEl = fixture.nativeElement.querySelector('.lines-card');
      expect(tableEl.textContent).toContain('⚠️ Corrected');
    });

    it('displays permission warning when user lacks procurement.read permission', () => {
      component.goodsReturn = { ...baseDraftReturn, status: 'dispatched' };
      component.canRead = false;
      fixture.detectChanges();

      const sectionC = fixture.nativeElement.querySelector('#warehouse-receipts-section');
      expect(sectionC.textContent).toContain('Viewing warehouse receipt history requires procurement.read permission');
    });

    it('handles loading, empty, and error states for warehouse receipts gracefully', () => {
      component.goodsReturn = { ...baseDraftReturn, status: 'dispatched' };
      component.canRead = true;

      // Loading state
      component.loadingReceipts = true;
      component.warehouseReceipts = [];
      fixture.detectChanges();
      let sectionC = fixture.nativeElement.querySelector('#warehouse-receipts-section');
      expect(sectionC.textContent).toContain('Loading warehouse receipt records from server');

      // Error state
      component.loadingReceipts = false;
      component.receiptsError = 'Failed to load receipts due to network timeout';
      fixture.detectChanges();
      sectionC = fixture.nativeElement.querySelector('#warehouse-receipts-section');
      expect(sectionC.textContent).toContain('Failed to load receipts due to network timeout');
      expect(sectionC.querySelector('.retry-btn')).toBeTruthy();

      // Retry action
      spyOn(component, 'loadWarehouseReceipts');
      sectionC.querySelector('.retry-btn').click();
      expect(component.loadWarehouseReceipts).toHaveBeenCalled();

      // Empty state for dispatched
      component.receiptsError = null;
      component.warehouseReceipts = [];
      fixture.detectChanges();
      sectionC = fixture.nativeElement.querySelector('#warehouse-receipts-section');
      expect(sectionC.textContent).toContain('All 2 dispatched asset(s) are currently in transit');
    });

    it('toggles receipt accordion expansion', () => {
      component.goodsReturn = { ...baseDraftReturn, status: 'dispatched' };
      component.warehouseReceipts = [mockReceipt];
      component.expandedReceiptIds = new Set(['wr-1']);
      fixture.detectChanges();

      expect(component.isReceiptExpanded('wr-1')).toBeTrue();
      let receiptContent = fixture.nativeElement.querySelector('.receipt-body-content');
      expect(receiptContent).toBeTruthy();

      // Toggle collapse
      component.toggleReceiptExpanded('wr-1');
      fixture.detectChanges();

      expect(component.isReceiptExpanded('wr-1')).toBeFalse();
      receiptContent = fixture.nativeElement.querySelector('.receipt-body-content');
      expect(receiptContent).toBeFalsy();

      // Toggle expand
      component.toggleReceiptExpanded('wr-1');
      fixture.detectChanges();

      expect(component.isReceiptExpanded('wr-1')).toBeTrue();
      receiptContent = fixture.nativeElement.querySelector('.receipt-body-content');
      expect(receiptContent).toBeTruthy();
    });
  });

  // =========================================================================
  // Stage 4B: Warehouse Receipt Intake Workflow Tests
  // =========================================================================

  describe('Stage 4B: Warehouse Receipt Intake Integration', () => {
    const mockReceipt = {
      id: 'wr-1',
      company_id: 'comp-1',
      goods_return_id: 'grr-1',
      receipt_number: 'WR-GRR-20261107-01',
      receipt_date: '2026-11-07',
      received_at: '2026-11-07T14:30:00Z',
      received_by_id: 'user-wh-clerk',
      warehouse_location_id: null,
      dispatch_reference: 'WB-CARRIER-99',
      reason: 'Physical return',
      notes: null,
      created_at: '2026-11-07T14:30:00Z',
      lines: [
        {
          id: 'wrl-1',
          company_id: 'comp-1',
          warehouse_receipt_id: 'wr-1',
          goods_return_id: 'grr-1',
          goods_return_line_id: 'line-1',
          asset_id: 'ast-1',
          condition_on_return: 'intact',
          notes: null,
          is_corrected: false,
          correction_reason: null,
          corrected_at: null,
          corrected_by_id: null,
          created_at: '2026-11-07T14:30:00Z',
        },
      ],
    };

    it('shows "Receive into Warehouse" button only when state is dispatched or partial and user has canManage', () => {
      // 1. Dispatched with canManage -> visible
      component.goodsReturn = { ...baseDraftReturn, status: 'dispatched' };
      component.warehouseReceipts = [];
      component.canManage = true;
      fixture.detectChanges();
      expect(component.canReceiveWarehouse).toBeTrue();
      let btn = fixture.nativeElement.querySelector('.receive-warehouse-btn');
      expect(btn).toBeTruthy();

      // 2. Dispatched but canManage is false -> hidden
      component.canManage = false;
      fixture.detectChanges();
      expect(component.canReceiveWarehouse).toBeFalse();
      btn = fixture.nativeElement.querySelector('.receive-warehouse-btn');
      expect(btn).toBeFalsy();

      // 3. Partially returned with canManage and 1 in-transit item remaining -> visible
      component.canManage = true;
      component.goodsReturn = { ...baseDraftReturn, status: 'partially_returned_to_warehouse' };
      component.warehouseReceipts = [mockReceipt];
      fixture.detectChanges();
      expect(component.canReceiveWarehouse).toBeTrue();
      btn = fixture.nativeElement.querySelector('.receive-warehouse-btn');
      expect(btn).toBeTruthy();

      // 4. Returned to warehouse -> hidden (all received)
      const fullReceipt = {
        ...mockReceipt,
        lines: [
          mockReceipt.lines[0],
          {
            ...mockReceipt.lines[0],
            id: 'wrl-2',
            goods_return_line_id: 'line-2',
            asset_id: 'ast-2',
          },
        ],
      };
      component.goodsReturn = { ...baseDraftReturn, status: 'returned_to_warehouse' };
      component.warehouseReceipts = [fullReceipt];
      fixture.detectChanges();
      expect(component.canReceiveWarehouse).toBeFalse();
      btn = fixture.nativeElement.querySelector('.receive-warehouse-btn');
      expect(btn).toBeFalsy();

      // 5. Completed or draft -> hidden
      component.goodsReturn = { ...baseDraftReturn, status: 'draft' };
      expect(component.canReceiveWarehouse).toBeFalse();
      component.goodsReturn = { ...baseDraftReturn, status: 'completed' };
      expect(component.canReceiveWarehouse).toBeFalse();
    });

    it('excludes lines with non-return_pending asset_status from eligibleInTransitAssetsCount', () => {
      component.goodsReturn = {
        ...baseDraftReturn,
        status: 'dispatched',
        lines: [
          { ...baseDraftReturn.lines[0], asset_status: 'return_pending' },
          { ...baseDraftReturn.lines[1], asset_status: 'reversed' },
        ],
      };
      component.warehouseReceipts = [];
      component.canManage = true;
      fixture.detectChanges();

      expect(component.eligibleInTransitAssetsCount).toBe(1);
      expect(component.canReceiveWarehouse).toBeTrue();
    });

    it('opens and closes the warehouse receipt intake modal', () => {
      component.goodsReturn = { ...baseDraftReturn, status: 'dispatched' };
      component.warehouseReceipts = [];
      component.canManage = true;
      fixture.detectChanges();

      expect(component.showWarehouseReceiptModal).toBeFalse();

      component.openWarehouseReceiptModal();
      fixture.detectChanges();
      expect(component.showWarehouseReceiptModal).toBeTrue();
      expect(fixture.nativeElement.querySelector('app-goods-return-warehouse-receipt-modal')).toBeTruthy();
    });

    it('refreshes return and receipt history after successful receipt creation', () => {
      mockGoodsReturnService.getGoodsReturn.calls.reset();
      mockGoodsReturnService.listWarehouseReceipts.calls.reset();

      component.goodsReturn = { ...baseDraftReturn, status: 'dispatched' };
      component.showWarehouseReceiptModal = true;

      component.onReceiptCreated(mockReceipt);

      expect(component.showWarehouseReceiptModal).toBeFalse();
      expect(component.actionMessage).toContain('WR-GRR-20261107-01 recorded successfully');
      expect(mockGoodsReturnService.getGoodsReturn).toHaveBeenCalledWith('comp-1', 'grr-1');
      expect(mockGoodsReturnService.listWarehouseReceipts).toHaveBeenCalledWith('comp-1', 'grr-1');
    });

    it('refreshes server state when a receipt conflict occurs', () => {
      mockGoodsReturnService.getGoodsReturn.calls.reset();
      mockGoodsReturnService.listWarehouseReceipts.calls.reset();

      component.onReceiptConflict();

      expect(mockGoodsReturnService.getGoodsReturn).toHaveBeenCalledWith('comp-1', 'grr-1');
      expect(mockGoodsReturnService.listWarehouseReceipts).toHaveBeenCalledWith('comp-1', 'grr-1');
    });

    it('handles conflictOccurred event from warehouse receipt modal template binding', () => {
      component.goodsReturn = { ...baseDraftReturn, status: 'dispatched' };
      component.warehouseReceipts = [];
      component.canManage = true;
      component.showWarehouseReceiptModal = true;
      fixture.detectChanges();

      mockGoodsReturnService.getGoodsReturn.calls.reset();
      mockGoodsReturnService.listWarehouseReceipts.calls.reset();

      const modalEl = fixture.debugElement.nativeElement.querySelector('app-goods-return-warehouse-receipt-modal');
      expect(modalEl).toBeTruthy();

      component.onReceiptConflict();

      expect(mockGoodsReturnService.getGoodsReturn).toHaveBeenCalledWith('comp-1', 'grr-1');
      expect(mockGoodsReturnService.listWarehouseReceipts).toHaveBeenCalledWith('comp-1', 'grr-1');
    });
  });

  // =========================================================================
  // Stage 4C: Warehouse Receipt Correction Integration Tests
  // =========================================================================

  describe('Stage 4C: Warehouse Receipt Correction Integration', () => {
    const uncorrectedReceipt = {
      id: 'wr-1',
      company_id: 'comp-1',
      goods_return_id: 'grr-1',
      receipt_number: 'WR-20261108-01',
      receipt_date: '2026-11-08',
      received_at: '2026-11-08T11:00:00Z',
      received_by_id: 'user-wh-clerk',
      warehouse_location_id: null,
      dispatch_reference: 'DISP-777',
      reason: 'Physical delivery back to dock',
      notes: null,
      created_at: '2026-11-08T11:00:00Z',
      lines: [
        {
          id: 'wrl-1',
          company_id: 'comp-1',
          warehouse_receipt_id: 'wr-1',
          goods_return_id: 'grr-1',
          goods_return_line_id: 'line-1',
          asset_id: 'ast-1',
          condition_on_return: 'intact',
          notes: 'Received intact',
          is_corrected: false,
          correction_reason: null,
          corrected_at: null,
          corrected_by_id: null,
          created_at: '2026-11-08T11:00:00Z',
        },
      ],
    };

    const correctedReceipt = {
      ...uncorrectedReceipt,
      lines: [
        {
          ...uncorrectedReceipt.lines[0],
          is_corrected: true,
          correction_reason: 'Scanned wrong serial into dock',
          corrected_at: '2026-11-08T12:00:00Z',
          corrected_by_id: 'user-wh-supervisor',
        },
      ],
    };

    it('calculates canCorrectReceiptLine based on canManage and non-terminal lifecycle', () => {
      // 1. canManage = true, status = partially_returned_to_warehouse -> true
      component.goodsReturn = { ...baseDraftReturn, status: 'partially_returned_to_warehouse' };
      component.canManage = true;
      expect(component.canCorrectReceiptLine).toBeTrue();

      // 2. canManage = true, status = returned_to_warehouse -> true
      component.goodsReturn = { ...baseDraftReturn, status: 'returned_to_warehouse' };
      expect(component.canCorrectReceiptLine).toBeTrue();

      // 3. canManage = true, status = dispatched -> true
      component.goodsReturn = { ...baseDraftReturn, status: 'dispatched' };
      expect(component.canCorrectReceiptLine).toBeTrue();

      // 4. canManage = false -> false
      component.canManage = false;
      expect(component.canCorrectReceiptLine).toBeFalse();

      // 5. status = completed -> false (even with canManage = true)
      component.canManage = true;
      component.goodsReturn = { ...baseDraftReturn, status: 'completed' };
      expect(component.canCorrectReceiptLine).toBeFalse();

      // 6. status = cancelled -> false
      component.goodsReturn = { ...baseDraftReturn, status: 'cancelled' };
      expect(component.canCorrectReceiptLine).toBeFalse();
    });

    it('shows "Correct Intake" button for uncorrected lines when user has permission and return is active', () => {
      component.goodsReturn = { ...baseDraftReturn, status: 'partially_returned_to_warehouse' };
      component.warehouseReceipts = [uncorrectedReceipt];
      component.expandedReceiptIds = new Set(['wr-1']);
      component.canManage = true;
      fixture.detectChanges();

      const btn = fixture.nativeElement.querySelector('.correct-intake-btn');
      expect(btn).toBeTruthy();
      expect(btn.textContent).toContain('Correct Intake');
    });

    it('hides "Correct Intake" button for already corrected lines', () => {
      component.goodsReturn = { ...baseDraftReturn, status: 'dispatched' };
      component.warehouseReceipts = [correctedReceipt];
      component.expandedReceiptIds = new Set(['wr-1']);
      component.canManage = true;
      fixture.detectChanges();

      const btn = fixture.nativeElement.querySelector('.correct-intake-btn');
      expect(btn).toBeFalsy();

      const tableContent = fixture.nativeElement.querySelector('.receipt-lines-table').textContent;
      expect(tableContent).toContain('Corrected');
      expect(tableContent).toContain('Scanned wrong serial into dock');
    });

    it('hides "Correct Intake" button when user lacks procurement.manage permission', () => {
      component.goodsReturn = { ...baseDraftReturn, status: 'partially_returned_to_warehouse' };
      component.warehouseReceipts = [uncorrectedReceipt];
      component.expandedReceiptIds = new Set(['wr-1']);
      component.canManage = false;
      fixture.detectChanges();

      const btn = fixture.nativeElement.querySelector('.correct-intake-btn');
      expect(btn).toBeFalsy();
    });

    it('hides "Correct Intake" button when return is completed or cancelled', () => {
      component.warehouseReceipts = [uncorrectedReceipt];
      component.expandedReceiptIds = new Set(['wr-1']);
      component.canManage = true;

      // Completed
      component.goodsReturn = { ...baseDraftReturn, status: 'completed' };
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.correct-intake-btn')).toBeFalsy();

      // Cancelled
      component.goodsReturn = { ...baseDraftReturn, status: 'cancelled' };
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.correct-intake-btn')).toBeFalsy();
    });

    it('opens the correction modal with the target receipt and receipt line when clicked', () => {
      component.goodsReturn = { ...baseDraftReturn, status: 'partially_returned_to_warehouse' };
      component.warehouseReceipts = [uncorrectedReceipt];
      component.expandedReceiptIds = new Set(['wr-1']);
      component.canManage = true;
      fixture.detectChanges();

      expect(component.showCorrectionModal).toBeFalse();

      const btn: HTMLButtonElement = fixture.nativeElement.querySelector('.correct-intake-btn');
      btn.click();
      fixture.detectChanges();

      expect(component.showCorrectionModal).toBeTrue();
      expect(component.selectedReceiptForCorrection).toBe(uncorrectedReceipt);
      expect(component.selectedLineForCorrection).toBe(uncorrectedReceipt.lines[0]);

      const modalEl = fixture.nativeElement.querySelector('app-goods-return-receipt-correction-modal');
      expect(modalEl).toBeTruthy();
    });

    it('refreshes both parent return and receipt history upon onCorrectionComplete', () => {
      mockGoodsReturnService.getGoodsReturn.calls.reset();
      mockGoodsReturnService.listWarehouseReceipts.calls.reset();

      component.goodsReturn = { ...baseDraftReturn, status: 'partially_returned_to_warehouse' };
      component.showCorrectionModal = true;
      component.selectedReceiptForCorrection = uncorrectedReceipt;
      component.selectedLineForCorrection = uncorrectedReceipt.lines[0];

      component.onCorrectionComplete(correctedReceipt);

      expect(component.showCorrectionModal).toBeFalse();
      expect(component.selectedReceiptForCorrection).toBeNull();
      expect(component.selectedLineForCorrection).toBeNull();
      expect(component.actionMessage).toContain('corrected successfully');
      expect(mockGoodsReturnService.getGoodsReturn).toHaveBeenCalledWith('comp-1', 'grr-1');
      expect(mockGoodsReturnService.listWarehouseReceipts).toHaveBeenCalledWith('comp-1', 'grr-1');
    });

    it('refreshes both parent return and receipt history upon onCorrectionConflict', () => {
      mockGoodsReturnService.getGoodsReturn.calls.reset();
      mockGoodsReturnService.listWarehouseReceipts.calls.reset();

      component.onCorrectionConflict();

      expect(mockGoodsReturnService.getGoodsReturn).toHaveBeenCalledWith('comp-1', 'grr-1');
      expect(mockGoodsReturnService.listWarehouseReceipts).toHaveBeenCalledWith('comp-1', 'grr-1');
    });

    it('closes the modal without refresh when closeCorrectionModal is called', () => {
      mockGoodsReturnService.getGoodsReturn.calls.reset();
      mockGoodsReturnService.listWarehouseReceipts.calls.reset();

      component.showCorrectionModal = true;
      component.selectedReceiptForCorrection = uncorrectedReceipt;
      component.selectedLineForCorrection = uncorrectedReceipt.lines[0];

      component.closeCorrectionModal();

      expect(component.showCorrectionModal).toBeFalse();
      expect(component.selectedReceiptForCorrection).toBeNull();
      expect(component.selectedLineForCorrection).toBeNull();
      expect(mockGoodsReturnService.getGoodsReturn).not.toHaveBeenCalled();
      expect(mockGoodsReturnService.listWarehouseReceipts).not.toHaveBeenCalled();
    });

    it('displays correction reason and user UUID in receipt line table when line is corrected', () => {
      component.goodsReturn = { ...baseDraftReturn, status: 'dispatched' };
      component.warehouseReceipts = [correctedReceipt];
      component.expandedReceiptIds = new Set(['wr-1']);
      fixture.detectChanges();

      const tableContent = fixture.nativeElement.querySelector('.receipt-lines-table').textContent;
      expect(tableContent).toContain('Scanned wrong serial into dock');
      expect(tableContent).toContain('user-wh-'); // sliced UUID display
    });
  });

  // =========================================================================
  // Stage 4D: Vendor Acceptance / Goods Return Completion Integration Tests
  // =========================================================================

  describe('Stage 4D: Vendor Acceptance / Goods Return Completion Integration', () => {
    const fiveLines = [
      { id: 'line-1', asset_id: 'ast-1', asset_number: 'AST-0001', serial_number: 'SN-1', return_condition: 'as_received', notes: null },
      { id: 'line-2', asset_id: 'ast-2', asset_number: 'AST-0002', serial_number: 'SN-2', return_condition: 'as_received', notes: null },
      { id: 'line-3', asset_id: 'ast-3', asset_number: 'AST-0003', serial_number: 'SN-3', return_condition: 'as_received', notes: null },
      { id: 'line-4', asset_id: 'ast-4', asset_number: 'AST-0004', serial_number: 'SN-4', return_condition: 'as_received', notes: null },
      { id: 'line-5', asset_id: 'ast-5', asset_number: 'AST-0005', serial_number: 'SN-5', return_condition: 'as_received', notes: null },
    ];

    const fiveAssetReturn: GoodsReturn = {
      ...baseDraftReturn,
      status: 'dispatched',
      lines: fiveLines.map((l) => ({
        ...baseDraftReturn.lines[0],
        ...l,
      })),
    };

    const makeReceipt = (
      id: string,
      receiptNumber: string,
      receiptLines: { id: string; goods_return_line_id: string; asset_id: string; is_corrected: boolean }[]
    ) => ({
      id,
      company_id: 'comp-1',
      goods_return_id: 'grr-1',
      receipt_number: receiptNumber,
      receipt_date: '2026-11-08',
      received_at: '2026-11-08T11:00:00Z',
      received_by_id: 'user-wh',
      warehouse_location_id: null,
      dispatch_reference: null,
      reason: 'Physical intake',
      notes: null,
      created_at: '2026-11-08T11:00:00Z',
      lines: receiptLines.map((rl) => ({
        id: rl.id,
        company_id: 'comp-1',
        warehouse_receipt_id: id,
        goods_return_id: 'grr-1',
        goods_return_line_id: rl.goods_return_line_id,
        asset_id: rl.asset_id,
        condition_on_return: 'intact',
        notes: null,
        is_corrected: rl.is_corrected,
        correction_reason: rl.is_corrected ? 'Correction note' : null,
        corrected_at: rl.is_corrected ? '2026-11-08T12:00:00Z' : null,
        corrected_by_id: rl.is_corrected ? 'user-supervisor' : null,
        created_at: '2026-11-08T11:00:00Z',
      })),
    });

    it('calculates 5 outstanding assets when 0 receipts exist', () => {
      component.goodsReturn = fiveAssetReturn;
      component.warehouseReceipts = [];
      component.receiptsLoadedSuccessfully = true;
      fixture.detectChanges();

      expect(component.outstandingInTransitLines.length).toBe(5);
      expect(component.outstandingInTransitCount).toBe(5);
    });

    it('calculates 3 outstanding assets when 2 lines have active warehouse receipts', () => {
      component.goodsReturn = fiveAssetReturn;
      component.warehouseReceipts = [
        makeReceipt('wr-1', 'WR-01', [
          { id: 'wrl-1', goods_return_line_id: 'line-1', asset_id: 'ast-1', is_corrected: false },
          { id: 'wrl-2', goods_return_line_id: 'line-2', asset_id: 'ast-2', is_corrected: false },
        ]),
      ];
      component.receiptsLoadedSuccessfully = true;
      fixture.detectChanges();

      expect(component.outstandingInTransitCount).toBe(3);
      const remainingIds = component.outstandingInTransitLines.map((l) => l.id);
      expect(remainingIds).toEqual(['line-3', 'line-4', 'line-5']);
    });

    it('calculates 0 outstanding assets when all 5 lines are actively received', () => {
      component.goodsReturn = fiveAssetReturn;
      component.warehouseReceipts = [
        makeReceipt('wr-1', 'WR-01', [
          { id: 'wrl-1', goods_return_line_id: 'line-1', asset_id: 'ast-1', is_corrected: false },
          { id: 'wrl-2', goods_return_line_id: 'line-2', asset_id: 'ast-2', is_corrected: false },
          { id: 'wrl-3', goods_return_line_id: 'line-3', asset_id: 'ast-3', is_corrected: false },
          { id: 'wrl-4', goods_return_line_id: 'line-4', asset_id: 'ast-4', is_corrected: false },
          { id: 'wrl-5', goods_return_line_id: 'line-5', asset_id: 'ast-5', is_corrected: false },
        ]),
      ];
      component.receiptsLoadedSuccessfully = true;
      fixture.detectChanges();

      expect(component.outstandingInTransitCount).toBe(0);
      expect(component.outstandingInTransitLines).toEqual([]);
    });

    it('keeps a line outstanding when its receipt was corrected', () => {
      component.goodsReturn = fiveAssetReturn;
      component.warehouseReceipts = [
        makeReceipt('wr-1', 'WR-01', [
          { id: 'wrl-1', goods_return_line_id: 'line-1', asset_id: 'ast-1', is_corrected: true }, // corrected
          { id: 'wrl-2', goods_return_line_id: 'line-2', asset_id: 'ast-2', is_corrected: false }, // active
        ]),
      ];
      component.receiptsLoadedSuccessfully = true;
      fixture.detectChanges();

      expect(component.outstandingInTransitCount).toBe(4);
      const remainingIds = component.outstandingInTransitLines.map((l) => l.id);
      expect(remainingIds).toContain('line-1'); // line-1 is outstanding again
      expect(remainingIds).not.toContain('line-2');
    });

    it('excludes a line when a corrected receipt is followed by a new active receipt', () => {
      component.goodsReturn = fiveAssetReturn;
      component.warehouseReceipts = [
        makeReceipt('wr-1', 'WR-01', [
          { id: 'wrl-1', goods_return_line_id: 'line-1', asset_id: 'ast-1', is_corrected: true },
        ]),
        makeReceipt('wr-2', 'WR-02', [
          { id: 'wrl-2', goods_return_line_id: 'line-1', asset_id: 'ast-1', is_corrected: false }, // re-received
        ]),
      ];
      component.receiptsLoadedSuccessfully = true;
      fixture.detectChanges();

      expect(component.outstandingInTransitCount).toBe(4);
      const remainingIds = component.outstandingInTransitLines.map((l) => l.id);
      expect(remainingIds).not.toContain('line-1'); // actively received in wr-2
    });

    it('does not duplicate lines when multiple receipt lines reference the same return line', () => {
      component.goodsReturn = fiveAssetReturn;
      component.warehouseReceipts = [
        makeReceipt('wr-1', 'WR-01', [
          { id: 'wrl-1', goods_return_line_id: 'line-1', asset_id: 'ast-1', is_corrected: false },
          { id: 'wrl-1-dup', goods_return_line_id: 'line-1', asset_id: 'ast-1', is_corrected: false },
        ]),
      ];
      component.receiptsLoadedSuccessfully = true;
      fixture.detectChanges();

      expect(component.outstandingInTransitCount).toBe(4);
      const line1Occurrences = component.outstandingInTransitLines.filter((l) => l.id === 'line-1').length;
      expect(line1Occurrences).toBe(0);
    });

    it('returns empty outstanding lines and blocks completion while receipt history is loading', () => {
      component.goodsReturn = fiveAssetReturn;
      component.loadingReceipts = true;
      component.receiptsLoadedSuccessfully = false;
      component.warehouseReceipts = [];
      component.canManage = true;
      fixture.detectChanges();

      expect(component.outstandingInTransitLines).toEqual([]);
      expect(component.outstandingInTransitCount).toBe(0);
      expect(component.canComplete).toBeFalse();
      expect(fixture.nativeElement.querySelector('.complete-return-btn')).toBeFalsy();
    });

    it('returns empty outstanding lines and blocks completion when receipt history failed', () => {
      component.goodsReturn = fiveAssetReturn;
      component.loadingReceipts = false;
      component.receiptsLoadedSuccessfully = false;
      component.receiptsError = 'Failed to load receipts';
      component.canManage = true;
      fixture.detectChanges();

      expect(component.outstandingInTransitLines).toEqual([]);
      expect(component.outstandingInTransitCount).toBe(0);
      expect(component.canComplete).toBeFalse();
      expect(fixture.nativeElement.querySelector('.complete-return-btn')).toBeFalsy();
      expect(fixture.nativeElement.querySelector('.outstanding-summary-badge')).toBeFalsy();
    });

    it('recovers calculation and enables completion when receipt history retry succeeds', () => {
      mockGoodsReturnService.listWarehouseReceipts.and.returnValue(of([]));

      component.goodsReturn = fiveAssetReturn;
      component.receiptsError = 'Network timeout';
      component.receiptsLoadedSuccessfully = false;
      component.canManage = true;
      fixture.detectChanges();

      expect(component.canComplete).toBeFalse();

      component.loadWarehouseReceipts();
      fixture.detectChanges();

      expect(component.receiptsLoadedSuccessfully).toBeTrue();
      expect(component.receiptsError).toBeNull();
      expect(component.outstandingInTransitCount).toBe(5);
      expect(component.canComplete).toBeTrue();
      expect(fixture.nativeElement.querySelector('.complete-return-btn')).toBeTruthy();
    });

    it('discards stale response when returnId changes while a request is in flight', () => {
      component.companyId = 'comp-1';
      component.returnId = 'grr-1';
      component.loadReturn();

      // User switches returnId before request finishes
      component.returnId = 'grr-99';
      fixture.detectChanges();

      expect(component.goodsReturn?.id).not.toBe('grr-99');
    });

    describe('canComplete Lifecycle and Permission Matrix', () => {
      beforeEach(() => {
        component.goodsReturn = fiveAssetReturn;
        component.warehouseReceipts = [];
        component.receiptsLoadedSuccessfully = true;
        component.canManage = true;
      });

      it('shows complete button for dispatched return with outstanding assets and canManage', () => {
        component.goodsReturn = { ...fiveAssetReturn, status: 'dispatched' };
        fixture.detectChanges();

        expect(component.canComplete).toBeTrue();
        const btn = fixture.nativeElement.querySelector('.complete-return-btn');
        expect(btn).toBeTruthy();
        expect(btn.textContent).toContain('Complete Return');

        const badge = fixture.nativeElement.querySelector('.outstanding-summary-badge');
        expect(badge).toBeTruthy();
        expect(badge.textContent).toContain('5 of 5 assets awaiting vendor acceptance');
      });

      it('shows complete button for partially_returned_to_warehouse with remaining in-transit assets', () => {
        component.goodsReturn = { ...fiveAssetReturn, status: 'partially_returned_to_warehouse' };
        component.warehouseReceipts = [
          makeReceipt('wr-1', 'WR-01', [
            { id: 'wrl-1', goods_return_line_id: 'line-1', asset_id: 'ast-1', is_corrected: false },
          ]),
        ];
        fixture.detectChanges();

        expect(component.canComplete).toBeTrue();
        expect(component.outstandingInTransitCount).toBe(4);
        expect(fixture.nativeElement.querySelector('.complete-return-btn')).toBeTruthy();
      });

      it('hides complete button when return status is returned_to_warehouse', () => {
        component.goodsReturn = { ...fiveAssetReturn, status: 'returned_to_warehouse' };
        fixture.detectChanges();

        expect(component.canComplete).toBeFalse();
        expect(fixture.nativeElement.querySelector('.complete-return-btn')).toBeFalsy();
      });

      it('hides complete button when return status is completed', () => {
        component.goodsReturn = { ...fiveAssetReturn, status: 'completed' };
        fixture.detectChanges();

        expect(component.canComplete).toBeFalse();
        expect(fixture.nativeElement.querySelector('.complete-return-btn')).toBeFalsy();
      });

      it('hides complete button when return status is cancelled', () => {
        component.goodsReturn = { ...fiveAssetReturn, status: 'cancelled' };
        fixture.detectChanges();

        expect(component.canComplete).toBeFalse();
        expect(fixture.nativeElement.querySelector('.complete-return-btn')).toBeFalsy();
      });

      it('hides complete button when user lacks procurement.manage permission', () => {
        component.canManage = false;
        fixture.detectChanges();

        expect(component.canComplete).toBeFalse();
        expect(fixture.nativeElement.querySelector('.complete-return-btn')).toBeFalsy();
      });

      it('hides complete button when outstanding in-transit count is 0', () => {
        component.warehouseReceipts = [
          makeReceipt('wr-all', 'WR-ALL', [
            { id: 'wrl-1', goods_return_line_id: 'line-1', asset_id: 'ast-1', is_corrected: false },
            { id: 'wrl-2', goods_return_line_id: 'line-2', asset_id: 'ast-2', is_corrected: false },
            { id: 'wrl-3', goods_return_line_id: 'line-3', asset_id: 'ast-3', is_corrected: false },
            { id: 'wrl-4', goods_return_line_id: 'line-4', asset_id: 'ast-4', is_corrected: false },
            { id: 'wrl-5', goods_return_line_id: 'line-5', asset_id: 'ast-5', is_corrected: false },
          ]),
        ];
        fixture.detectChanges();

        expect(component.outstandingInTransitCount).toBe(0);
        expect(component.canComplete).toBeFalse();
        expect(fixture.nativeElement.querySelector('.complete-return-btn')).toBeFalsy();
      });
    });

    describe('Modal Triggers and Lifecycle Event Handling', () => {
      beforeEach(() => {
        component.goodsReturn = { ...fiveAssetReturn, status: 'dispatched' };
        component.warehouseReceipts = [];
        component.receiptsLoadedSuccessfully = true;
        component.canManage = true;
        fixture.detectChanges();
      });

      it('opens the complete modal with outstanding lines when button clicked', () => {
        expect(component.showCompleteModal).toBeFalse();

        const btn: HTMLButtonElement = fixture.nativeElement.querySelector('.complete-return-btn');
        btn.click();
        fixture.detectChanges();

        expect(component.showCompleteModal).toBeTrue();
        const modalEl = fixture.nativeElement.querySelector('app-goods-return-complete-modal');
        expect(modalEl).toBeTruthy();
      });

      it('handles onCompleted: closes modal, updates return, sets neutral message, reloads APIs and emits returnUpdated', () => {
        const updatedReturn: GoodsReturn = { ...fiveAssetReturn, status: 'completed' };
        mockGoodsReturnService.getGoodsReturn.and.returnValue(of(updatedReturn));
        mockGoodsReturnService.getGoodsReturn.calls.reset();
        mockGoodsReturnService.listWarehouseReceipts.calls.reset();
        spyOn(component.returnUpdated, 'emit');

        component.showCompleteModal = true;

        component.onCompleted(updatedReturn);

        expect(component.showCompleteModal).toBeFalse();
        expect(component.goodsReturn).toEqual(updatedReturn);
        expect(component.actionMessage).toContain('has been completed successfully. Vendor acceptance recorded.');
        expect(mockGoodsReturnService.getGoodsReturn).toHaveBeenCalledWith('comp-1', 'grr-1');
        expect(mockGoodsReturnService.listWarehouseReceipts).toHaveBeenCalledWith('comp-1', 'grr-1');
        expect(component.returnUpdated.emit).toHaveBeenCalledWith(updatedReturn);
      });

      it('derives verified count from authoritative response when completed_lines_count is present', () => {
        const updatedReturn: any = {
          ...fiveAssetReturn,
          status: 'completed',
          completed_lines_count: 3,
        };
        mockGoodsReturnService.getGoodsReturn.and.returnValue(of(updatedReturn));

        component.onCompleted(updatedReturn);

        expect(component.actionMessage).toContain('3 asset(s) marked as accepted by vendor');
      });

      it('simulates changed outstanding set between modal opening and submission: preserves receipt history and avoids unverified count claim', () => {
        component.showCompleteModal = true;
        expect(component.outstandingInTransitCount).toBe(5);

        // Concurrently on server, another user recorded a warehouse receipt for line-1 and line-2
        const concurrentReceipt = makeReceipt('wr-concurrent', 'WR-CONC-01', [
          { id: 'wrl-c1', goods_return_line_id: 'line-1', asset_id: 'ast-1', is_corrected: false },
          { id: 'wrl-c2', goods_return_line_id: 'line-2', asset_id: 'ast-2', is_corrected: false },
        ]);
        const completedReturn: GoodsReturn = { ...fiveAssetReturn, status: 'completed' };

        // Server returns completion without line count assumption; reloads authoritative receipts
        mockGoodsReturnService.getGoodsReturn.and.returnValue(of(completedReturn));
        mockGoodsReturnService.listWarehouseReceipts.and.returnValue(of([concurrentReceipt]));

        component.onCompleted(completedReturn);

        // Does NOT claim "5 assets accepted"
        expect(component.actionMessage).not.toContain('5 outstanding asset(s)');
        expect(component.actionMessage).toContain('has been completed successfully. Vendor acceptance recorded.');

        // Preserves receipt history from server
        expect(component.warehouseReceipts.length).toBe(1);
        expect(component.warehouseReceipts[0].receipt_number).toBe('WR-CONC-01');
      });

      it('handles onCompleteConflict: reloads return and receipt history', () => {
        mockGoodsReturnService.getGoodsReturn.calls.reset();
        mockGoodsReturnService.listWarehouseReceipts.calls.reset();

        component.onCompleteConflict();

        expect(mockGoodsReturnService.getGoodsReturn).toHaveBeenCalledWith('comp-1', 'grr-1');
        expect(mockGoodsReturnService.listWarehouseReceipts).toHaveBeenCalledWith('comp-1', 'grr-1');
      });

      it('handles onCompleteNotFound: triggers authoritative refresh of both loadReturn and loadWarehouseReceipts', () => {
        mockGoodsReturnService.getGoodsReturn.calls.reset();
        mockGoodsReturnService.listWarehouseReceipts.calls.reset();

        component.onCompleteNotFound();

        expect(mockGoodsReturnService.getGoodsReturn).toHaveBeenCalledWith('comp-1', 'grr-1');
        expect(mockGoodsReturnService.listWarehouseReceipts).toHaveBeenCalledWith('comp-1', 'grr-1');
      });

      it('prevents stale data from continuing to enable completion after HTTP 404 on return reload', () => {
        mockGoodsReturnService.getGoodsReturn.and.returnValue(
          throwError(() => ({ status: 404, error: { detail: 'Goods return not found' } }))
        );

        component.onCompleteNotFound();

        expect(component.goodsReturn).toBeNull();
        expect(component.receiptsLoadedSuccessfully).toBeFalse();
        expect(component.canComplete).toBeFalse();
        expect(component.outstandingInTransitCount).toBe(0);
        expect(component.error).toBe('Goods return not found');
      });

      it('prevents in-flight responses for a previously selected Goods Return from overwriting the current selection', () => {
        const return1Subject = new Subject<GoodsReturn>();
        const receipts1Subject = new Subject<GoodsReturnWarehouseReceipt[]>();
        const return2Subject = new Subject<GoodsReturn>();
        const receipts2Subject = new Subject<GoodsReturnWarehouseReceipt[]>();

        const return1: GoodsReturn = { ...fiveAssetReturn, id: 'grr-1' };
        const return2: GoodsReturn = { ...fiveAssetReturn, id: 'grr-2', return_number: 'GRR-20261107-0002' };

        component.companyId = 'comp-1';
        component.returnId = 'grr-1';
        mockGoodsReturnService.getGoodsReturn.and.callFake((_cId: string, rId: string) => {
          if (rId === 'grr-1') return return1Subject.asObservable();
          return return2Subject.asObservable();
        });
        mockGoodsReturnService.listWarehouseReceipts.and.callFake((_cId: string, rId: string) => {
          if (rId === 'grr-1') return receipts1Subject.asObservable();
          return receipts2Subject.asObservable();
        });

        component.loadReturn();
        expect(component.loading).toBeTrue();

        // Switch selection to grr-2
        component.returnId = 'grr-2';
        component.loadReturn();

        // Late response for grr-1 arrives
        return1Subject.next(return1);
        receipts1Subject.next([]);

        expect(component.goodsReturn).toBeNull();
        expect(component.loadedReturnId).toBeNull();
        expect(component.canComplete).toBeFalse();

        // Response for grr-2 arrives
        return2Subject.next(return2);
        receipts2Subject.next([]);

        expect(component.goodsReturn).toEqual(return2);
        expect(component.loadedReturnId).toBe('grr-2');
        expect(component.receiptsLoadedSuccessfully).toBeTrue();
        expect(component.canComplete).toBeTrue();
      });

      it('prevents in-flight responses for a previously selected company from overwriting the current company', () => {
        const company1Subject = new Subject<GoodsReturn>();
        const company2Subject = new Subject<GoodsReturn>();

        const comp1Return: GoodsReturn = { ...fiveAssetReturn, company_id: 'comp-1' };
        const comp2Return: GoodsReturn = { ...fiveAssetReturn, company_id: 'comp-2' };

        component.companyId = 'comp-1';
        component.returnId = 'grr-1';
        mockGoodsReturnService.getGoodsReturn.and.callFake((cId: string) => {
          if (cId === 'comp-1') return company1Subject.asObservable();
          return company2Subject.asObservable();
        });
        mockGoodsReturnService.listWarehouseReceipts.and.returnValue(of([]));

        component.loadReturn();

        // Switch company to comp-2
        component.companyId = 'comp-2';
        component.loadReturn();

        // comp-1 response arrives late
        company1Subject.next(comp1Return);
        expect(component.goodsReturn).toBeNull();

        // comp-2 response arrives
        company2Subject.next(comp2Return);
        expect(component.goodsReturn).toEqual(comp2Return);
        expect(component.loadedReturnCompanyId).toBe('comp-2');
      });

      it('disables completion and returns empty outstanding lines when receipts belong to a different return', () => {
        component.companyId = 'comp-1';
        component.returnId = 'grr-1';
        component.goodsReturn = { ...fiveAssetReturn, id: 'grr-1', company_id: 'comp-1', status: 'dispatched' };
        const mismatchReceipt = makeReceipt('wr-mismatch', 'WR-MISMATCH-01', [
          { id: 'wrl-m1', goods_return_line_id: 'line-1', asset_id: 'ast-1', is_corrected: false },
        ]);
        (mismatchReceipt as any).goods_return_id = 'grr-999';
        component.warehouseReceipts = [mismatchReceipt];
        component.receiptsLoadedSuccessfully = true;

        expect(component.outstandingInTransitLines).toEqual([]);
        expect(component.canComplete).toBeFalse();
      });

      it('restores correct calculation and completion availability after a successful retry', () => {
        mockGoodsReturnService.getGoodsReturn.and.returnValue(
          throwError(() => ({ status: 500, message: 'Server down' }))
        );

        component.loadReturn();
        expect(component.error).toBe('Server down');
        expect(component.canComplete).toBeFalse();

        // Successful retry
        mockGoodsReturnService.getGoodsReturn.and.returnValue(of(fiveAssetReturn));
        mockGoodsReturnService.listWarehouseReceipts.and.returnValue(of([]));

        component.loadReturn();

        expect(component.error).toBeNull();
        expect(component.goodsReturn).toEqual(fiveAssetReturn);
        expect(component.receiptsLoadedSuccessfully).toBeTrue();
        expect(component.outstandingInTransitCount).toBe(5);
        expect(component.canComplete).toBeTrue();
      });

      it('handles closeCompleteModal: closes modal without reloading APIs', () => {
        mockGoodsReturnService.getGoodsReturn.calls.reset();
        mockGoodsReturnService.listWarehouseReceipts.calls.reset();

        component.showCompleteModal = true;
        component.closeCompleteModal();

        expect(component.showCompleteModal).toBeFalse();
        expect(mockGoodsReturnService.getGoodsReturn).not.toHaveBeenCalled();
        expect(mockGoodsReturnService.listWarehouseReceipts).not.toHaveBeenCalled();
      });
    });
  });
});
