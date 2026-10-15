import { Routes } from '@angular/router';

import { authenticatedGuard } from './auth/auth.guard';
import { InvitationComponent } from './components/auth/invitation.component';
import { LoginComponent } from './components/auth/login.component';
import { RegistryComponent } from './components/registry/registry.component';
import { StatusComponent } from './components/status/status.component';

export const routes: Routes = [
  { path: '', component: RegistryComponent, canActivate: [authenticatedGuard] },
  { path: 'login', component: LoginComponent },
  { path: 'invite', component: InvitationComponent },
  { path: 'status', component: StatusComponent },
  { path: '**', redirectTo: '' }
];
