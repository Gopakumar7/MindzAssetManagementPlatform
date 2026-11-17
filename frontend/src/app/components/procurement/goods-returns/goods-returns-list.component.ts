import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnChanges, OnInit, Output, SimpleChanges } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { GoodsReturn, GoodsReturnService } from '../../../services/goods-return.service';
import { ProcurementSupplier, PurchaseOrder } from '../../../services/registry.service';

export type GoodsReturnStatusFilter =
  | 'all'
  | 'draft'
  | 'approved'
  | 'dispatched'
  | 'partially_returned_to_warehouse'
  | 'returned_to_warehouse'
  | 'completed'
  | 'cancelled';

@Component({
  selector: 'app-goods-returns-list',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './goods-returns-list.component.html',
  styleUrls: ['./goods-returns-list.component.scss'],
})
export class GoodsReturnsListComponent implements OnInit, OnChanges {
  @Input({ required: true }) companyId!: string;
  @Input() canManage = false;
  @Input() canRead = true;
  @Input() suppliers: ProcurementSupplier[] = [];
  @Input() purchaseOrders: PurchaseOrder[] = [];

  @Output() createReturn = new EventEmitter<void>();
  @Output() selectReturn = new EventEmitter<GoodsReturn>();

  loading = false;
  error: string | null = null;
  returns: GoodsReturn[] = [];

  searchTerm = '';
  statusFilter: GoodsReturnStatusFilter = 'all';
  supplierFilter = '';

  pageSize = 10;
  currentPage = 1;

  readonly canonicalStatuses: { value: GoodsReturnStatusFilter; label: string }[] = [
    { value: 'all', label: 'All Statuses' },
    { value: 'draft', label: 'Draft' },
    { value: 'approved', label: 'Approved' },
    { value: 'dispatched', label: 'Dispatched' },
    { value: 'partially_returned_to_warehouse', label: 'Partially Returned' },
    { value: 'returned_to_warehouse', label: 'Returned to Warehouse' },
    { value: 'completed', label: 'Completed' },
    { value: 'cancelled', label: 'Cancelled' },
  ];

  constructor(private goodsReturnService: GoodsReturnService) {}

  ngOnInit(): void {
    if (this.companyId && this.canRead) {
      this.loadReturns();
    }
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['companyId'] && !changes['companyId'].firstChange) {
      this.currentPage = 1;
      this.loadReturns();
    }
  }

  loadReturns(): void {
    if (!this.companyId || !this.canRead) return;
    this.loading = true;
    this.error = null;

    const filters: { status?: string; supplierId?: string } = {};
    if (this.statusFilter !== 'all') {
      filters.status = this.statusFilter;
    }
    if (this.supplierFilter) {
      filters.supplierId = this.supplierFilter;
    }

    this.goodsReturnService.listGoodsReturns(this.companyId, filters).subscribe({
      next: (data) => {
        this.loading = false;
        this.returns = data || [];
      },
      error: (err) => {
        this.loading = false;
        this.error = err.error?.detail || err.message || 'Failed to load Goods Returns.';
      },
    });
  }

  get filteredReturns(): GoodsReturn[] {
    const term = this.searchTerm.trim().toLowerCase();
    if (!term) return this.returns;

    return this.returns.filter((r) => {
      const matchNum = r.return_number.toLowerCase().includes(term);
      const matchReason = (r.return_reason || '').toLowerCase().includes(term);
      const matchVendorRef = (r.vendor_reference || '').toLowerCase().includes(term);
      const matchDispatchRef = (r.dispatch_reference || '').toLowerCase().includes(term);
      const supplier = this.supplierName(r.supplier_id).toLowerCase();
      const matchSupplier = supplier.includes(term);
      const poNum = this.purchaseOrderNumber(r.purchase_order_id).toLowerCase();
      const matchPo = poNum.includes(term);
      return matchNum || matchReason || matchVendorRef || matchDispatchRef || matchSupplier || matchPo;
    });
  }

  get paginatedReturns(): GoodsReturn[] {
    const filtered = this.filteredReturns;
    const start = (this.currentPage - 1) * this.pageSize;
    return filtered.slice(start, start + this.pageSize);
  }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.filteredReturns.length / this.pageSize));
  }

  get totalCount(): number {
    return this.returns.length;
  }

  get draftCount(): number {
    return this.returns.filter((r) => r.status === 'draft').length;
  }

  get activeDispatchCount(): number {
    return this.returns.filter((r) => r.status === 'approved' || r.status === 'dispatched').length;
  }

  get warehouseReturnCount(): number {
    return this.returns.filter(
      (r) => r.status === 'partially_returned_to_warehouse' || r.status === 'returned_to_warehouse'
    ).length;
  }

  get completedCount(): number {
    return this.returns.filter((r) => r.status === 'completed').length;
  }

  get cancelledCount(): number {
    return this.returns.filter((r) => r.status === 'cancelled').length;
  }

  supplierName(supplierId: string): string {
    const s = this.suppliers.find((sup) => sup.id === supplierId);
    return s ? `${s.name} (${s.code})` : 'Unknown Supplier';
  }

  purchaseOrderNumber(poId: string): string {
    const po = this.purchaseOrders.find((p) => p.id === poId);
    return po ? po.order_number : '—';
  }

  onStatusFilterChange(status: GoodsReturnStatusFilter): void {
    this.statusFilter = status;
    this.currentPage = 1;
    this.loadReturns();
  }

  onSupplierFilterChange(): void {
    this.currentPage = 1;
    this.loadReturns();
  }

  onSearchChange(): void {
    this.currentPage = 1;
  }

  nextPage(): void {
    if (this.currentPage < this.totalPages) {
      this.currentPage++;
    }
  }

  prevPage(): void {
    if (this.currentPage > 1) {
      this.currentPage--;
    }
  }

  onSelectReturn(grr: GoodsReturn): void {
    this.selectReturn.emit(grr);
  }

  onCreateReturn(): void {
    this.createReturn.emit();
  }
}
