import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, EventEmitter, HostListener, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { GoodsReturn, GoodsReturnCancelPayload, GoodsReturnService } from '../../../services/goods-return.service';

@Component({
  selector: 'app-goods-return-cancel-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './goods-return-cancel-modal.component.html',
  styleUrls: ['./goods-return-cancel-modal.component.scss'],
  changeDetection: ChangeDetectionStrategy.Eager,
})
export class GoodsReturnCancelModalComponent {
  @Input({ required: true }) companyId!: string;
  @Input({ required: true }) goodsReturn!: GoodsReturn;

  @Output() cancelled = new EventEmitter<GoodsReturn>();
  @Output() close = new EventEmitter<void>();

  cancellationReason = '';
  submitting = false;
  error: string | null = null;

  constructor(
    private goodsReturnService: GoodsReturnService,
    private changeDetector: ChangeDetectorRef
  ) {}

  @HostListener('keydown.escape', ['$event'])
  onEscape(event?: Event): void {
    if (event) {
      event.stopPropagation();
    }
    if (!this.submitting) {
      this.onClose();
    }
  }

  get isReasonValid(): boolean {
    return this.cancellationReason.trim().length >= 3;
  }

  get isFormValid(): boolean {
    return this.isReasonValid && !this.submitting;
  }

  onSubmit(): void {
    if (!this.isFormValid) return;

    this.submitting = true;
    this.error = null;

    const payload: GoodsReturnCancelPayload = {
      cancellation_reason: this.cancellationReason.trim(),
    };

    this.goodsReturnService.cancelGoodsReturn(this.companyId, this.goodsReturn.id, payload).subscribe({
      next: (updatedReturn) => {
        this.submitting = false;
        this.changeDetector.markForCheck();
        this.cancelled.emit(updatedReturn);
      },
      error: (err) => {
        this.submitting = false;
        this.error = err.error?.detail || err.message || 'Failed to cancel Goods Return.';
        this.changeDetector.markForCheck();
      },
    });
  }

  onClose(): void {
    if (this.submitting) return;
    this.close.emit();
  }
}
