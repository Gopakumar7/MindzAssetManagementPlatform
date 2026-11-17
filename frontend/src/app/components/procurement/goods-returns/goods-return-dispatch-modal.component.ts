import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, EventEmitter, HostListener, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { GoodsReturn, GoodsReturnDispatchPayload, GoodsReturnService } from '../../../services/goods-return.service';

@Component({
  selector: 'app-goods-return-dispatch-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './goods-return-dispatch-modal.component.html',
  styleUrls: ['./goods-return-dispatch-modal.component.scss'],
  changeDetection: ChangeDetectionStrategy.Eager,
})
export class GoodsReturnDispatchModalComponent {
  @Input({ required: true }) companyId!: string;
  @Input({ required: true }) goodsReturn!: GoodsReturn;

  @Output() dispatched = new EventEmitter<GoodsReturn>();
  @Output() close = new EventEmitter<void>();

  dispatchReference = '';
  transportDetails = '';
  notes = '';
  confirmed = false;

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

  get isFormValid(): boolean {
    return this.dispatchReference.trim().length >= 1 &&
      this.dispatchReference.trim().length <= 128 &&
      this.confirmed &&
      !this.submitting;
  }

  get assetCount(): number {
    return this.goodsReturn?.lines?.length || 0;
  }

  onSubmit(): void {
    if (!this.isFormValid) return;

    this.submitting = true;
    this.error = null;

    const payload: GoodsReturnDispatchPayload = {
      dispatch_reference: this.dispatchReference.trim(),
      transport_details: this.transportDetails.trim() || null,
      notes: this.notes.trim() || null,
    };

    this.goodsReturnService.dispatchGoodsReturn(this.companyId, this.goodsReturn.id, payload).subscribe({
      next: (updatedReturn) => {
        this.submitting = false;
        this.changeDetector.markForCheck();
        this.dispatched.emit(updatedReturn);
      },
      error: (err) => {
        this.submitting = false;
        this.error = err.error?.detail || err.message || 'Failed to dispatch Goods Return. Please check return status.';
        this.changeDetector.markForCheck();
      },
    });
  }

  onClose(): void {
    if (this.submitting) return;
    this.close.emit();
  }
}
