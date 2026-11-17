import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';

import {
  GoodsReceiptReversalRead,
  GoodsReturnService,
} from '../../../services/goods-return.service';
import { GoodsReceipt } from '../../../services/registry.service';

@Component({
  selector: 'app-goods-receipt-history-modal',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './goods-receipt-history-modal.component.html',
  styleUrls: ['./goods-receipt-history-modal.component.scss'],
})
export class GoodsReceiptHistoryModalComponent implements OnInit {
  @Input({ required: true }) companyId!: string;
  @Input({ required: true }) receipt!: GoodsReceipt;

  @Output() close = new EventEmitter<void>();

  loading = true;
  error: string | null = null;
  reversals: GoodsReceiptReversalRead[] = [];

  constructor(private goodsReturnService: GoodsReturnService) {}

  ngOnInit(): void {
    this.loadHistory();
  }

  loadHistory(): void {
    this.loading = true;
    this.error = null;
    this.goodsReturnService
      .listGoodsReceiptReversals(this.companyId, this.receipt.id)
      .subscribe({
        next: (items) => {
          this.loading = false;
          this.reversals = items;
        },
        error: (err) => {
          this.loading = false;
          this.error =
            err.error?.detail || err.message || 'Failed to load goods receipt reversal history.';
        },
      });
  }

  onClose(): void {
    this.close.emit();
  }
}
