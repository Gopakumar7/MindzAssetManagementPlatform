import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { AssetLabelComponent } from './asset-label.component';
import { Asset } from '../../../services/registry.service';

describe('AssetLabelComponent', () => {
  let component: AssetLabelComponent;
  let fixture: ComponentFixture<AssetLabelComponent>;

  const mockAsset1: Asset = {
    id: 'asset-uuid-1',
    company_id: 'company-uuid-1',
    asset_number: 'AST-2026-0001',
    category_id: 'cat-laptop',
    model: 'ThinkPad T14s',
    serial_number: 'SN-TP-9921',
    manufacturer: 'Lenovo',
    status: 'in_stock',
    site_id: 'site-1',
    location_id: 'loc-1',
    responsible_department_id: 'dept-1',
    cost_center_id: 'cc-1',
    custodian_name: 'Jane Doe',
    notes: 'Standard engineering laptop',
    acquisition_date: '2026-01-10',
    acquisition_cost: '1450.00',
    vendor_reference: null,
    invoice_reference: null,
    warranty_start: null,
    warranty_end: null
  };

  const mockAsset2: Asset = {
    id: 'asset-uuid-2',
    company_id: 'company-uuid-1',
    asset_number: 'AST-2026-0002',
    category_id: 'cat-monitor',
    model: 'Dell U2723QE',
    serial_number: 'SN-DL-8842',
    manufacturer: 'Dell',
    status: 'in_use',
    site_id: 'site-1',
    location_id: 'loc-1',
    responsible_department_id: 'dept-1',
    cost_center_id: 'cc-1',
    custodian_name: 'John Smith',
    notes: null,
    acquisition_date: '2026-02-15',
    acquisition_cost: '620.00',
    vendor_reference: null,
    invoice_reference: null,
    warranty_start: null,
    warranty_end: null
  };

  const mockAssetMinimal: Asset = {
    id: 'asset-uuid-3',
    company_id: 'company-uuid-1',
    asset_number: 'AST-2026-0003',
    category_id: '',
    model: null,
    serial_number: null,
    status: 'in_stock',
    acquisition_cost: null,
    acquisition_date: null,
    manufacturer: null,
    site_id: null,
    location_id: null,
    responsible_department_id: null,
    cost_center_id: null,
    custodian_name: null,
    vendor_reference: null,
    invoice_reference: null,
    warranty_start: null,
    warranty_end: null,
    notes: null
  };

  const categoryNames = {
    'cat-laptop': 'Laptops & Workstations',
    'cat-monitor': 'Monitors'
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AssetLabelComponent]
    }).compileComponents();

    fixture = TestBed.createComponent(AssetLabelComponent);
    component = fixture.componentInstance;
  });

  it('should create the component', () => {
    expect(component).toBeTruthy();
  });

  it('should format a safe dynamic lookup URL with encoded asset number and no sensitive data', () => {
    const url = component.getLookupUrl('AST-2026-0001');
    expect(url).toContain('/?lookup=AST-2026-0001');
    expect(url).not.toContain('financial');
    expect(url).not.toContain('token');
    expect(url).not.toContain('1450');
  });

  it('should resolve mapped category names and fallback cleanly for unmapped or null categories', () => {
    component.categoryNames = categoryNames;
    expect(component.getCategoryName('cat-laptop')).toBe('Laptops & Workstations');
    expect(component.getCategoryName('cat-unknown')).toBe('Asset');
    expect(component.getCategoryName(null)).toBe('General');
    expect(component.getCategoryName(undefined)).toBe('General');
  });

  it('should generate QR code and render barcode for a single asset', fakeAsync(() => {
    component.assets = [mockAsset1];
    component.companyName = 'MindZen Demo Enterprise';
    component.categoryNames = categoryNames;

    fixture.detectChanges();
    tick(50);
    fixture.detectChanges();

    expect(component.qrDataUrls[mockAsset1.id]).toBeDefined();
    expect(component.qrDataUrls[mockAsset1.id]).toMatch(/^data:image\/png;base64,/);

    const compiled = fixture.nativeElement as HTMLElement;
    const titleEl = compiled.querySelector('.label-modal-header h3');
    expect(titleEl?.textContent).toContain('Asset Label Preview');

    const companyEl = compiled.querySelector('.label-company-name');
    expect(companyEl?.textContent).toBe('MindZen Demo Enterprise');

    const catEl = compiled.querySelector('.label-category-pill');
    expect(catEl?.textContent).toBe('Laptops & Workstations');

    const assetNumEl = compiled.querySelector('.label-asset-number');
    expect(assetNumEl?.textContent).toBe('AST-2026-0001');

    const modelEl = compiled.querySelector('.label-model');
    expect(modelEl?.textContent?.trim()).toBe('ThinkPad T14s');

    const snEl = compiled.querySelector('.label-sn');
    expect(snEl?.textContent?.trim()).toBe('SN: SN-TP-9921');

    const barcodeSvg = compiled.querySelector(`#barcode-${mockAsset1.id}`);
    expect(barcodeSvg).toBeTruthy();
    // JsBarcode appends rect or path elements inside the SVG
    expect(barcodeSvg?.children.length).toBeGreaterThan(0);
  }));

  it('should render bulk labels for multiple assets in a grid layout', fakeAsync(() => {
    component.assets = [mockAsset1, mockAsset2];
    component.companyName = 'MindZen Demo Enterprise';
    component.categoryNames = categoryNames;

    fixture.detectChanges();
    tick(50);
    fixture.detectChanges();

    expect(component.qrDataUrls[mockAsset1.id]).toBeDefined();
    expect(component.qrDataUrls[mockAsset2.id]).toBeDefined();

    const compiled = fixture.nativeElement as HTMLElement;
    const titleEl = compiled.querySelector('.label-modal-header h3');
    expect(titleEl?.textContent).toContain('Bulk Asset Labels (2)');

    const printBtn = compiled.querySelector('.print-btn');
    expect(printBtn?.textContent).toContain('Print Labels (2)');

    const labelCards = compiled.querySelectorAll('.asset-label-card');
    expect(labelCards.length).toBe(2);
  }));

  it('should render graceful fallbacks when optional fields (model, SN, category) are missing', fakeAsync(() => {
    component.assets = [mockAssetMinimal];
    component.companyName = '';
    component.categoryNames = {};

    fixture.detectChanges();
    tick(50);
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    const companyEl = compiled.querySelector('.label-company-name');
    expect(companyEl?.textContent).toBe('MindZen Asset Tag');

    const catEl = compiled.querySelector('.label-category-pill');
    expect(catEl?.textContent).toBe('General');

    const modelEl = compiled.querySelector('.label-model');
    expect(modelEl).toBeNull();

    const snEl = compiled.querySelector('.label-sn');
    expect(snEl).toBeNull();
  }));

  it('should trigger window.print when printLabels is invoked', () => {
    const printSpy = spyOn(window, 'print');
    component.printLabels();
    expect(printSpy).toHaveBeenCalled();
  });

  it('should emit close event when onClose is called or close button clicked', () => {
    spyOn(component.close, 'emit');
    component.onClose();
    expect(component.close.emit).toHaveBeenCalled();

    const compiled = fixture.nativeElement as HTMLElement;
    const closeBtn = compiled.querySelector('.secondary') as HTMLButtonElement;
    closeBtn?.click();
    expect(component.close.emit).toHaveBeenCalledTimes(2);
  });

  it('should handle empty assets array gracefully', () => {
    component.assets = [];
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.empty-state')).toBeTruthy();
    const printBtn = compiled.querySelector('.print-btn') as HTMLButtonElement;
    expect(printBtn?.disabled).toBeTrue();
  });
});
