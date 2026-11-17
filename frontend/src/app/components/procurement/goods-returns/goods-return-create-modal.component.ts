import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  GoodsReceiptReversalRead,
  GoodsReturn,
  GoodsReturnCreatePayload,
  GoodsReturnService,
  ReturnEligibleAssetItem,
} from '../../../services/goods-return.service';
import { GoodsReceipt } from '../../../services/registry.service';

@Component({
  selector: 'app-goods-return-create-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './goods-return-create-modal.component.html',
  styleUrls: ['./goods-return-create-modal.component.scss'],
})
export class GoodsReturnCreateModalComponent implements OnInit {
  @Input({ required: true }) companyId!: string;
  @Input() initialReceipt?: GoodsReceipt | null;
  @Input() initialReversal?: GoodsReceiptReversalRead | null;
  @Input() availableReceipts: GoodsReceipt[] = [];

  @Output() close = new EventEmitter<void>();
  @Output() returnCreated = new EventEmitter<GoodsReturn>();

  step: 'select_source' | 'select_assets' = 'select_source';

  loadingReceipts = false;
  loadingReversals = false;
  loadingAssets = false;
  submitting = false;

  error: string | null = null;
  conflictWarning: string | null = null;

  selectedReceiptId = '';
  selectedReversalId = '';

  receiptReversals: GoodsReceiptReversalRead[] = [];
  eligibleAssets: ReturnEligibleAssetItem[] = [];

  // Form Fields
  selectedReversalAssetIds = new Set<string>();
  assetConditions: Record<string, string> = {};
  assetNotes: Record<string, string> = {};

  returnDate = new Date().toISOString().slice(0, 10);
  returnReason = '';
  vendorReference = '';
  notes = '';

  constructor(private goodsReturnService: GoodsReturnService) {}

  ngOnInit(): void {
    if (this.initialReversal) {
      this.selectedReversalId = this.initialReversal.id;
      if (this.initialReceipt) {
        this.selectedReceiptId = this.initialReceipt.id;
      }
      this.step = 'select_assets';
      this.loadEligibleAssets(this.selectedReversalId);
    } else if (this.initialReceipt) {
      this.selectedReceiptId = this.initialReceipt.id;
      this.onReceiptSelected();
    }
  }

  get receiptsWithReversals(): GoodsReceipt[] {
    return this.availableReceipts.filter((r) => {
      const reversedCount = (r.lines || []).reduce(
        (sum, l) => sum + (l.quantity_reversed || 0),
        0
      );
      return reversedCount > 0;
    });
  }

  onReceiptSelected(): void {
    if (!this.selectedReceiptId) {
      this.receiptReversals = [];
      this.selectedReversalId = '';
      return;
    }

    this.loadingReversals = true;
    this.error = null;
    this.goodsReturnService
      .listGoodsReceiptReversals(this.companyId, this.selectedReceiptId)
      .subscribe({
        next: (items) => {
          this.loadingReversals = false;
          this.receiptReversals = items || [];
          if (this.receiptReversals.length === 1) {
            this.selectedReversalId = this.receiptReversals[0].id;
          }
        },
        error: (err) => {
          this.loadingReversals = false;
          this.error =
            err.error?.detail || err.message || 'Failed to load reversals for receipt.';
        },
      });
  }

  proceedToAssets(): void {
    if (!this.selectedReversalId) return;
    this.step = 'select_assets';
    this.loadEligibleAssets(this.selectedReversalId);
  }

  backToSource(): void {
    this.step = 'select_source';
  }

  loadEligibleAssets(reversalId: string): void {
    this.loadingAssets = true;
    this.error = null;
    this.goodsReturnService
      .getReturnEligibleAssets(this.companyId, reversalId)
      .subscribe({
        next: (items) => {
          this.loadingAssets = false;
          this.eligibleAssets = items || [];
          // Cleanse any selected IDs that are no longer eligible or active
          const validIds = new Set(
            this.eligibleAssets
              .filter((a) => a.is_eligible && !a.is_actively_reserved)
              .map((a) => a.goods_receipt_reversal_asset_id)
          );
          for (const id of Array.from(this.selectedReversalAssetIds)) {
            if (!validIds.has(id)) {
              this.selectedReversalAssetIds.delete(id);
            }
          }
        },
        error: (err) => {
          this.loadingAssets = false;
          this.error =
            err.error?.detail || err.message || 'Failed to retrieve return eligible assets.';
        },
      });
  }

  get selectableAssetCount(): number {
    return this.eligibleAssets.filter(
      (a) => a.is_eligible && !a.is_actively_reserved
    ).length;
  }

  isAssetSelected(revAssetId: string): boolean {
    return this.selectedReversalAssetIds.has(revAssetId);
  }

  toggleAsset(revAssetId: string): void {
    if (this.selectedReversalAssetIds.has(revAssetId)) {
      this.selectedReversalAssetIds.delete(revAssetId);
    } else {
      this.selectedReversalAssetIds.add(revAssetId);
      if (!this.assetConditions[revAssetId]) {
        this.assetConditions[revAssetId] = 'as_received';
      }
    }
  }

  selectAllEligible(): void {
    const selectable = this.eligibleAssets.filter(
      (a) => a.is_eligible && !a.is_actively_reserved
    );
    if (this.areAllSelectableSelected()) {
      for (const a of selectable) {
        this.selectedReversalAssetIds.delete(a.goods_receipt_reversal_asset_id);
      }
    } else {
      for (const a of selectable) {
        this.selectedReversalAssetIds.add(a.goods_receipt_reversal_asset_id);
        if (!this.assetConditions[a.goods_receipt_reversal_asset_id]) {
          this.assetConditions[a.goods_receipt_reversal_asset_id] = 'as_received';
        }
      }
    }
  }

  areAllSelectableSelected(): boolean {
    const selectable = this.eligibleAssets.filter(
      (a) => a.is_eligible && !a.is_actively_reserved
    );
    if (selectable.length === 0) return false;
    return selectable.every((a) =>
      this.selectedReversalAssetIds.has(a.goods_receipt_reversal_asset_id)
    );
  }

  canSubmit(): boolean {
    return (
      this.selectedReversalAssetIds.size >= 1 &&
      this.returnReason.trim().length >= 1 &&
      !this.submitting
    );
  }

  submitReturn(): void {
    if (!this.canSubmit()) return;

    this.submitting = true;
    this.error = null;
    this.conflictWarning = null;

    const payload: GoodsReturnCreatePayload = {
      goods_receipt_reversal_id: this.selectedReversalId,
      return_date: this.returnDate,
      return_reason: this.returnReason.trim(),
      vendor_reference: this.vendorReference.trim() || null,
      notes: this.notes.trim() || null,
      lines: Array.from(this.selectedReversalAssetIds).map((revAssetId) => ({
        goods_receipt_reversal_asset_id: revAssetId,
        return_condition: this.assetConditions[revAssetId] || 'as_received',
        notes: this.assetNotes[revAssetId]?.trim() || null,
      })),
    };

    this.goodsReturnService.createGoodsReturn(this.companyId, payload).subscribe({
      next: (createdReturn) => {
        this.submitting = false;
        this.returnCreated.emit(createdReturn);
      },
      error: (err) => {
        this.submitting = false;
        if (err.status === 409) {
          const detail =
            err.error?.detail ||
            'One or more selected assets are already actively reserved in another Goods Return.';
          this.conflictWarning = `Reservation Conflict (409): ${detail} Authoritative reservations have been refreshed. Conflicting assets have been deselected. Please review your selection and submit again.`;
          // Authoritative refresh of reservation state
          this.loadEligibleAssets(this.selectedReversalId);
        } else {
          this.error =
            err.error?.detail || err.message || 'Failed to create Goods Return.';
        }
      },
    });
  }

  onClose(): void {
    this.close.emit();
  }
}
