import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  EventEmitter,
  HostListener,
  Input,
  OnChanges,
  OnInit,
  Output,
  SimpleChanges,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  GoodsReturn,
  GoodsReturnService,
  GoodsReturnWarehouseReceipt,
  WarehouseReceiptCreatePayload,
} from '../../../services/goods-return.service';
import { formatLocalCalendarDate } from '../../../utils/date.utils';

export interface EligibleAssetRow {
  lineId: string;
  assetId: string;
  assetNumber: string;
  serialNumber: string | null;
  returnCondition: string;
  conditionOnReturn: string;
  notes: string;
  selected: boolean;
  assetStatus?: string | null;
}

@Component({
  selector: 'app-goods-return-warehouse-receipt-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './goods-return-warehouse-receipt-modal.component.html',
  styleUrls: ['./goods-return-warehouse-receipt-modal.component.scss'],
  changeDetection: ChangeDetectionStrategy.Eager,
})
export class GoodsReturnWarehouseReceiptModalComponent implements OnInit, OnChanges {
  @Input({ required: true }) companyId!: string;
  @Input({ required: true }) goodsReturn!: GoodsReturn;
  @Input() warehouseReceipts: GoodsReturnWarehouseReceipt[] = [];

  @Output() receiptCreated = new EventEmitter<GoodsReturnWarehouseReceipt>();
  @Output() conflictOccurred = new EventEmitter<void>();
  @Output() close = new EventEmitter<void>();

  receiptDate = '';
  reason = '';
  dispatchReference = '';
  warehouseLocationId = '';
  notes = '';
  confirmed = false;

  eligibleAssets: EligibleAssetRow[] = [];

  submitting = false;
  error: string | null = null;
  validationError: string | null = null;

  constructor(
    private goodsReturnService: GoodsReturnService,
    private changeDetector: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.receiptDate = formatLocalCalendarDate();
    this.dispatchReference = this.goodsReturn?.dispatch_reference || '';
    this.initEligibleAssets();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['goodsReturn'] || changes['warehouseReceipts']) {
      this.initEligibleAssets();
    }
  }

  @HostListener('keydown.escape', ['$event'])
  onEscape(event?: Event): void {
    if (event) {
      event.stopPropagation();
    }
    if (!this.submitting) {
      this.onClose();
    }
  }

  initEligibleAssets(): void {
    if (!this.goodsReturn || !this.goodsReturn.lines) {
      this.eligibleAssets = [];
      return;
    }

    // Eligibility check 1: Parent GRR status must be 'dispatched' or 'partially_returned_to_warehouse'
    const isStateEligible =
      this.goodsReturn.status === 'dispatched' ||
      this.goodsReturn.status === 'partially_returned_to_warehouse';

    if (!isStateEligible) {
      this.eligibleAssets = [];
      this.changeDetector.markForCheck();
      return;
    }

    const activeReceiptLineMap = new Map<string, boolean>();
    for (const receipt of this.warehouseReceipts || []) {
      for (const rLine of receipt.lines || []) {
        if (!rLine.is_corrected) {
          activeReceiptLineMap.set(rLine.goods_return_line_id, true);
        }
      }
    }

    const previousStateMap = new Map<string, { selected: boolean; conditionOnReturn: string; notes: string }>();
    for (const row of this.eligibleAssets) {
      previousStateMap.set(row.lineId, {
        selected: row.selected,
        conditionOnReturn: row.conditionOnReturn,
        notes: row.notes,
      });
    }

    // Eligibility check 2 & 3:
    // - Must not already have an active uncorrected warehouse receipt line
    // - If underlying asset_status is available, verify it is 'return_pending'
    // NOTE: The current backend GoodsReturnLineRead response does not serialize underlying asset.status.
    // The backend POST endpoint is authoritative and enforces asset.status == 'return_pending' at transaction commit time.
    this.eligibleAssets = this.goodsReturn.lines
      .filter((line) => {
        if (activeReceiptLineMap.has(line.id)) {
          return false;
        }
        if (line.asset_status && line.asset_status !== 'return_pending') {
          return false;
        }
        return true;
      })
      .map((line) => {
        const prev = previousStateMap.get(line.id);
        return {
          lineId: line.id,
          assetId: line.asset_id,
          assetNumber: line.asset_number || 'AST-N/A',
          serialNumber: line.serial_number || null,
          returnCondition: line.return_condition || 'as_received',
          conditionOnReturn: prev?.conditionOnReturn || 'intact',
          notes: prev?.notes || '',
          selected: prev !== undefined ? prev.selected : true,
          assetStatus: line.asset_status,
        };
      });

    this.changeDetector.markForCheck();
  }

  selectAll(): void {
    for (const item of this.eligibleAssets) {
      item.selected = true;
    }
    this.changeDetector.markForCheck();
  }

  deselectAll(): void {
    for (const item of this.eligibleAssets) {
      item.selected = false;
    }
    this.changeDetector.markForCheck();
  }

  get selectedCount(): number {
    return this.eligibleAssets.filter((a) => a.selected).length;
  }

  get totalEligibleCount(): number {
    return this.eligibleAssets.length;
  }

  get isFormValid(): boolean {
    return (
      !this.submitting &&
      this.receiptDate.trim().length > 0 &&
      this.reason.trim().length >= 3 &&
      this.selectedCount >= 1 &&
      this.confirmed
    );
  }

  onSubmit(): void {
    if (!this.isFormValid) {
      if (this.selectedCount === 0) {
        this.validationError = 'Please select at least one asset to receive into the warehouse.';
      } else if (this.reason.trim().length < 3) {
        this.validationError = 'Reason is mandatory (minimum 3 characters).';
      } else if (!this.confirmed) {
        this.validationError = 'Please confirm physical receipt and inspection before submitting.';
      }
      return;
    }

    this.validationError = null;
    this.submitting = true;
    this.error = null;

    const selectedRows = this.eligibleAssets.filter((a) => a.selected);
    const payload: WarehouseReceiptCreatePayload = {
      receipt_date: this.receiptDate.trim(),
      reason: this.reason.trim(),
      dispatch_reference: this.dispatchReference.trim() || null,
      warehouse_location_id: this.warehouseLocationId.trim() || null,
      notes: this.notes.trim() || null,
      lines: selectedRows.map((row) => ({
        goods_return_line_id: row.lineId,
        condition_on_return: row.conditionOnReturn.trim() || 'intact',
        notes: row.notes.trim() || null,
      })),
    };

    this.goodsReturnService
      .createWarehouseReceipt(this.companyId, this.goodsReturn.id, payload)
      .subscribe({
        next: (receipt) => {
          this.submitting = false;
          this.changeDetector.markForCheck();
          this.receiptCreated.emit(receipt);
        },
        error: (err) => {
          this.submitting = false;
          const detail = typeof err.error?.detail === 'string' ? err.error.detail : null;

          if (err.status === 400) {
            // Distinguish asset-status mismatch from generic request-validation errors.
            // Backend contract (goods_return_service.py):
            // f"Asset '{asset.asset_number}' has status '{asset.status}', expected 'return_pending'"
            const isAssetStatusError =
              detail !== null && detail.toLowerCase().includes('return_pending');

            if (isAssetStatusError) {
              // 1. Asset-status mismatch (stale asset lifecycle condition):
              // Display backend message, clear selected assets, reset confirmation,
              // and trigger authoritative server refresh. Safe header metadata is preserved.
              this.error =
                detail ||
                "Asset status validation failed: One or more selected assets are no longer in 'return_pending' status.";
              this.confirmed = false;
              for (const asset of this.eligibleAssets) {
                asset.selected = false;
              }
              this.conflictOccurred.emit();
            } else {
              // 2. Generic HTTP 400 validation error (e.g. malformed field, business validation):
              // Display backend validation message, preserve selected assets, preserve
              // confirmation, preserve header metadata, and do NOT trigger conflict refresh.
              this.error =
                detail ||
                'Validation error recording warehouse receipt. Please verify receipt details.';
            }
          } else if (err.status === 409) {
            // 3. HTTP 409 Concurrency conflict (stale return or already-received line):
            this.error =
              detail ||
              'Conflict recording warehouse receipt. Return status or asset eligibility has changed on the server. Active assets have been refreshed.';
            this.confirmed = false;
            for (const asset of this.eligibleAssets) {
              asset.selected = false;
            }
            this.conflictOccurred.emit();
          } else if (err.status === 403) {
            this.error =
              detail ||
              'Permission denied. Recording warehouse receipts requires procurement.manage permission.';
          } else if (err.status === 422) {
            this.error =
              detail ||
              'Invalid submission. Please verify that receipt date, reason, and lines are valid.';
          } else {
            this.error =
              detail ||
              err.message ||
              'Failed to record warehouse receipt. Please try again.';
          }
          this.changeDetector.markForCheck();
        },
      });
  }

  onClose(): void {
    if (this.submitting) return;
    this.close.emit();
  }
}
