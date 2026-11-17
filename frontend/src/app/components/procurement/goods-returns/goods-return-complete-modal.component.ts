import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  EventEmitter,
  HostListener,
  Input,
  Output,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  GoodsReturn,
  GoodsReturnLine,
  GoodsReturnService,
} from '../../../services/goods-return.service';

@Component({
  selector: 'app-goods-return-complete-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './goods-return-complete-modal.component.html',
  styleUrls: ['./goods-return-complete-modal.component.scss'],
  changeDetection: ChangeDetectionStrategy.Eager,
})
export class GoodsReturnCompleteModalComponent {
  @Input({ required: true }) companyId!: string;
  @Input({ required: true }) goodsReturn!: GoodsReturn;
  @Input({ required: true }) outstandingLines: GoodsReturnLine[] = [];
  @Input() supplierName = '—';
  @Input() receivedCount = 0;

  @Output() completed = new EventEmitter<GoodsReturn>();
  @Output() conflictOccurred = new EventEmitter<void>();
  @Output() notFoundOccurred = new EventEmitter<void>();
  @Output() close = new EventEmitter<void>();

  confirmed = false;
  submitting = false;
  error: string | null = null;
  validationError: string | null = null;

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
    return this.confirmed && this.outstandingLines.length > 0 && !this.submitting;
  }

  onClose(): void {
    if (this.submitting) return;
    this.close.emit();
  }

  onSubmit(): void {
    if (this.submitting) return;

    if (this.outstandingLines.length === 0) {
      this.validationError =
        'No outstanding in-transit assets remain to be accepted by the vendor.';
      return;
    }

    if (!this.confirmed) {
      this.validationError =
        'Please check the confirmation box to confirm vendor acceptance and permanent completion.';
      return;
    }

    this.validationError = null;
    this.submitting = true;
    this.error = null;

    this.goodsReturnService
      .completeGoodsReturn(this.companyId, this.goodsReturn.id)
      .subscribe({
        next: (updatedReturn) => {
          this.submitting = false;
          this.changeDetector.markForCheck();
          this.completed.emit(updatedReturn);
        },
        error: (err) => {
          this.submitting = false;
          const detail = typeof err.error?.detail === 'string' ? err.error.detail : null;

          if (err.status === 401) {
            this.error = 'Authentication session expired. Please log in again.';
          } else if (err.status === 403) {
            this.error =
              detail ||
              'Permission denied. Completing goods returns requires procurement.manage permission.';
          } else if (err.status === 404) {
            this.confirmed = false;
            this.error =
              detail ||
              'The requested Goods Return was not found on the server. The record may have been removed or updated.';
            this.notFoundOccurred.emit();
          } else if (err.status === 409) {
            this.confirmed = false;
            this.error =
              detail ||
              'Conflict completing goods return: Return status or asset eligibility has changed on the server. Active return data refreshed.';
            this.conflictOccurred.emit();
          } else {
            this.error =
              detail ||
              err.message ||
              'An unexpected error occurred while completing the goods return.';
          }
          this.changeDetector.markForCheck();
        },
      });
  }
}
