import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import {
  Asset,
  AssetHistory,
  AssetPage,
  Company,
  DepartmentUsage,
  MasterRecord,
  NumberRule,
  RegistryService
} from '../../services/registry.service';

type ViewName = 'assets' | 'departments' | 'sites' | 'categories' | 'cost-centers' | 'company';
type MasterKind = 'departments' | 'sites' | 'categories' | 'cost-centers';

@Component({
  selector: 'app-registry',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './registry.component.html'
})
export class RegistryComponent implements OnInit {
  @ViewChild('assetDetail') private assetDetail?: ElementRef<HTMLElement>;

  companies: Company[] = [];
  companyId = '';
  company?: Company;
  creatingCompany = false;
  activeView: ViewName = 'assets';
  loading = false;
  saving = false;
  errorMessage = '';
  successMessage = '';

  departments: MasterRecord[] = [];
  sites: MasterRecord[] = [];
  locations: MasterRecord[] = [];
  categories: MasterRecord[] = [];
  costCenters: MasterRecord[] = [];
  numberRules: NumberRule[] = [];
  assets: Asset[] = [];
  totalAssets = 0;
  page = 1;
  readonly pageSize = 15;
  selectedAsset?: Asset;
  selectedUsages: DepartmentUsage[] = [];
  assetHistory: AssetHistory[] = [];

  filters = { search: '', category_id: '', status: '', site_id: '', location_id: '', department_id: '' };
  companyForm = { code: '', name: '', number_prefix: 'AST', is_active: true };
  masterForm = { code: '', name: '', description: '', address: '', details: '', is_active: true };
  selectedSiteId = '';
  editingMasterId = '';
  editingLocationId = '';
  ruleForm = { category_id: '', prefix: 'AST', separator: '-', padding: 6 };
  assetForm: Partial<Asset> = {
    category_id: '',
    serial_number: '',
    manufacturer: '',
    model: '',
    status: 'in_stock',
    site_id: '',
    location_id: '',
    responsible_department_id: '',
    cost_center_id: '',
    custodian_name: '',
    notes: ''
  };
  assetEditForm: Partial<Asset> = {};
  usageForm = { department_id: '', purpose: '' };

  constructor(
    private readonly registry: RegistryService,
    private readonly changeDetector: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.loading = true;
    this.registry.companies().subscribe({
      next: (companies) => {
        this.companies = companies;
        this.loading = false;
        if (companies.length > 0) {
          this.selectCompany(companies[0].id);
        }
      },
      error: (error) => this.fail(error)
    });
  }

  get activeDepartments(): MasterRecord[] {
    return this.departments.filter((item) => item.is_active);
  }

  get activeSites(): MasterRecord[] {
    return this.sites.filter((item) => item.is_active);
  }

  get activeCategories(): MasterRecord[] {
    return this.categories.filter((item) => item.is_active);
  }

  get activeCostCenters(): MasterRecord[] {
    return this.costCenters.filter((item) => item.is_active);
  }

  get pageCount(): number {
    return Math.max(1, Math.ceil(this.totalAssets / this.pageSize));
  }

  selectCompany(id: string): void {
    this.companyId = id;
    this.company = this.companies.find((item) => item.id === id);
    this.creatingCompany = this.companies.length === 0;
    if (this.company) {
      this.companyForm.name = this.company.name;
      this.companyForm.is_active = this.company.is_active;
    }
    if (!id) {
      return;
    }
    this.loading = true;
    this.errorMessage = '';
    forkJoin({
      departments: this.registry.listMaster(id, 'departments'),
      sites: this.registry.listMaster(id, 'sites'),
      categories: this.registry.listMaster(id, 'categories'),
      costCenters: this.registry.listMaster(id, 'cost-centers'),
      rules: this.registry.listNumberRules(id)
    }).subscribe({
      next: (result) => {
        this.departments = result.departments;
        this.sites = result.sites;
        this.categories = result.categories;
        this.costCenters = result.costCenters;
        this.numberRules = result.rules;
        this.loading = false;
        if (!this.ruleForm.category_id && result.rules.length) {
          const defaultRule = result.rules.find((rule) => rule.category_id === null) ?? result.rules[0];
          this.ruleForm = {
            category_id: defaultRule.category_id ?? '',
            prefix: defaultRule.prefix,
            separator: defaultRule.separator,
            padding: defaultRule.padding
          };
        }
        this.loadAssets();
        if (this.selectedSiteId) {
          this.loadLocations(this.selectedSiteId);
        }
      },
      error: (error) => this.fail(error)
    });
  }

  setView(view: ViewName): void {
    this.activeView = view;
    this.errorMessage = '';
    this.successMessage = '';
    this.editingMasterId = '';
    this.masterForm = { code: '', name: '', description: '', address: '', details: '', is_active: true };
    if (view === 'assets') {
      this.loadAssets();
    }
  }

  loadAssets(): void {
    if (!this.companyId) {
      return;
    }
    this.loading = true;
    this.registry.listAssets(this.companyId, {
      page: this.page,
      page_size: this.pageSize,
      search: this.filters.search,
      category_id: this.filters.category_id,
      status: this.filters.status,
      site_id: this.filters.site_id,
      location_id: this.filters.location_id,
      department_id: this.filters.department_id
    }).subscribe({
      next: (result: AssetPage) => {
        this.assets = result.items;
        this.totalAssets = result.total;
        this.loading = false;
      },
      error: (error) => this.fail(error)
    });
  }

  pageBy(delta: number): void {
    const pageCount = Math.max(1, Math.ceil(this.totalAssets / this.pageSize));
    this.page = Math.min(pageCount, Math.max(1, this.page + delta));
    this.loadAssets();
  }

  onSiteChange(siteId: string): void {
    this.selectedSiteId = siteId;
    this.locations = [];
    if (siteId) {
      this.loadLocations(siteId);
    }
  }

  loadLocations(siteId: string): void {
    if (!siteId || !this.companyId) {
      this.locations = [];
      return;
    }
    this.registry.listLocations(this.companyId, siteId).subscribe({
      next: (records) => (this.locations = records),
      error: (error) => this.fail(error)
    });
  }

  saveMaster(): void {
    if (!this.companyId) {
      this.errorMessage = 'Create or select a company before adding master data.';
      return;
    }
    const kind = this.activeView as MasterKind;
    const payload: Record<string, string | boolean | null> = {
      code: this.masterForm.code.trim(),
      name: this.masterForm.name.trim(),
      is_active: this.masterForm.is_active
    };
    if (kind === 'sites') {
      payload['address'] = this.masterForm.address;
    } else if (kind === 'categories') {
      payload['description'] = this.masterForm.description;
    }
    if (this.editingMasterId) {
      const body: Record<string, string | boolean | null> = { name: this.masterForm.name.trim(), is_active: this.masterForm.is_active };
      if (kind === 'sites') {
        body['address'] = this.masterForm.address;
      } else if (kind === 'categories') {
        body['description'] = this.masterForm.description;
      }
      this.updateMaster(kind, this.editingMasterId, body);
      return;
    }
    this.saving = true;
    this.registry.createMaster(this.companyId, kind, payload).subscribe({
      next: () => {
        this.saving = false;
        this.successMessage = 'Record created.';
        this.masterForm = { code: '', name: '', description: '', address: '', details: '', is_active: true };
        this.refreshMaster(kind);
      },
      error: (error) => this.fail(error)
    });
  }

  saveLocation(): void {
    if (!this.selectedSiteId) {
      this.errorMessage = 'Select a site for this location.';
      return;
    }
    this.saving = true;
    if (this.editingLocationId) {
      this.registry.updateLocation(this.companyId, this.selectedSiteId, this.editingLocationId, {
        name: this.masterForm.name.trim(),
        details: this.masterForm.details,
        is_active: this.masterForm.is_active
      }).subscribe({
        next: () => {
          this.saving = false;
          this.editingLocationId = '';
          this.successMessage = 'Location updated.';
          this.loadLocations(this.selectedSiteId);
          this.masterForm = { code: '', name: '', description: '', address: '', details: '', is_active: true };
        },
        error: (error) => this.fail(error)
      });
      return;
    }
    this.registry.createLocation(this.companyId, this.selectedSiteId, {
      code: this.masterForm.code.trim(),
      name: this.masterForm.name.trim(),
      details: this.masterForm.details,
      is_active: true
    }).subscribe({
      next: () => {
        this.saving = false;
        this.successMessage = 'Location created.';
        this.masterForm = { code: '', name: '', description: '', address: '', details: '', is_active: true };
        this.loadLocations(this.selectedSiteId);
      },
      error: (error) => this.fail(error)
    });
  }

  editMaster(record: MasterRecord): void {
    this.editingMasterId = record.id;
    this.masterForm = {
      code: record.code,
      name: record.name,
      description: record.description ?? '',
      address: record.address ?? '',
      details: record.details ?? '',
      is_active: record.is_active
    };
    if (record.site_id) {
      this.selectedSiteId = record.site_id;
      this.loadLocations(record.site_id);
    }
  }

  editLocation(record: MasterRecord): void {
    this.editingLocationId = record.id;
    this.selectedSiteId = record.site_id ?? this.selectedSiteId;
    if (this.selectedSiteId) this.loadLocations(this.selectedSiteId);
    this.masterForm.code = record.code;
    this.masterForm.name = record.name;
    this.masterForm.details = record.details ?? '';
    this.masterForm.is_active = record.is_active;
  }

  deactivateLocation(record: MasterRecord): void {
    if (!window.confirm(`Deactivate location ${record.name}?`)) return;
    this.registry.deactivateLocation(this.companyId, this.selectedSiteId, record).subscribe({
      next: () => {
        this.successMessage = 'Location deactivated.';
        this.loadLocations(this.selectedSiteId);
      },
      error: (error) => this.fail(error)
    });
  }

  private updateMaster(kind: MasterKind, id: string, payload: Record<string, string | boolean | null>): void {
    this.saving = true;
    this.registry.updateMaster(this.companyId, kind, id, payload).subscribe({
      next: () => {
        this.saving = false;
        this.successMessage = 'Record updated.';
        this.editingMasterId = '';
        this.masterForm = { code: '', name: '', description: '', address: '', details: '', is_active: true };
        this.refreshMaster(kind);
      },
      error: (error) => this.fail(error)
    });
  }

  deactivateMaster(kind: MasterKind, record: MasterRecord): void {
    if (!window.confirm(`Deactivate ${record.name}?`)) {
      return;
    }
    this.registry.deactivateMaster(this.companyId, kind, record).subscribe({
      next: () => {
        this.successMessage = 'Record deactivated.';
        this.refreshMaster(kind);
      },
      error: (error) => this.fail(error)
    });
  }

  deactivateCurrentMaster(record: MasterRecord): void {
    if (this.activeView === 'departments' || this.activeView === 'sites' || this.activeView === 'categories' || this.activeView === 'cost-centers') {
      this.deactivateMaster(this.activeView, record);
    }
  }

  private refreshMaster(kind: MasterKind): void {
    this.registry.listMaster(this.companyId, kind).subscribe({
      next: (records) => {
        if (kind === 'departments') this.departments = records;
        if (kind === 'sites') this.sites = records;
        if (kind === 'categories') this.categories = records;
        if (kind === 'cost-centers') this.costCenters = records;
      },
      error: (error) => this.fail(error)
    });
  }

  createCompany(): void {
    this.saving = true;
    this.registry.createCompany({
      code: this.companyForm.code.trim(),
      name: this.companyForm.name.trim(),
      number_prefix: this.companyForm.number_prefix.trim()
    }).subscribe({
      next: (company) => {
        this.saving = false;
        this.successMessage = 'Company created with its own default asset numbering rule and six initial categories.';
        this.companies = [...this.companies, company];
        this.companyForm = { code: '', name: '', number_prefix: 'AST', is_active: true };
        this.selectCompany(company.id);
      },
      error: (error) => this.fail(error)
    });
  }

  beginCompanyCreate(): void {
    this.creatingCompany = true;
    this.companyForm = { code: '', name: '', number_prefix: 'AST', is_active: true };
    this.successMessage = '';
  }

  selectCompanyForEdit(company: Company): void {
    this.selectCompany(company.id);
    this.creatingCompany = false;
  }

  saveCompany(): void {
    if (!this.company) {
      return;
    }
    this.registry.updateCompany(this.company.id, { name: this.companyForm.name, is_active: this.companyForm.is_active }).subscribe({
      next: (updated) => {
        this.company = updated;
        this.companies = this.companies.map((item) => item.id === updated.id ? updated : item);
        this.successMessage = 'Company updated.';
      },
      error: (error) => this.fail(error)
    });
  }

  saveNumberRule(): void {
    this.registry.saveNumberRule(
      this.companyId,
      { prefix: this.ruleForm.prefix.trim(), separator: this.ruleForm.separator, padding: Number(this.ruleForm.padding) },
      this.ruleForm.category_id || undefined
    ).subscribe({
      next: (rule) => {
        this.successMessage = 'Numbering rule saved. Existing asset numbers are not changed.';
        this.numberRules = [...this.numberRules.filter((item) => item.category_id !== rule.category_id), rule];
      },
      error: (error) => this.fail(error)
    });
  }

  onRuleCategoryChange(categoryId: string): void {
    const rule = this.numberRules.find((item) => item.category_id === (categoryId || null));
    this.ruleForm = rule
      ? { category_id: categoryId, prefix: rule.prefix, separator: rule.separator, padding: rule.padding }
      : { category_id: categoryId, prefix: 'AST', separator: '-', padding: 6 };
  }

  createAsset(): void {
    const payload: Partial<Asset> = {
      ...this.assetForm,
      category_id: this.assetForm.category_id || undefined,
      site_id: this.assetForm.site_id || undefined,
      location_id: this.assetForm.location_id || undefined,
      responsible_department_id: this.assetForm.responsible_department_id || undefined,
      cost_center_id: this.assetForm.cost_center_id || undefined
    };
    this.saving = true;
    this.registry.createAsset(this.companyId, payload).subscribe({
      next: (asset) => {
        this.saving = false;
        this.successMessage = `Asset ${asset.asset_number} registered.`;
        this.assetForm = { category_id: '', status: 'in_stock', site_id: '', location_id: '', responsible_department_id: '', cost_center_id: '' };
        this.page = 1;
        this.loadAssets();
        this.openAsset(asset);
      },
      error: (error) => this.fail(error)
    });
  }

  openAsset(asset: Asset): void {
    this.selectedAsset = asset;
    this.assetEditForm = { ...asset };
    this.usageForm = { department_id: '', purpose: '' };
    this.changeDetector.detectChanges();
    const detailsPanel = this.assetDetail?.nativeElement;
    detailsPanel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    detailsPanel?.focus({ preventScroll: true });
    if (asset.site_id) {
      this.loadLocations(asset.site_id);
    } else {
      this.locations = [];
    }
    this.refreshAssetDetails();
  }

  refreshAssetDetails(): void {
    if (!this.selectedAsset || !this.companyId) return;
    forkJoin({
      asset: this.registry.getAsset(this.companyId, this.selectedAsset.id),
      usages: this.registry.usages(this.companyId, this.selectedAsset.id, true),
      history: this.registry.history(this.companyId, this.selectedAsset.id)
    }).subscribe({
      next: (result) => {
        this.selectedAsset = result.asset;
        this.assetEditForm = { ...result.asset };
        this.selectedUsages = result.usages;
        this.assetHistory = result.history;
      },
      error: (error) => this.fail(error)
    });
  }

  saveAsset(): void {
    if (!this.selectedAsset) return;
    this.registry.updateAsset(this.companyId, this.selectedAsset.id, {
      ...this.assetEditForm,
      site_id: this.assetEditForm.site_id || null,
      location_id: this.assetEditForm.location_id || null,
      responsible_department_id: this.assetEditForm.responsible_department_id || null,
      cost_center_id: this.assetEditForm.cost_center_id || null
    }).subscribe({
      next: (updated) => {
        this.selectedAsset = updated;
        this.successMessage = 'Asset updated.';
        this.loadAssets();
        this.refreshAssetDetails();
      },
      error: (error) => this.fail(error)
    });
  }

  addUsage(): void {
    if (!this.selectedAsset || !this.usageForm.department_id) return;
    this.registry.startUsage(this.companyId, this.selectedAsset.id, this.usageForm).subscribe({
      next: () => {
        this.successMessage = 'Department usage started. Custodian and location were not changed.';
        this.usageForm = { department_id: '', purpose: '' };
        this.refreshAssetDetails();
      },
      error: (error) => this.fail(error)
    });
  }

  endUsage(usage: DepartmentUsage): void {
    if (!this.selectedAsset || usage.ended_at || !window.confirm('End this department usage relationship?')) return;
    this.registry.endUsage(this.companyId, this.selectedAsset.id, usage.id).subscribe({
      next: () => {
        this.successMessage = 'Department usage ended; its history is retained.';
        this.refreshAssetDetails();
      },
      error: (error) => this.fail(error)
    });
  }

  categoryName(categoryId: string): string {
    return this.categories.find((item) => item.id === categoryId)?.name ?? 'Unknown category';
  }

  siteName(siteId: string | null): string {
    return this.sites.find((item) => item.id === siteId)?.name ?? '—';
  }

  locationName(locationId: string | null): string {
    for (const site of this.sites) {
      const location = this.locations.find((item) => item.id === locationId);
      if (location && site.id === location.site_id) return location.name;
    }
    return locationId ? 'Location recorded' : '—';
  }

  departmentName(departmentId: string): string {
    return this.departments.find((item) => item.id === departmentId)?.name ?? 'Unknown department';
  }

  private fail(error: { error?: { detail?: string | { message?: string } }; message?: string }): void {
    this.loading = false;
    this.saving = false;
    const detail = error.error?.detail;
    this.errorMessage = typeof detail === 'string' ? detail : detail?.message ?? error.message ?? 'Request failed.';
  }
}
