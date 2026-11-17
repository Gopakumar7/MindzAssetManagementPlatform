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
  GoodsReturnService,
  GoodsReturnWarehouseReceipt,
  GoodsReturnWarehouseReceiptLine,
  WarehouseReceiptCorrectionPayload,
} from '../../../services/goods-return.service';

@Component({
  selector: 'app-goods-return-receipt-correction-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './goods-return-receipt-correction-modal.component.html',
  styleUrls: ['./goods-return-receipt-correction-modal.component.scss'],
  changeDetection: ChangeDetectionStrategy.Eager,
})
export class GoodsReturnReceiptCorrectionModalComponent {
  @Input({ required: true }) companyId!: string;
  @Input({ required: true }) goodsReturn!: GoodsReturn;
  @Input({ required: true }) receipt!: GoodsReturnWarehouseReceipt;
  @Input({ required: true }) receiptLine!: GoodsReturnWarehouseReceiptLine;
  @Input() assetNumber?: string;
  @Input() serialNumber?: string | null;

  @Output() corrected = new EventEmitter<GoodsReturnWarehouseReceipt>();
  @Output() conflictOccurred = new EventEmitter<void>();
  @Output() close = new EventEmitter<void>();

  correctionReason = '';
  notes = '';
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

  get trimmedReason(): string {
    return this.correctionReason ? this.correctionReason.trim() : '';
  }

  get reasonLength(): number {
    return this.trimmedReason.length;
  }

  get isReasonValid(): boolean {
    return this.reasonLength >= 5;
  }

  get isFormValid(): boolean {
    return this.isReasonValid && this.confirmed && !this.submitting;
  }

  onClose(): void {
    if (this.submitting) return;
    this.close.emit();
  }

  onSubmit(): void {
    if (this.submitting) return;

    if (!this.isReasonValid) {
      this.validationError =
        'Correction reason is mandatory and must be at least 5 characters (excluding whitespace).';
      return;
    }

    if (!this.confirmed) {
      this.validationError =
        'Please confirm that you understand the lifecycle effects of correcting this warehouse receipt.';
      return;
    }

    this.validationError = null;
    this.submitting = true;
    this.error = null;

    const payload: WarehouseReceiptCorrectionPayload = {
      correction_reason: this.trimmedReason,
      notes: this.notes.trim() || null,
    };

    this.goodsReturnService
      .correctWarehouseReceiptLine(
        this.companyId,
        this.goodsReturn.id,
        this.receipt.id,
        this.receiptLine.id,
        payload
      )
      .subscribe({
        next: (updatedReceipt) => {
          this.submitting = false;
          this.changeDetector.markForCheck();
          this.corrected.emit(updatedReceipt);
        },
        error: (err) => {
          this.submitting = false;
          const detail = typeof err.error?.detail === 'string' ? err.error.detail : null;

          if (err.status === 401) {
            this.error = 'Authentication session expired. Please log in again.';
          } else if (err.status === 403) {
            this.error =
              detail ||
              'Permission denied. Correcting warehouse receipt intake requires procurement.manage permission.';
          } else if (err.status === 404) {
            this.error =
              detail ||
              'The warehouse receipt or receipt line no longer exists. Server data has been refreshed.';
            this.conflictOccurred.emit();
          } else if (err.status === 409) {
            this.error =
              detail ||
              'Correction conflict: The asset is no longer eligible for receipt correction. Server data has been refreshed.';
            this.conflictOccurred.emit();
          } else if (err.status === 422) {
            this.error =
              detail ||
              'Validation error: Correction reason must be at least 5 characters.';
          } else {
            this.error =
              detail ||
              err.message ||
              'An unexpected error occurred while submitting the correction.';
          }
          this.changeDetector.markForCheck();
        },
      });
  }
}
