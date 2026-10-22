import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { AssetImportComponent } from './asset-import.component';
import {
  AssetImportConfirmResponse,
  AssetImportPreviewResponse,
  RegistryService
} from '../../../services/registry.service';

describe('AssetImportComponent', () => {
  let component: AssetImportComponent;
  let fixture: ComponentFixture<AssetImportComponent>;
  let registrySpy: jasmine.SpyObj<RegistryService>;

  beforeEach(async () => {
    registrySpy = jasmine.createSpyObj('RegistryService', [
      'downloadAssetImportTemplate',
      'previewAssetImport',
      'confirmAssetImport'
    ]);

    await TestBed.configureTestingModule({
      imports: [AssetImportComponent],
      providers: [
        { provide: RegistryService, useValue: registrySpy }
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(AssetImportComponent);
    component = fixture.componentInstance;
    component.companyId = 'comp-123';
    component.canCreateAssets = true;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
    expect(component.selectedFile).toBeNull();
    expect(component.previewResult).toBeNull();
  });

  describe('Template Download', () => {
    it('should call registry downloadAssetImportTemplate with csv format', () => {
      const mockBlob = new Blob(['sample,csv'], { type: 'text/csv' });
      registrySpy.downloadAssetImportTemplate.and.returnValue(of(mockBlob));
      spyOn(window.URL, 'createObjectURL').and.returnValue('blob:http://localhost/dummy');
      spyOn(window.URL, 'revokeObjectURL');

      component.downloadTemplate('csv');

      expect(registrySpy.downloadAssetImportTemplate).toHaveBeenCalledWith('comp-123', 'csv');
      expect(component.templateDownloading).toBeFalse();
    });

    it('should call registry downloadAssetImportTemplate with xlsx format', () => {
      const mockBlob = new Blob(['fake-xlsx'], { type: 'application/vnd.openxmlformats' });
      registrySpy.downloadAssetImportTemplate.and.returnValue(of(mockBlob));
      spyOn(window.URL, 'createObjectURL').and.returnValue('blob:http://localhost/dummy');
      spyOn(window.URL, 'revokeObjectURL');

      component.downloadTemplate('xlsx');

      expect(registrySpy.downloadAssetImportTemplate).toHaveBeenCalledWith('comp-123', 'xlsx');
    });

    it('should handle template download failure gracefully', () => {
      registrySpy.downloadAssetImportTemplate.and.returnValue(
        throwError(() => ({ error: { detail: 'Template generation failed' } }))
      );

      component.downloadTemplate('csv');

      expect(component.errorMessage).toBe('Template generation failed');
      expect(component.templateDownloading).toBeFalse();
    });
  });

  describe('File Validation & Handling', () => {
    it('should reject unsupported file extensions', () => {
      const file = new File(['dummy'], 'assets.pdf', { type: 'application/pdf' });
      component.handleFile(file);

      expect(component.selectedFile).toBeNull();
      expect(component.errorMessage).toContain("Unsupported file type");
    });

    it('should reject files exceeding 5MB', () => {
      const largeFile = new File(['x'.repeat(100)], 'assets.csv', { type: 'text/csv' });
      Object.defineProperty(largeFile, 'size', { value: 6 * 1024 * 1024 });

      component.handleFile(largeFile);

      expect(component.selectedFile).toBeNull();
      expect(component.errorMessage).toContain('File size exceeds maximum allowed limit');
    });

    it('should accept valid CSV file and trigger preview', () => {
      const file = new File(['category_code\nLAPTOP\n'], 'assets.csv', { type: 'text/csv' });
      const mockPreview: AssetImportPreviewResponse = {
        valid: true,
        total_rows: 1,
        valid_rows: 1,
        invalid_rows: 0,
        preview_token: 'token-abc',
        errors: [],
        warnings: [],
        preview_rows: [
          {
            row_number: 2,
            category_code: 'LAPTOP',
            category_name: 'Laptops',
            serial_number: 'SN-1',
            manufacturer: 'Dell',
            model: 'XPS',
            status: 'in_stock',
            site_code: 'HQ',
            location_code: 'STORE',
            department_code: 'IT',
            cost_center_code: 'CC-1',
            acquisition_date: '2026-01-01',
            acquisition_cost: '1200.00',
            has_errors: false
          }
        ]
      };
      registrySpy.previewAssetImport.and.returnValue(of(mockPreview));

      component.handleFile(file);

      expect(component.selectedFile).toBe(file);
      expect(registrySpy.previewAssetImport).toHaveBeenCalledWith('comp-123', file);
      expect(component.previewResult).toEqual(mockPreview);
      expect(component.activeTab).toBe('preview');
    });

    it('should switch activeTab to errors if preview contains row errors', () => {
      const file = new File(['category_code\nINVALID\n'], 'assets.csv', { type: 'text/csv' });
      const mockPreview: AssetImportPreviewResponse = {
        valid: false,
        total_rows: 1,
        valid_rows: 0,
        invalid_rows: 1,
        preview_token: null,
        errors: [
          { row_number: 2, field: 'category_code', value: 'INVALID', message: 'Category not found' }
        ],
        warnings: [],
        preview_rows: []
      };
      registrySpy.previewAssetImport.and.returnValue(of(mockPreview));

      component.handleFile(file);

      expect(component.previewResult?.valid).toBeFalse();
      expect(component.activeTab).toBe('errors');
    });

    it('should display error when preview API call fails', () => {
      const file = new File(['data'], 'assets.xlsx', { type: 'application/vnd.openxmlformats' });
      registrySpy.previewAssetImport.and.returnValue(
        throwError(() => ({ error: { detail: 'Corrupted spreadsheet' } }))
      );

      component.handleFile(file);

      expect(component.isValidating).toBeFalse();
      expect(component.errorMessage).toBe('Corrupted spreadsheet');
    });
  });

  describe('Confirm Import', () => {
    it('should call registry confirmAssetImport and emit importCompleted on success', () => {
      component.previewResult = {
        valid: true,
        total_rows: 1,
        valid_rows: 1,
        invalid_rows: 0,
        preview_token: 'valid-token',
        errors: [],
        warnings: [],
        preview_rows: []
      };
      const mockConfirm: AssetImportConfirmResponse = {
        imported_count: 1,
        asset_numbers: ['AST-0001']
      };
      registrySpy.confirmAssetImport.and.returnValue(of(mockConfirm));
      spyOn(component.importCompleted, 'emit');

      component.confirmImport();

      expect(registrySpy.confirmAssetImport).toHaveBeenCalledWith('comp-123', 'valid-token');
      expect(component.confirmResult).toEqual(mockConfirm);
      expect(component.importCompleted.emit).toHaveBeenCalledWith({
        count: 1,
        assetNumbers: ['AST-0001']
      });
    });

    it('should handle confirm failure gracefully', () => {
      component.previewResult = {
        valid: true,
        total_rows: 1,
        valid_rows: 1,
        invalid_rows: 0,
        preview_token: 'expired-token',
        errors: [],
        warnings: [],
        preview_rows: []
      };
      registrySpy.confirmAssetImport.and.returnValue(
        throwError(() => ({ error: { detail: 'Token expired' } }))
      );

      component.confirmImport();

      expect(component.isImporting).toBeFalse();
      expect(component.errorMessage).toBe('Token expired');
    });
  });

  describe('Error Report Download', () => {
    it('should generate sanitized CSV error report and trigger download', () => {
      component.previewResult = {
        valid: false,
        total_rows: 2,
        valid_rows: 0,
        invalid_rows: 2,
        preview_token: null,
        errors: [
          { row_number: 2, field: 'category_code', value: '=CMD()', message: 'Formula attempted' },
          { row_number: 3, field: 'serial_number', value: 'SN-001', message: 'Duplicate serial' }
        ],
        warnings: [],
        preview_rows: []
      };

      spyOn(window.URL, 'createObjectURL').and.returnValue('blob:http://localhost/dummy');
      spyOn(window.URL, 'revokeObjectURL');

      component.downloadErrorReport();

      expect(window.URL.createObjectURL).toHaveBeenCalled();
      expect(window.URL.revokeObjectURL).toHaveBeenCalled();
    });
  });

  describe('Reset & Close', () => {
    it('should reset state on reset()', () => {
      component.selectedFile = new File([''], 'test.csv');
      component.errorMessage = 'Some error';
      component.activeTab = 'errors';

      component.reset();

      expect(component.selectedFile).toBeNull();
      expect(component.errorMessage).toBeNull();
      expect(component.activeTab).toBe('preview');
    });

    it('should emit close on onClose()', () => {
      spyOn(component.close, 'emit');
      component.onClose();
      expect(component.close.emit).toHaveBeenCalled();
    });
  });
});
