import { Routes } from '@angular/router';

import { RegistryComponent } from './components/registry/registry.component';
import { StatusComponent } from './components/status/status.component';

export const routes: Routes = [
  { path: '', component: RegistryComponent },
  { path: 'status', component: StatusComponent },
  { path: '**', redirectTo: '' }
];
