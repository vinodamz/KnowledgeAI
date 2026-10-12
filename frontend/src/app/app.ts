import { Component, HostListener, inject } from "@angular/core";
import { FormsModule } from "@angular/forms";
import { RouterLink, RouterLinkActive, RouterOutlet } from "@angular/router";
import { Api } from "./core/api";
@Component({
  selector: "ka-app",
  imports: [FormsModule, RouterLink, RouterLinkActive, RouterOutlet],
  template: `
    <a class="skip" href="#main">Skip to content</a>
    @if (!api.ready()) {
      <main class="login"><p role="status">Opening your workspace…</p></main>
    } @else if (!api.actor()) {
      <main class="login" id="main">
        <div class="brand-mark">K<span>AI</span></div>
        <h1>Knowledge AI</h1>
        <p class="muted">Governed knowledge. Traceable answers.</p>
        <form (ngSubmit)="signin()">
          <h2>Sign in</h2>
          <label
            >Username<input
              name="username"
              autocomplete="username"
              [(ngModel)]="username"
              required /></label
          ><label
            >Password<input
              name="password"
              type="password"
              autocomplete="current-password"
              [(ngModel)]="password"
              required /></label
          ><button class="primary" [disabled]="api.busy()">Sign in</button>
        </form>
        @if (api.error()) {
          <p class="alert error" role="alert">{{ api.error() }}</p>
        }
      </main>
    } @else {
      <div class="shell">
        <header class="workspace-header">
          <div class="navigation-bar">
            <a routerLink="/graph" class="brand" aria-label="Knowledge AI home"
              ><div class="brand-mark">K<span>AI</span></div>
              <strong>Knowledge AI</strong></a
            >
            <nav class="primary-navigation" aria-label="Main navigation">
              @for (item of nav; track item.path) {
                <a
                  [routerLink]="item.path"
                  routerLinkActive="active"
                  [attr.aria-label]="item.name"
                  >{{ item.label }}</a
                >
              }
              <div class="manage">
                <button
                  class="manage-toggle"
                  type="button"
                  aria-controls="manage-links"
                  [attr.aria-expanded]="manageOpen"
                  (click)="manageOpen = !manageOpen"
                >
                  Manage <span aria-hidden="true">⌄</span>
                </button>
                @if (manageOpen) {
                  <nav
                    id="manage-links"
                    class="manage-links"
                    aria-label="Manage workspace"
                  >
                    @for (item of management; track item.path) {
                      <a
                        [routerLink]="item.path"
                        routerLinkActive="active"
                        (click)="manageOpen = false"
                        >{{ item.name }}</a
                      >
                    }
                  </nav>
                }
              </div>
            </nav>
            <div class="account">
              <span>{{ api.actor()?.role }}</span
              ><button class="quiet" (click)="api.run(logout.bind(this))">
                Sign out
              </button>
            </div>
          </div>
          <div class="context-bar" aria-label="Selected knowledge context">
            <label
              >Profile<select
                aria-label="Profile"
                [ngModel]="api.profileId()"
                (ngModelChange)="api.run(selectProfile.bind(this, $event))"
              >
                <option value="">Select profile</option>
                @for (p of api.profiles(); track p.id) {
                  <option [value]="p.id">{{ p.name }} · {{ p.kind }}</option>
                }
              </select></label
            ><label
              >Knowledge version<select
                aria-label="Knowledge version"
                [ngModel]="api.versionId()"
                (ngModelChange)="api.selectVersion($event)"
              >
                <option value="">Select version</option>
                @for (v of api.versions(); track v.id) {
                  <option [value]="v.id">{{ v.label }} · {{ v.status }}</option>
                }
              </select></label
            >

          </div>
        </header>
        <div class="workspace">
          <main id="main" tabindex="-1">
            @if (api.error()) {
              <div class="alert error" role="alert">
                {{ api.error()
                }}<button
                  class="quiet"
                  (click)="api.error.set('')"
                  aria-label="Dismiss error"
                >
                  ×
                </button>
              </div>
            }
            @if (api.notice()) {
              <div class="alert success" role="status">{{ api.notice() }}</div>
            }
            @if (api.busy()) {
              <div class="working" role="status">Working…</div>
            }
            <router-outlet />
          </main>
        </div>
      </div>
    }
  `,
})
export class App {
  api = inject(Api);
  username = "";
  password = "";
  manageOpen = false;
  nav = [
    { path: "/graph", name: "Knowledge — Central Graph", label: "Knowledge" },
    { path: "/review", name: "Review Inbox", label: "Review" },
    { path: "/ask", name: "Ask Knowledge AI", label: "Ask" },
  ];
  management = [
    { path: "/profiles", name: "Profiles" },
    { path: "/models", name: "Knowledge Models" },
    { path: "/activity", name: "Activity" },
  ];
  @HostListener("document:click", ["$event"])
  closeOutside(event: MouseEvent) {
    if (!(event.target instanceof Element && event.target.closest(".manage")))
      this.manageOpen = false;
  }
  @HostListener("document:keydown.escape", ["$event"])
  closeManage(event: Event) {
    if (!this.manageOpen) return;
    this.manageOpen = false;
    event.preventDefault();
    (document.querySelector(".manage-toggle") as HTMLElement)?.focus();
  }
  constructor() {
    void this.api.init();
  }
  signin() {
    void this.api.run(async () => {
      await this.api.login(this.username, this.password);
      this.password = "";
    });
  }
  async selectProfile(id: string) {
    await this.api.selectProfile(id);
  }
  async logout() {
    await this.api.logout();
  }
}
