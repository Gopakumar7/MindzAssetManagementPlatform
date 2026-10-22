import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  EventEmitter,
  Input,
  Output
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  AssetImportConfirmResponse,
  AssetImportPreviewResponse,
  RegistryService
} from '../../../services/registry.service';

/**
 * Serializes a cell value for CSV error reports according to RFC-4180.
 * Neutralizes spreadsheet formula injection (CWE-1236).
 */
function sanitizeCsvValue(val: unknown): string {
  if (val === null || val === undefined) {
    return '""';
  }
  let s = String(val);
  if (/^[\s\x00-\x1f\x7f]*[=+\-@\t\r]/.test(s)) {
    s = "'" + s;
  }
  return `"${s.replace(/"/g, '""')}"`;
}

@Component({
  selector: 'app-asset-import',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './asset-import.component.html'
})
export class AssetImportComponent {
  @Input() companyId = '';
  @Input() canCreateAssets = false;

  @Output() importCompleted = new EventEmitter<{ count: number; assetNumbers: string[] }>();
  @Output() close = new EventEmitter<void>();

  selectedFile: File | null = null;
  isDragging = false;
  isValidating = false;
  isImporting = false;
  templateDownloading = false;

  previewResult: AssetImportPreviewResponse | null = null;
  confirmResult: AssetImportConfirmResponse | null = null;
  errorMessage: string | null = null;
  activeTab: 'preview' | 'errors' | 'warnings' = 'preview';

  constructor(
    private registry: RegistryService,
    private cdr: ChangeDetectorRef
  ) {}

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragging = true;
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragging = false;
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragging = false;
    const files = event.dataTransfer?.files;
    if (files && files.length > 0) {
      this.handleFile(files[0]);
    }
  }

  onFileInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      this.handleFile(input.files[0]);
    }
  }

  handleFile(file: File): void {
    const lower = file.name.toLowerCase();
    if (!lower.endsWith('.csv') && !lower.endsWith('.xlsx')) {
      this.errorMessage = "Unsupported file type. Please upload a '.csv' or '.xlsx' spreadsheet.";
      this.selectedFile = null;
      this.previewResult = null;
      this.confirmResult = null;
      this.cdr.markForCheck();
      return;
    }

    if (file.size > 5 * 1024 * 1024) {
      this.errorMessage = 'File size exceeds maximum allowed limit of 5 MB.';
      this.selectedFile = null;
      this.previewResult = null;
      this.confirmResult = null;
      this.cdr.markForCheck();
      return;
    }

    this.errorMessage = null;
    this.selectedFile = file;
    this.confirmResult = null;
    this.previewFile();
  }

  previewFile(): void {
    if (!this.selectedFile || !this.companyId) return;

    this.isValidating = true;
    this.errorMessage = null;
    this.previewResult = null;
    this.cdr.markForCheck();

    this.registry.previewAssetImport(this.companyId, this.selectedFile).subscribe({
      next: (res) => {
        this.previewResult = res;
        this.isValidating = false;
        if (!res.valid && res.errors.length > 0) {
          this.activeTab = 'errors';
        } else {
          this.activeTab = 'preview';
        }
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.isValidating = false;
        this.errorMessage = err.error?.detail || 'Failed to parse and validate spreadsheet file.';
        this.cdr.markForCheck();
      }
    });
  }

  confirmImport(): void {
    if (!this.previewResult?.preview_token || !this.companyId || this.isImporting) return;

    this.isImporting = true;
    this.errorMessage = null;
    this.cdr.markForCheck();

    this.registry.confirmAssetImport(this.companyId, this.previewResult.preview_token).subscribe({
      next: (res) => {
        this.confirmResult = res;
        this.isImporting = false;
        this.importCompleted.emit({ count: res.imported_count, assetNumbers: res.asset_numbers });
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.isImporting = false;
        this.errorMessage = err.error?.detail || 'Failed to complete bulk asset import.';
        this.cdr.markForCheck();
      }
    });
  }

  downloadTemplate(format: 'csv' | 'xlsx'): void {
    if (!this.companyId || this.templateDownloading) return;
    this.templateDownloading = true;
    this.cdr.markForCheck();

    this.registry.downloadAssetImportTemplate(this.companyId, format).subscribe({
      next: (blob) => {
        this.templateDownloading = false;
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `mindzen_asset_import_template.${format}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.templateDownloading = false;
        this.errorMessage = err.error?.detail || 'Failed to download import template.';
        this.cdr.markForCheck();
      }
    });
  }

  downloadErrorReport(): void {
    if (!this.previewResult || !this.previewResult.errors.length) return;

    const headers = ['Row', 'Field', 'Value', 'Error Message'];
    const rows = this.previewResult.errors.map(e => [
      sanitizeCsvValue(e.row_number),
      sanitizeCsvValue(e.field),
      sanitizeCsvValue(e.value || ''),
      sanitizeCsvValue(e.message)
    ]);

    const csvContent = '\uFEFF' + [headers.join(','), ...rows.map(r => r.join(','))].join('\r\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `mindzen_import_errors_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  }

  reset(): void {
    this.selectedFile = null;
    this.previewResult = null;
    this.confirmResult = null;
    this.errorMessage = null;
    this.activeTab = 'preview';
    this.cdr.markForCheck();
  }

  onClose(): void {
    this.close.emit();
  }
}
