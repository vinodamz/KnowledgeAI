import { Component, inject, signal } from "@angular/core";
import { FormsModule } from "@angular/forms";
import { DatePipe, JsonPipe } from "@angular/common";
import { Api } from "../core/api";
import { Activity } from "../core/contracts";
@Component({
  selector: "ka-activity",
  imports: [FormsModule, DatePipe, JsonPipe],
  template: `<div class="page-heading">
      <div>
        <p class="eyebrow">GOVERNANCE TRAIL</p>
        <h1>Activity</h1>
        <p class="muted">
          Recent events within your current authorized scopes.
        </p>
      </div>
      <button (click)="load()">Refresh activity</button>
    </div>
    <section class="panel">
      <label
        >Profile filter<select [(ngModel)]="profileId" (ngModelChange)="load()">
          <option value="">All authorized profiles</option>
          @for (p of api.profiles(); track p.id) {
            <option [value]="p.id">{{ p.name }}</option>
          }
        </select></label
      >
      <ol class="timeline">
        @for (e of events(); track e.id) {
          <li>
            <time>{{ e.created_at | date: "medium" }}</time>
            <h3>{{ e.action.replaceAll("_", " ") }}</h3>
            <p>{{ profileName(e.profile_id) }}</p>
            @if (hasDetails(e)) {
              <details>
                <summary>Event details</summary>
                <pre>{{ e.details | json }}</pre>
              </details>
            }
          </li>
        } @empty {
          <li>
            <h3>No activity in this scope</h3>
            <p>Events appear as authorized work is completed.</p>
          </li>
        }
      </ol>
      <p class="muted small">
        Showing up to 200 recent events. Read-only access excludes private draft
        event details.
      </p>
    </section>`,
})
export class ActivityPage {
  api = inject(Api);
  profileId = "";
  events = signal<Activity[]>([]);
  constructor() {
    this.load();
  }
  load() {
    void this.api.run(async () =>
      this.events.set(
        await this.api.request<Activity[]>(
          "/activity" + (this.profileId ? "?profile_id=" + this.profileId : ""),
        ),
      ),
    );
  }
  profileName(id: string | null) {
    return (
      this.api.profiles().find((p) => p.id === id)?.name || "Account activity"
    );
  }
  hasDetails(e: Activity) {
    return Object.keys(e.details).length > 0;
  }
}
