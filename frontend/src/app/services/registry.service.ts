import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

export interface Company {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
}

export interface MasterRecord {
  id: string;
  company_id: string;
  code: string;
  name: string;
  is_active: boolean;
  address?: string | null;
  details?: string | null;
  description?: string | null;
  site_id?: string;
}

export interface NumberRule {
  id: string;
  category_id: string | null;
  prefix: string;
  separator: string;
  padding: number;
}

export interface Asset {
  id: string;
  company_id: string;
  category_id: string;
  asset_number: string;
  serial_number: string | null;
  manufacturer: string | null;
  model: string | null;
  acquisition_date: string | null;
  acquisition_cost: string | null;
  status: string;
  site_id: string | null;
  location_id: string | null;
  responsible_department_id: string | null;
  cost_center_id: string | null;
  custodian_name: string | null;
  vendor_reference: string | null;
  invoice_reference: string | null;
  warranty_start: string | null;
  warranty_end: string | null;
  notes: string | null;
}

export interface AssetPage {
  items: Asset[];
  total: number;
  page: number;
  page_size: number;
}

export interface DepartmentUsage {
  id: string;
  department_id: string;
  purpose: string | null;
  started_at: string;
  ended_at: string | null;
}

export interface AssetHistory {
  id: string;
  event_type: string;
  field_name: string | null;
  old_value: string | null;
  new_value: string | null;
  occurred_at: string;
}

@Injectable({ providedIn: 'root' })
export class RegistryService {
  private readonly base = `${environment.apiBaseUrl}`;

  constructor(private readonly http: HttpClient) {}

  companies(): Observable<Company[]> {
    return this.http.get<Company[]>(`${this.base}/companies`);
  }

  createCompany(payload: { code: string; name: string; number_prefix: string }): Observable<Company> {
    return this.http.post<Company>(`${this.base}/companies`, payload);
  }

  updateCompany(companyId: string, payload: Partial<Pick<Company, 'name' | 'is_active'>>): Observable<Company> {
    return this.http.patch<Company>(`${this.base}/companies/${companyId}`, payload);
  }

  listMaster(companyId: string, kind: 'departments' | 'sites' | 'categories' | 'cost-centers'): Observable<MasterRecord[]> {
    return this.http.get<MasterRecord[]>(`${this.base}/companies/${companyId}/${kind}`);
  }

  createMaster(
    companyId: string,
    kind: 'departments' | 'sites' | 'categories' | 'cost-centers',
    payload: Record<string, string | boolean | null>
  ): Observable<MasterRecord> {
    return this.http.post<MasterRecord>(`${this.base}/companies/${companyId}/${kind}`, payload);
  }

  updateMaster(
    companyId: string,
    kind: 'departments' | 'sites' | 'categories' | 'cost-centers',
    id: string,
    payload: Record<string, string | boolean | null>
  ): Observable<MasterRecord> {
    return this.http.patch<MasterRecord>(`${this.base}/companies/${companyId}/${kind}/${id}`, payload);
  }

  deactivateMaster(companyId: string, kind: 'departments' | 'sites' | 'categories' | 'cost-centers', record: MasterRecord): Observable<MasterRecord> {
    if (kind === 'departments') {
      return this.http.delete<MasterRecord>(`${this.base}/companies/${companyId}/${kind}/${record.id}`);
    }
    return this.http.patch<MasterRecord>(`${this.base}/companies/${companyId}/${kind}/${record.id}`, { is_active: false });
  }

  listLocations(companyId: string, siteId: string): Observable<MasterRecord[]> {
    return this.http.get<MasterRecord[]>(`${this.base}/companies/${companyId}/sites/${siteId}/locations`);
  }

  createLocation(companyId: string, siteId: string, payload: Record<string, string | boolean | null>): Observable<MasterRecord> {
    return this.http.post<MasterRecord>(`${this.base}/companies/${companyId}/sites/${siteId}/locations`, payload);
  }

  updateLocation(companyId: string, siteId: string, locationId: string, payload: Record<string, string | boolean | null>): Observable<MasterRecord> {
    return this.http.patch<MasterRecord>(
      `${this.base}/companies/${companyId}/sites/${siteId}/locations/${locationId}`,
      payload
    );
  }

  deactivateLocation(companyId: string, siteId: string, location: MasterRecord): Observable<MasterRecord> {
    return this.http.patch<MasterRecord>(
      `${this.base}/companies/${companyId}/sites/${siteId}/locations/${location.id}`,
      { is_active: false }
    );
  }

  listNumberRules(companyId: string): Observable<NumberRule[]> {
    return this.http.get<NumberRule[]>(`${this.base}/companies/${companyId}/numbering-rules`);
  }

  saveNumberRule(companyId: string, payload: { prefix: string; separator: string; padding: number }, categoryId?: string): Observable<NumberRule> {
    let params = new HttpParams();
    if (categoryId) {
      params = params.set('category_id', categoryId);
    }
    return this.http.put<NumberRule>(`${this.base}/companies/${companyId}/numbering-rules`, payload, { params });
  }

  listAssets(companyId: string, filters: {
    page: number;
    page_size: number;
    search?: string;
    category_id?: string;
    status?: string;
    site_id?: string;
    location_id?: string;
    department_id?: string;
  }): Observable<AssetPage> {
    let params = new HttpParams().set('page', filters.page).set('page_size', filters.page_size);
    for (const [key, value] of Object.entries(filters)) {
      if (key !== 'page' && key !== 'page_size' && value) {
        params = params.set(key, value);
      }
    }
    return this.http.get<AssetPage>(`${this.base}/companies/${companyId}/assets`, { params });
  }

  getAsset(companyId: string, assetId: string): Observable<Asset> {
    return this.http.get<Asset>(`${this.base}/companies/${companyId}/assets/${assetId}`);
  }

  createAsset(companyId: string, payload: Partial<Asset>): Observable<Asset> {
    return this.http.post<Asset>(`${this.base}/companies/${companyId}/assets`, payload);
  }

  updateAsset(companyId: string, assetId: string, payload: Partial<Asset>): Observable<Asset> {
    return this.http.patch<Asset>(`${this.base}/companies/${companyId}/assets/${assetId}`, payload);
  }

  usages(companyId: string, assetId: string, includeEnded = true): Observable<DepartmentUsage[]> {
    return this.http.get<DepartmentUsage[]>(`${this.base}/companies/${companyId}/assets/${assetId}/usages`, {
      params: { include_ended: includeEnded }
    });
  }

  startUsage(companyId: string, assetId: string, payload: { department_id: string; purpose: string }): Observable<DepartmentUsage> {
    return this.http.post<DepartmentUsage>(`${this.base}/companies/${companyId}/assets/${assetId}/usages`, payload);
  }

  endUsage(companyId: string, assetId: string, usageId: string): Observable<DepartmentUsage> {
    return this.http.post<DepartmentUsage>(
      `${this.base}/companies/${companyId}/assets/${assetId}/usages/${usageId}/end`,
      {}
    );
  }

  history(companyId: string, assetId: string): Observable<AssetHistory[]> {
    return this.http.get<AssetHistory[]>(`${this.base}/companies/${companyId}/assets/${assetId}/history`);
  }
}
