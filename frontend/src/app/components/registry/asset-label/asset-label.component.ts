import {
  AfterViewInit,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  OnInit,
  Output,
  SimpleChanges
} from '@angular/core';
import { CommonModule } from '@angular/common';
import JsBarcode from 'jsbarcode';
import * as QRCode from 'qrcode';
import { Asset } from '../../../services/registry.service';

@Component({
  selector: 'app-asset-label',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './asset-label.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class AssetLabelComponent implements OnInit, OnChanges, AfterViewInit {
  @Input() assets: Asset[] = [];
  @Input() companyName = '';
  @Input() categoryNames: Record<string, string> = {};
  @Output() close = new EventEmitter<void>();

  qrDataUrls: Record<string, string> = {};
  isGenerating = false;

  constructor(
    private elementRef: ElementRef,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.generateLabels();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['assets'] && !changes['assets'].firstChange) {
      this.generateLabels();
    }
  }

  ngAfterViewInit(): void {
    this.renderBarcodes();
  }

  getLookupUrl(assetNumber: string): string {
    if (!assetNumber) return '';
    if (typeof window !== 'undefined' && window.location && window.location.origin) {
      return `${window.location.origin}/?lookup=${encodeURIComponent(assetNumber)}`;
    }
    return `/?lookup=${encodeURIComponent(assetNumber)}`;
  }

  getCategoryName(categoryId: string | null | undefined): string {
    if (!categoryId) return 'General';
    return this.categoryNames[categoryId] || 'Asset';
  }

  async generateLabels(): Promise<void> {
    if (!this.assets || this.assets.length === 0) {
      this.qrDataUrls = {};
      this.cdr.markForCheck();
      return;
    }

    this.isGenerating = true;
    const newQrMap: Record<string, string> = {};

    for (const asset of this.assets) {
      if (!asset || !asset.asset_number) continue;
      const url = this.getLookupUrl(asset.asset_number);
      try {
        const dataUrl = await QRCode.toDataURL(url, {
          errorCorrectionLevel: 'M',
          margin: 1,
          width: 140,
          color: {
            dark: '#000000',
            light: '#ffffff'
          }
        });
        newQrMap[asset.id] = dataUrl;
      } catch (err) {
        console.error('Failed to generate QR for asset', asset.asset_number, err);
      }
    }

    this.qrDataUrls = newQrMap;
    this.isGenerating = false;
    this.cdr.markForCheck();

    // Re-render barcodes into SVG elements after DOM update
    setTimeout(() => {
      this.renderBarcodes();
    }, 0);
  }

  renderBarcodes(): void {
    if (!this.assets || this.assets.length === 0) return;

    for (const asset of this.assets) {
      if (!asset || !asset.asset_number) continue;
      const svgEl = this.elementRef.nativeElement.querySelector(`#barcode-${asset.id}`);
      if (svgEl) {
        try {
          JsBarcode(svgEl, asset.asset_number, {
            format: 'CODE128',
            width: 1.4,
            height: 32,
            displayValue: false,
            margin: 0,
            background: '#ffffff',
            lineColor: '#000000'
          });
        } catch (err) {
          console.error('Failed to render barcode for', asset.asset_number, err);
        }
      }
    }
    this.cdr.markForCheck();
  }

  printLabels(): void {
    if (typeof window !== 'undefined') {
      window.print();
    }
  }

  onClose(): void {
    this.close.emit();
  }
}
