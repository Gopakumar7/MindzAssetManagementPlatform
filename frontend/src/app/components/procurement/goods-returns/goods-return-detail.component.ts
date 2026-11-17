import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, EventEmitter, Input, OnChanges, OnInit, Output, SimpleChanges } from '@angular/core';

import { GoodsReturn, GoodsReturnLine, GoodsReturnService, GoodsReturnWarehouseReceipt, GoodsReturnWarehouseReceiptLine } from '../../../services/goods-return.service';
import { ProcurementSupplier, PurchaseOrder } from '../../../services/registry.service';
import { GoodsReturnCancelModalComponent } from './goods-return-cancel-modal.component';
import { GoodsReturnCompleteModalComponent } from './goods-return-complete-modal.component';
import { GoodsReturnDispatchModalComponent } from './goods-return-dispatch-modal.component';
import { GoodsReturnReceiptCorrectionModalComponent } from './goods-return-receipt-correction-modal.component';
import { GoodsReturnWarehouseReceiptModalComponent } from './goods-return-warehouse-receipt-modal.component';

export interface LifecycleStepInfo {
  key: string;
  label: string;
  branch: 'initiation' | 'vendor_acceptance' | 'warehouse_intake' | 'cancellation';
  description?: string;
  isCurrent: boolean;
  isCompleted: boolean;
  isTerminal: boolean;
  actorId: string | null;
  timestamp: string | null;
}

export type AssetReturnClassification =
  | 'in_transit'
  | 'received_warehouse'
  | 'accepted_vendor'
  | 'draft_reserved'
  | 'approved_pending'
  | 'cancelled';

export interface ClassifiedReturnLine {
  line: GoodsReturnLine;
  classification: AssetReturnClassification;
  classificationLabel: string;
  classificationBadgeClass: string;
  activeReceipt: GoodsReturnWarehouseReceipt | null;
  activeReceiptLine: GoodsReturnWarehouseReceiptLine | null;
  hasCorrection: boolean;
  correctionHistory: {
    receiptNumber: string;
    receiptDate: string;
    receiptLine: GoodsReturnWarehouseReceiptLine;
  }[];
}

@Component({
  selector: 'app-goods-return-detail',
  standalone: true,
  imports: [
    CommonModule,
    GoodsReturnDispatchModalComponent,
    GoodsReturnCancelModalComponent,
    GoodsReturnWarehouseReceiptModalComponent,
    GoodsReturnReceiptCorrectionModalComponent,
    GoodsReturnCompleteModalComponent,
  ],
  templateUrl: './goods-return-detail.component.html',
  styleUrls: ['./goods-return-detail.component.scss'],
  changeDetection: ChangeDetectionStrategy.Eager,
})
export class GoodsReturnDetailComponent implements OnInit, OnChanges {
  @Input({ required: true }) companyId!: string;
  @Input({ required: true }) returnId!: string;
  @Input() currentUserId: string | null = null;
  @Input() canManage = false;
  @Input() canRead = true;
  @Input() suppliers: ProcurementSupplier[] = [];
  @Input() purchaseOrders: PurchaseOrder[] = [];

  @Output() back = new EventEmitter<void>();
  @Output() returnUpdated = new EventEmitter<GoodsReturn>();

  goodsReturn: GoodsReturn | null = null;
  warehouseReceipts: GoodsReturnWarehouseReceipt[] = [];
  loading = false;
  loadingReceipts = false;
  receiptsLoadedSuccessfully = false;
  error: string | null = null;
  receiptsError: string | null = null;
  actionMessage: string | null = null;
  actionError: string | null = null;
  expandedReceiptIds = new Set<string>();

  policyStrictApproval = true;
  loadingSettings = false;

  showDispatchModal = false;
  showCancelModal = false;
  showWarehouseReceiptModal = false;
  showCorrectionModal = false;
  showCompleteModal = false;
  selectedReceiptForCorrection: GoodsReturnWarehouseReceipt | null = null;
  selectedLineForCorrection: GoodsReturnWarehouseReceiptLine | null = null;
  confirmLineRemovalId: string | null = null;
  removingLine = false;
  approving = false;

  currentReturnRequestId = 0;
  currentReceiptsRequestId = 0;
  loadedReturnId: string | null = null;
  loadedReturnCompanyId: string | null = null;
  loadedReceiptsReturnId: string | null = null;
  loadedReceiptsCompanyId: string | null = null;

  readonly canonicalStates = [
    'draft',
    'approved',
    'dispatched',
    'partially_returned_to_warehouse',
    'returned_to_warehouse',
    'completed',
    'cancelled',
  ] as const;

  constructor(
    private goodsReturnService: GoodsReturnService,
    private changeDetector: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    if (this.companyId && this.returnId && this.canRead) {
      this.loadReturn();
      this.loadSettings();
    }
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (
      (changes['companyId'] && !changes['companyId'].firstChange) ||
      (changes['returnId'] && !changes['returnId'].firstChange)
    ) {
      this.actionMessage = null;
      this.actionError = null;
      this.confirmLineRemovalId = null;
      this.goodsReturn = null as any;
      this.warehouseReceipts = [];
      this.receiptsLoadedSuccessfully = false;
      this.loadedReturnId = null;
      this.loadedReturnCompanyId = null;
      this.loadedReceiptsReturnId = null;
      this.loadedReceiptsCompanyId = null;
      this.loadReturn();
      this.loadSettings();
    }
  }

  loadReturn(): void {
    if (!this.companyId || !this.returnId || !this.canRead) return;
    const reqCompanyId = this.companyId;
    const reqReturnId = this.returnId;
    const requestId = ++this.currentReturnRequestId;
    ++this.currentReceiptsRequestId;
    this.loading = true;
    this.error = null;
    this.goodsReturn = null as any;
    this.loadedReturnId = null;
    this.loadedReturnCompanyId = null;
    this.warehouseReceipts = [];
    this.receiptsLoadedSuccessfully = false;
    this.loadedReceiptsReturnId = null;
    this.loadedReceiptsCompanyId = null;

    this.goodsReturnService.getGoodsReturn(reqCompanyId, reqReturnId).subscribe({
      next: (grr) => {
        if (
          requestId !== this.currentReturnRequestId ||
          this.companyId !== reqCompanyId ||
          this.returnId !== reqReturnId
        ) {
          return;
        }
        this.loading = false;
        this.goodsReturn = grr;
        this.loadedReturnId = reqReturnId;
        this.loadedReturnCompanyId = reqCompanyId;
        this.loadWarehouseReceipts();
        this.changeDetector.markForCheck();
      },
      error: (err) => {
        if (
          requestId !== this.currentReturnRequestId ||
          this.companyId !== reqCompanyId ||
          this.returnId !== reqReturnId
        ) {
          return;
        }
        this.loading = false;
        this.goodsReturn = null as any;
        this.warehouseReceipts = [];
        this.receiptsLoadedSuccessfully = false;
        this.loadedReturnId = null;
        this.loadedReturnCompanyId = null;
        this.loadedReceiptsReturnId = null;
        this.loadedReceiptsCompanyId = null;
        this.error = err.error?.detail || err.message || 'Failed to load Goods Return details.';
        this.changeDetector.markForCheck();
      },
    });
  }

  loadWarehouseReceipts(): void {
    if (!this.companyId || !this.returnId || !this.canRead) return;
    const reqCompanyId = this.companyId;
    const reqReturnId = this.returnId;
    const requestId = ++this.currentReceiptsRequestId;
    this.loadingReceipts = true;
    this.receiptsError = null;
    this.receiptsLoadedSuccessfully = false;
    this.loadedReceiptsReturnId = null;
    this.loadedReceiptsCompanyId = null;

    this.goodsReturnService.listWarehouseReceipts(reqCompanyId, reqReturnId).subscribe({
      next: (receipts) => {
        if (
          requestId !== this.currentReceiptsRequestId ||
          this.companyId !== reqCompanyId ||
          this.returnId !== reqReturnId
        ) {
          return;
        }
        this.loadingReceipts = false;
        if (this.error !== null || !this.goodsReturn) {
          this.receiptsLoadedSuccessfully = false;
          this.warehouseReceipts = [];
          return;
        }
        this.warehouseReceipts = receipts || [];
        this.receiptsLoadedSuccessfully = true;
        this.loadedReceiptsReturnId = reqReturnId;
        this.loadedReceiptsCompanyId = reqCompanyId;
        this.expandedReceiptIds = new Set(this.warehouseReceipts.map((r) => r.id));
        this.changeDetector.markForCheck();
      },
      error: (err) => {
        if (
          requestId !== this.currentReceiptsRequestId ||
          this.companyId !== reqCompanyId ||
          this.returnId !== reqReturnId
        ) {
          return;
        }
        this.loadingReceipts = false;
        this.receiptsLoadedSuccessfully = false;
        this.loadedReceiptsReturnId = null;
        this.loadedReceiptsCompanyId = null;
        this.receiptsError =
          err.error?.detail || err.message || 'Failed to load warehouse receipt history.';
        this.changeDetector.markForCheck();
      },
    });
  }

  toggleReceiptExpanded(receiptId: string): void {
    if (this.expandedReceiptIds.has(receiptId)) {
      this.expandedReceiptIds.delete(receiptId);
    } else {
      this.expandedReceiptIds.add(receiptId);
    }
    this.changeDetector.markForCheck();
  }

  isReceiptExpanded(receiptId: string): boolean {
    return this.expandedReceiptIds.has(receiptId);
  }

  hasReceiptCorrections(receipt: GoodsReturnWarehouseReceipt): boolean {
    return (receipt.lines || []).some((l) => l.is_corrected);
  }

  getAssetNumberForLine(goodsReturnLineId: string): string {
    const line = this.goodsReturn?.lines.find((l) => l.id === goodsReturnLineId);
    return line?.asset_number || 'AST-N/A';
  }

  getSerialNumberForLine(goodsReturnLineId: string): string | null {
    const line = this.goodsReturn?.lines.find((l) => l.id === goodsReturnLineId);
    return line?.serial_number || null;
  }

  get canCorrectReceiptLine(): boolean {
    const s = this.goodsReturn?.status;
    return this.canManage && !!s && s !== 'completed' && s !== 'cancelled';
  }

  get classifiedLines(): ClassifiedReturnLine[] {
    if (!this.goodsReturn || !this.goodsReturn.lines) return [];
    const grr = this.goodsReturn;
    const receipts = this.warehouseReceipts || [];

    const activeReceiptMap = new Map<
      string,
      { receipt: GoodsReturnWarehouseReceipt; line: GoodsReturnWarehouseReceiptLine }
    >();

    const correctionHistoryMap = new Map<
      string,
      { receiptNumber: string; receiptDate: string; receiptLine: GoodsReturnWarehouseReceiptLine }[]
    >();

    for (const receipt of receipts) {
      for (const rLine of receipt.lines || []) {
        if (rLine.is_corrected) {
          const history = correctionHistoryMap.get(rLine.goods_return_line_id) || [];
          history.push({
            receiptNumber: receipt.receipt_number,
            receiptDate: receipt.receipt_date,
            receiptLine: rLine,
          });
          correctionHistoryMap.set(rLine.goods_return_line_id, history);
        } else {
          activeReceiptMap.set(rLine.goods_return_line_id, { receipt, line: rLine });
        }
      }
    }

    return grr.lines.map((line) => {
      const active = activeReceiptMap.get(line.id) || null;
      const history = correctionHistoryMap.get(line.id) || [];
      const hasCorrection = history.length > 0;

      let classification: AssetReturnClassification;
      let classificationLabel: string;
      let classificationBadgeClass: string;

      if (active !== null) {
        classification = 'received_warehouse';
        classificationLabel = 'Received in Warehouse';
        classificationBadgeClass = 'badge-warehouse-received';
      } else {
        switch (grr.status) {
          case 'dispatched':
          case 'partially_returned_to_warehouse':
            classification = 'in_transit';
            classificationLabel = 'In Transit';
            classificationBadgeClass = 'badge-in-transit';
            break;

          case 'returned_to_warehouse':
            classification = 'received_warehouse';
            classificationLabel = 'Received in Warehouse';
            classificationBadgeClass = 'badge-warehouse-received';
            break;

          case 'completed':
            classification = 'accepted_vendor';
            classificationLabel = 'Accepted by Vendor';
            classificationBadgeClass = 'badge-vendor-accepted';
            break;

          case 'draft':
            classification = 'draft_reserved';
            classificationLabel = 'Draft (Reserved)';
            classificationBadgeClass = 'badge-draft';
            break;

          case 'approved':
            classification = 'approved_pending';
            classificationLabel = 'Approved (Pending Dispatch)';
            classificationBadgeClass = 'badge-approved';
            break;

          case 'cancelled':
            classification = 'cancelled';
            classificationLabel = 'Cancelled';
            classificationBadgeClass = 'badge-cancelled';
            break;

          default:
            classification = 'in_transit';
            classificationLabel = 'In Transit';
            classificationBadgeClass = 'badge-in-transit';
            break;
        }
      }

      return {
        line,
        classification,
        classificationLabel,
        classificationBadgeClass,
        activeReceipt: active ? active.receipt : null,
        activeReceiptLine: active ? active.line : null,
        hasCorrection,
        correctionHistory: history,
      };
    });
  }

  get lineCountsSummary() {
    const lines = this.classifiedLines;
    return {
      total: lines.length,
      inTransit: lines.filter((l) => l.classification === 'in_transit').length,
      receivedWarehouse: lines.filter((l) => l.classification === 'received_warehouse').length,
      acceptedVendor: lines.filter((l) => l.classification === 'accepted_vendor').length,
      corrected: lines.filter((l) => l.hasCorrection).length,
    };
  }

  loadSettings(): void {
    if (!this.companyId) return;
    this.loadingSettings = true;
    this.goodsReturnService.getCompanySettings(this.companyId).subscribe({
      next: (settings) => {
        this.loadingSettings = false;
        if (settings && typeof settings['procurement_different_person_return_approval'] === 'boolean') {
          this.policyStrictApproval = settings['procurement_different_person_return_approval'];
        } else {
          this.policyStrictApproval = true; // safe default
        }
        this.changeDetector.markForCheck();
      },
      error: () => {
        this.loadingSettings = false;
        this.policyStrictApproval = true; // safe default on error/forbidden
        this.changeDetector.markForCheck();
      },
    });
  }

  get isCreator(): boolean {
    if (!this.goodsReturn || !this.currentUserId) return false;
    return this.goodsReturn.created_by_id === this.currentUserId;
  }

  get isSelfApprovalBlocked(): boolean {
    return this.policyStrictApproval && this.isCreator;
  }

  get canApprove(): boolean {
    return (
      this.goodsReturn?.status === 'draft' &&
      this.canManage &&
      !this.isSelfApprovalBlocked &&
      !this.approving
    );
  }

  get canRemoveLines(): boolean {
    return this.goodsReturn?.status === 'draft' && this.canManage;
  }

  get canDispatch(): boolean {
    return this.goodsReturn?.status === 'approved' && this.canManage;
  }

  get canCancel(): boolean {
    const s = this.goodsReturn?.status;
    return (s === 'draft' || s === 'approved') && this.canManage;
  }

  get eligibleInTransitAssetsCount(): number {
    return this.classifiedLines.filter((l) => {
      if (l.classification !== 'in_transit') return false;
      if (l.line.asset_status && l.line.asset_status !== 'return_pending') return false;
      return true;
    }).length;
  }

  get canReceiveWarehouse(): boolean {
    const s = this.goodsReturn?.status;
    return (
      (s === 'dispatched' || s === 'partially_returned_to_warehouse') &&
      this.canManage &&
      this.eligibleInTransitAssetsCount > 0
    );
  }

  get outstandingInTransitLines(): GoodsReturnLine[] {
    if (
      !this.goodsReturn ||
      this.goodsReturn.id !== this.returnId ||
      this.goodsReturn.company_id !== this.companyId ||
      (this.loadedReturnId !== null && this.loadedReturnId !== this.returnId) ||
      (this.loadedReturnCompanyId !== null && this.loadedReturnCompanyId !== this.companyId) ||
      (this.loadedReceiptsReturnId !== null && this.loadedReceiptsReturnId !== this.returnId) ||
      (this.loadedReceiptsCompanyId !== null && this.loadedReceiptsCompanyId !== this.companyId) ||
      this.loading ||
      this.loadingReceipts ||
      this.error !== null ||
      this.receiptsError !== null ||
      !this.receiptsLoadedSuccessfully
    ) {
      return [];
    }

    const activeReturnedLineIds = new Set<string>();
    for (const receipt of this.warehouseReceipts || []) {
      if (receipt.goods_return_id !== this.returnId || receipt.company_id !== this.companyId) {
        return [];
      }
      for (const rLine of receipt.lines || []) {
        if (!rLine.is_corrected) {
          activeReturnedLineIds.add(rLine.goods_return_line_id);
        }
      }
    }

    return (this.goodsReturn.lines || []).filter(
      (line) => !activeReturnedLineIds.has(line.id)
    );
  }

  get outstandingInTransitCount(): number {
    return this.outstandingInTransitLines.length;
  }

  get canComplete(): boolean {
    const s = this.goodsReturn?.status;
    return (
      this.canManage &&
      !this.loading &&
      !this.loadingReceipts &&
      this.receiptsLoadedSuccessfully &&
      !this.receiptsError &&
      !this.error &&
      this.goodsReturn !== null &&
      this.goodsReturn !== undefined &&
      this.goodsReturn.id === this.returnId &&
      this.goodsReturn.company_id === this.companyId &&
      (this.loadedReturnId === null || this.loadedReturnId === this.returnId) &&
      (this.loadedReturnCompanyId === null || this.loadedReturnCompanyId === this.companyId) &&
      (this.loadedReceiptsReturnId === null || this.loadedReceiptsReturnId === this.returnId) &&
      (this.loadedReceiptsCompanyId === null || this.loadedReceiptsCompanyId === this.companyId) &&
      (s === 'dispatched' || s === 'partially_returned_to_warehouse') &&
      this.outstandingInTransitCount > 0
    );
  }

  supplierName(supplierId?: string | null): string {
    if (!supplierId) return '—';
    const s = this.suppliers.find((sup) => sup.id === supplierId);
    return s ? `${s.name} (${s.code})` : 'Unknown Supplier';
  }

  purchaseOrderNumber(poId?: string | null): string {
    if (!poId) return '—';
    const po = this.purchaseOrders.find((p) => p.id === poId);
    return po ? po.order_number : '—';
  }

  get initiationSteps(): LifecycleStepInfo[] {
    if (!this.goodsReturn) return [];
    const s = this.goodsReturn.status;
    return [
      {
        key: 'draft',
        label: '1. Draft',
        branch: 'initiation',
        description: 'Preparation & asset reservation',
        isCurrent: s === 'draft',
        isCompleted: s !== 'draft',
        isTerminal: false,
        actorId: this.goodsReturn.created_by_id || null,
        timestamp: this.goodsReturn.created_at || null,
      },
      {
        key: 'approved',
        label: '2. Approved',
        branch: 'initiation',
        description: 'Segregation-of-duties authorized',
        isCurrent: s === 'approved',
        isCompleted: !!this.goodsReturn.approved_at && s !== 'approved' && s !== 'draft',
        isTerminal: false,
        actorId: this.goodsReturn.approved_by_id || null,
        timestamp: this.goodsReturn.approved_at || null,
      },
      {
        key: 'dispatched',
        label: '3. Dispatched',
        branch: 'initiation',
        description: 'Carrier in-transit',
        isCurrent: s === 'dispatched',
        isCompleted: !!this.goodsReturn.dispatched_at && !['draft', 'approved', 'dispatched'].includes(s),
        isTerminal: false,
        actorId: this.goodsReturn.dispatched_by_id || null,
        timestamp: this.goodsReturn.dispatched_at || null,
      },
    ];
  }

  get vendorAcceptanceStep(): LifecycleStepInfo {
    const s = this.goodsReturn?.status;
    return {
      key: 'completed',
      label: 'Vendor Acceptance (Completed)',
      branch: 'vendor_acceptance',
      description: 'In-transit items acknowledged by vendor; return terminal',
      isCurrent: s === 'completed',
      isCompleted: s === 'completed',
      isTerminal: true,
      actorId: this.goodsReturn?.completed_by_id || null,
      timestamp: this.goodsReturn?.completed_at || null,
    };
  }

  get warehouseIntakeSteps(): LifecycleStepInfo[] {
    const s = this.goodsReturn?.status;
    return [
      {
        key: 'partially_returned_to_warehouse',
        label: 'Partial Warehouse Return',
        branch: 'warehouse_intake',
        description: 'Subset of lines received into warehouse inventory',
        isCurrent: s === 'partially_returned_to_warehouse',
        isCompleted: false,
        isTerminal: false,
        actorId: null,
        timestamp: null,
      },
      {
        key: 'returned_to_warehouse',
        label: 'Returned to Warehouse',
        branch: 'warehouse_intake',
        description: 'All lines received into warehouse; physical fulfillment complete',
        isCurrent: s === 'returned_to_warehouse',
        isCompleted: false,
        isTerminal: true,
        actorId: null,
        timestamp: null,
      },
    ];
  }

  get cancellationStep(): LifecycleStepInfo {
    const s = this.goodsReturn?.status;
    return {
      key: 'cancelled',
      label: 'Cancelled (Terminal)',
      branch: 'cancellation',
      description: 'Return aborted; asset reservations released',
      isCurrent: s === 'cancelled',
      isCompleted: s === 'cancelled',
      isTerminal: true,
      actorId: this.goodsReturn?.cancelled_by_id || null,
      timestamp: this.goodsReturn?.cancelled_at || null,
    };
  }

  get lifecycleSteps(): LifecycleStepInfo[] {
    if (!this.goodsReturn) return [];
    return [
      ...this.initiationSteps,
      this.vendorAcceptanceStep,
      ...this.warehouseIntakeSteps,
      this.cancellationStep,
    ];
  }

  // --- Line Removal Workflow ---
  promptRemoveLine(lineId: string): void {
    if (!this.canRemoveLines) return;
    this.confirmLineRemovalId = lineId;
    this.actionMessage = null;
    this.actionError = null;
  }

  cancelRemoveLine(): void {
    this.confirmLineRemovalId = null;
  }

  executeRemoveLine(lineId: string): void {
    if (!this.canRemoveLines || !this.goodsReturn) return;

    this.removingLine = true;
    this.actionError = null;
    this.actionMessage = null;

    this.goodsReturnService.deselectReturnLine(this.companyId, this.goodsReturn.id, lineId).subscribe({
      next: (updatedReturn) => {
        this.removingLine = false;
        this.confirmLineRemovalId = null;
        this.goodsReturn = updatedReturn;
        this.actionMessage = 'Line removed from return and active reservation released.';
        this.returnUpdated.emit(updatedReturn);
      },
      error: (err) => {
        this.removingLine = false;
        this.confirmLineRemovalId = null;
        this.actionError = err.error?.detail || err.message || 'Failed to remove return line. Server state refreshed.';
        this.loadReturn();
      },
    });
  }

  // --- Approval Workflow ---
  onApprove(): void {
    if (!this.canApprove || !this.goodsReturn) return;

    this.approving = true;
    this.actionError = null;
    this.actionMessage = null;

    this.goodsReturnService.approveGoodsReturn(this.companyId, this.goodsReturn.id).subscribe({
      next: (updatedReturn) => {
        this.approving = false;
        this.goodsReturn = updatedReturn;
        this.actionMessage = 'Goods Return approved successfully.';
        this.returnUpdated.emit(updatedReturn);
      },
      error: (err) => {
        this.approving = false;
        if (err.status === 403) {
          this.actionError =
            err.error?.detail || 'Approval rejected: Segregation of duties policy prohibits self-approval.';
        } else if (err.status === 409) {
          this.actionError =
            err.error?.detail || 'Conflict approving Goods Return. The return status has changed.';
          this.loadReturn();
        } else {
          this.actionError = err.error?.detail || err.message || 'Failed to approve Goods Return.';
        }
      },
    });
  }

  // --- Dispatch Workflow ---
  openDispatchModal(): void {
    if (!this.canDispatch) return;
    this.showDispatchModal = true;
  }

  onDispatched(updated: GoodsReturn): void {
    this.showDispatchModal = false;
    this.goodsReturn = updated;
    this.actionMessage = `Goods Return ${updated.return_number} successfully dispatched. Carrier ref: ${updated.dispatch_reference || 'N/A'}`;
    this.returnUpdated.emit(updated);
  }

  // --- Cancel Workflow ---
  openCancelModal(): void {
    if (!this.canCancel) return;
    this.showCancelModal = true;
  }

  onCancelled(updated: GoodsReturn): void {
    this.showCancelModal = false;
    this.goodsReturn = updated;
    this.actionMessage = `Goods Return ${updated.return_number} has been cancelled. Asset reservations released.`;
    this.returnUpdated.emit(updated);
  }

  // --- Warehouse Receipt Intake Workflow ---
  openWarehouseReceiptModal(): void {
    if (!this.canReceiveWarehouse) return;
    this.showWarehouseReceiptModal = true;
  }

  onReceiptCreated(receipt: GoodsReturnWarehouseReceipt): void {
    this.showWarehouseReceiptModal = false;
    this.actionMessage = `Warehouse Receipt ${receipt.receipt_number} recorded successfully (${receipt.lines.length} item(s) received into warehouse stock).`;
    this.actionError = null;
    this.loadReturn();
    this.loadWarehouseReceipts();
  }

  onReceiptConflict(): void {
    this.loadReturn();
    this.loadWarehouseReceipts();
  }

  // --- Warehouse Receipt Correction Workflow ---
  openCorrectionModal(
    receipt: GoodsReturnWarehouseReceipt,
    line: GoodsReturnWarehouseReceiptLine
  ): void {
    if (!this.canCorrectReceiptLine || line.is_corrected) return;
    this.selectedReceiptForCorrection = receipt;
    this.selectedLineForCorrection = line;
    this.showCorrectionModal = true;
  }

  onCorrectionComplete(updatedReceipt: GoodsReturnWarehouseReceipt): void {
    const assetNum = this.selectedLineForCorrection
      ? this.getAssetNumberForLine(this.selectedLineForCorrection.goods_return_line_id)
      : 'asset';
    this.showCorrectionModal = false;
    this.selectedReceiptForCorrection = null;
    this.selectedLineForCorrection = null;
    this.actionMessage = `Receipt intake for ${assetNum} corrected successfully. Return lifecycle and reservations updated.`;
    this.actionError = null;
    this.loadReturn();
    this.loadWarehouseReceipts();
  }

  onCorrectionConflict(): void {
    this.loadReturn();
    this.loadWarehouseReceipts();
  }

  closeCorrectionModal(): void {
    this.showCorrectionModal = false;
    this.selectedReceiptForCorrection = null;
    this.selectedLineForCorrection = null;
  }

  // --- Vendor Acceptance / Completion Workflow ---
  openCompleteModal(): void {
    if (!this.canComplete) return;
    this.showCompleteModal = true;
  }

  closeCompleteModal(): void {
    this.showCompleteModal = false;
  }

  deriveAuthoritativeAcceptedCount(updatedReturn: GoodsReturn): number | null {
    if (!updatedReturn) return null;

    const anyReturn = updatedReturn as any;
    if (typeof anyReturn.completed_lines_count === 'number') {
      return anyReturn.completed_lines_count;
    }
    if (typeof anyReturn.completed_assets_count === 'number') {
      return anyReturn.completed_assets_count;
    }

    if (Array.isArray(updatedReturn.lines) && updatedReturn.lines.length > 0) {
      const vendorAcceptedLines = updatedReturn.lines.filter(
        (l: any) =>
          l.status === 'returned_to_vendor' ||
          l.asset_status === 'returned_to_vendor' ||
          l.lifecycle_status === 'returned_to_vendor'
      );
      if (vendorAcceptedLines.length > 0) {
        return vendorAcceptedLines.length;
      }
    }

    return null;
  }

  onCompleted(updatedReturn: GoodsReturn): void {
    this.showCompleteModal = false;
    this.goodsReturn = updatedReturn;
    this.actionError = null;

    const verifiedCount = this.deriveAuthoritativeAcceptedCount(updatedReturn);
    if (verifiedCount !== null) {
      this.actionMessage = `Goods Return ${updatedReturn.return_number} has been completed. ${verifiedCount} asset(s) marked as accepted by vendor.`;
    } else {
      this.actionMessage = `Goods Return ${updatedReturn.return_number} has been completed successfully. Vendor acceptance recorded.`;
    }

    this.loadReturn();
    this.loadWarehouseReceipts();
    this.returnUpdated.emit(updatedReturn);
  }

  onCompleteConflict(): void {
    this.loadReturn();
    this.loadWarehouseReceipts();
  }

  onCompleteNotFound(): void {
    this.loadReturn();
    this.loadWarehouseReceipts();
  }

  onBack(): void {
    this.back.emit();
  }
}
