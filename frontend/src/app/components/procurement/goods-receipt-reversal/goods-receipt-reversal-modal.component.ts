import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  AssetEligibilityCheckItem,
  GoodsReceiptReversalCreate,
  GoodsReceiptReversalEligibilityResponse,
  GoodsReceiptReversalRead,
  GoodsReturnService,
  ReversalLineItem,
} from '../../../services/goods-return.service';
import { GoodsReceipt } from '../../../services/registry.service';

@Component({
  selector: 'app-goods-receipt-reversal-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './goods-receipt-reversal-modal.component.html',
  styleUrls: ['./goods-receipt-reversal-modal.component.scss'],
})
export class GoodsReceiptReversalModalComponent implements OnInit {
  @Input({ required: true }) companyId!: string;
  @Input({ required: true }) receipt!: GoodsReceipt;

  @Output() close = new EventEmitter<void>();
  @Output() reversalCompleted = new EventEmitter<GoodsReceiptReversalRead>();

  loading = true;
  submitting = false;
  error: string | null = null;
  checkResult: GoodsReceiptReversalEligibilityResponse | null = null;

  selectedAssetIds = new Set<string>();
  reversalReason = '';
  lineNotes: Record<string, string> = {};
  assetLineMap = new Map<string, string>();
  eligibleAssetIds: string[] = [];

  constructor(private goodsReturnService: GoodsReturnService) {}

  ngOnInit(): void {
    this.buildAssetLineMap();
    this.loadEligibilityCheck();
  }

  buildAssetLineMap(): void {
    if (this.receipt?.lines) {
      for (const line of this.receipt.lines) {
        if (line.assets) {
          for (const asset of line.assets) {
            this.assetLineMap.set(asset.id, line.id);
          }
        }
      }
    }
  }

  loadEligibilityCheck(): void {
    this.loading = true;
    this.error = null;
    this.goodsReturnService
      .getGoodsReceiptReversalCheck(this.companyId, this.receipt.id)
      .subscribe({
        next: (result) => {
          this.loading = false;
          this.checkResult = result;
          this.eligibleAssetIds = result.assets
            .filter((a) => a.is_eligible)
            .map((a) => a.asset_id);
        },
        error: (err) => {
          this.loading = false;
          this.error =
            err.error?.detail || err.message || 'Failed to check reversal eligibility.';
        },
      });
  }

  isAssetSelected(assetId: string): boolean {
    return this.selectedAssetIds.has(assetId);
  }

  toggleAsset(assetId: string): void {
    if (this.selectedAssetIds.has(assetId)) {
      this.selectedAssetIds.delete(assetId);
    } else {
      this.selectedAssetIds.add(assetId);
    }
  }

  selectAllEligible(): void {
    if (this.areAllEligibleSelected()) {
      for (const id of this.eligibleAssetIds) {
        this.selectedAssetIds.delete(id);
      }
    } else {
      for (const id of this.eligibleAssetIds) {
        this.selectedAssetIds.add(id);
      }
    }
  }

  areAllEligibleSelected(): boolean {
    if (this.eligibleAssetIds.length === 0) return false;
    return this.eligibleAssetIds.every((id) => this.selectedAssetIds.has(id));
  }

  canSubmit(): boolean {
    return (
      this.selectedAssetIds.size >= 1 &&
      this.reversalReason.trim().length >= 1 &&
      !this.submitting
    );
  }

  submitReversal(): void {
    if (!this.canSubmit()) return;

    this.submitting = true;
    this.error = null;

    const grouped = new Map<string, string[]>();
    for (const assetId of this.selectedAssetIds) {
      const lineId = this.assetLineMap.get(assetId);
      if (lineId) {
        const arr = grouped.get(lineId) || [];
        arr.push(assetId);
        grouped.set(lineId, arr);
      }
    }

    const lines: ReversalLineItem[] = [];
    for (const [lineId, assetIds] of grouped.entries()) {
      lines.push({
        goods_receipt_line_id: lineId,
        asset_ids: assetIds,
        notes: this.lineNotes[lineId]?.trim() || null,
      });
    }

    const payload: GoodsReceiptReversalCreate = {
      reason: this.reversalReason.trim(),
      lines,
    };

    this.goodsReturnService
      .reverseGoodsReceipt(this.companyId, this.receipt.id, payload)
      .subscribe({
        next: (reversal) => {
          this.submitting = false;
          this.reversalCompleted.emit(reversal);
        },
        error: (err) => {
          this.submitting = false;
          this.error =
            err.error?.detail || err.message || 'Failed to execute goods receipt reversal.';
        },
      });
  }

  onClose(): void {
    this.close.emit();
  }
}
