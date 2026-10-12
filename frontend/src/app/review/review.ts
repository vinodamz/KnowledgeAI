import {
  Component,
  effect,
  inject,
  signal,
  untracked,
  OnDestroy,
} from "@angular/core";
import { FormsModule } from "@angular/forms";
import { JsonPipe, DatePipe } from "@angular/common";
import { Api } from "../core/api";
import {
  Candidate,
  Publication,
  Job,
  Upload,
  Schema,
  Payload,
} from "../core/contracts";
@Component({
  selector: "ka-review",
  imports: [FormsModule, JsonPipe, DatePipe],
  templateUrl: "./review.html",
})
export class Review implements OnDestroy {
  api = inject(Api);
  rows = signal<Candidate[]>([]);
  candidate = signal<Candidate | null>(null);
  jobs = signal<Publication[]>([]);
  uploadJob = signal<Job | null>(null);
  selected = new Map<string, number>();
  reason = "";
  editName = "";
  editDescription = "";
  editAttributes: { key: string; value: string; original: unknown }[] = [];
  sourceEndpoint = "";
  targetEndpoint = "";
  file: File | null = null;
  compareRevision = 0;
  monitorError = signal("");
  private pollRequest = 0;
  private loadRequest = 0;
  private timer: ReturnType<typeof setInterval> | undefined;
  constructor() {
    effect(() => {
      const id = this.api.versionId();
      const loading = this.api.scopeLoading();
      untracked(() => {
        this.pollRequest++;
        this.loadRequest++;
        this.monitorError.set("");
        this.jobs.set([]);
        this.file = null;
        this.selected.clear();
        this.candidate.set(null);
        this.rows.set([]);
        this.uploadJob.set(null);
        if (!loading && this.api.canEdit && id)
          void this.api.run(() => this.load(), false);
      });
    });
    this.timer = setInterval(() => {
      if (this.api.canEdit && this.api.versionId()) void this.poll();
    }, 3000);
  }
  ngOnDestroy() {
    clearInterval(this.timer);
  }
  get latest() {
    return this.rows().filter((c) => c.revision === c.latest_revision);
  }
  get entities() {
    return this.latest.filter((c) => c.kind === "entity");
  }
  get previous() {
    const c = this.candidate();
    return this.rows().find(
      (x) => x.id === c?.id && x.revision === this.compareRevision,
    );
  }
  label(c: Candidate) {
    return String(c.payload.name || c.payload.type_name || c.kind);
  }
  status(c: Candidate) {
    return (
      (
        {
          draft: "Draft",
          approved_awaiting_publication: "Approved — awaiting publication",
          approved_but_blocked: "Blocked",
          published: "Published",
          rejected: "Rejected",
          changes_requested: "Changes requested",
        } as Record<string, string>
      )[c.status] || c.status
    );
  }
  async load() {
    const request = ++this.loadRequest;
    const id = this.api.versionId();
    const [rows, jobs] = await Promise.all([
      this.api.request<Candidate[]>("/versions/" + id + "/candidates"),
      this.api.request<Publication[]>("/publications?version_id=" + id),
    ]);
    if (
      request !== this.loadRequest ||
      id !== this.api.versionId() ||
      this.api.scopeLoading()
    )
      return;
    this.rows.set(rows);
    this.jobs.set(jobs);
    const old = this.candidate();
    this.choose(
      rows.find((c) => c.id === old?.id && c.revision === c.latest_revision) ||
        this.latest[0] ||
        null,
    );
    this.selected.clear();
  }
  refresh() {
    void this.api.run(() => this.load());
  }
  choose(c: Candidate | null) {
    this.candidate.set(c);
    this.editName = String(c?.payload.name || "");
    this.editDescription = String(c?.payload.description || "");
    this.editAttributes = Object.entries(c?.payload.attributes || {}).map(
      ([key, v]) => ({
        key,
        value: typeof v === "string" ? v : JSON.stringify(v),
        original: v,
      }),
    );
    this.sourceEndpoint = c?.payload.source_candidate_id || "";
    this.targetEndpoint = c?.payload.target_candidate_id || "";
    this.compareRevision = c && c.revision > 1 ? c.revision - 1 : 0;
  }
  toggle(c: Candidate) {
    if (this.selected.has(c.id)) this.selected.delete(c.id);
    else this.selected.set(c.id, c.revision);
  }
  review(decision: "approve" | "reject" | "request_changes", batch = false) {
    void this.api.run(async () => {
      if (batch) {
        const body: Schema<"BatchInput"> = {
          candidates: [...this.selected].map(([candidate_id, revision]) => ({
            candidate_id,
            revision,
          })),
          decision,
          reason: this.reason || null,
        };
        await this.api.request("/review/batch", "POST", body);
      } else {
        const c = this.candidate()!;
        const body: Schema<"ReviewInput"> = {
          expected_revision: c.revision,
          decision,
          reason: this.reason || null,
        };
        await this.api.request("/candidates/" + c.id + "/review", "POST", body);
      }
      await this.load();
      this.reason = "";
    });
  }
  save() {
    void this.api.run(async () => {
      const c = this.candidate()!;
      const payload: Payload = structuredClone(c.payload);
      if (c.kind === "entity" || payload["suggestion_kind"] === "entity") {
        payload.name = this.editName;
        payload.attributes = Object.fromEntries(
          this.editAttributes.map((a) => {
            let v: unknown = a.value;
            if (typeof a.original !== "string") {
              try {
                v = JSON.parse(a.value);
              } catch {
                throw new Error(
                  "Attribute " + a.key + " must retain its original data type.",
                );
              }
            }
            return [a.key, v];
          }),
        );
      }
      if (this.editDescription || "description" in payload)
        payload.description = this.editDescription;
      if (c.kind === "relation" || payload["suggestion_kind"] === "relation") {
        const source = this.entities.find((e) => e.id === this.sourceEndpoint),
          target = this.entities.find((e) => e.id === this.targetEndpoint);
        if (!source || !target)
          throw new Error("Select exact current source and target entities.");
        payload.source_candidate_id = source.id;
        payload.source_candidate_revision = source.revision;
        payload.target_candidate_id = target.id;
        payload.target_candidate_revision = target.revision;
      }
      const body: Schema<"EditInput"> = {
        expected_revision: c.revision,
        payload,
      };
      await this.api.request("/candidates/" + c.id, "PATCH", body);
      await this.load();
      this.api.notice.set(
        "New draft revision saved. Previous approval does not apply to this revision.",
      );
    });
  }
  fileChanged(event: Event) {
    this.file = (event.target as HTMLInputElement).files?.[0] || null;
  }
  upload() {
    void this.api.run(async () => {
      if (!this.file) return;
      const version = this.api.versionId();
      const data = new FormData();
      data.append("file", this.file);
      const result = await this.api.request<Upload>(
        "/versions/" + version + "/sources",
        "POST",
        data,
      );
      const job = await this.api.request<Job>("/jobs/" + result.job_id);
      sessionStorage.setItem("ka-upload-" + version, result.job_id);
      if (version !== this.api.versionId() || this.api.scopeLoading()) return;
      this.uploadJob.set(job);
      this.api.notice.set(
        result.duplicate
          ? "This exact source already exists; following its extraction job."
          : "Source uploaded. Extraction runs in the background.",
      );
    });
  }
  async poll(strict = false) {
    const version = this.api.versionId();
    const request = ++this.pollRequest;
    if (!version || this.api.scopeLoading()) return;
    try {
      const id =
        this.uploadJob()?.id || sessionStorage.getItem("ka-upload-" + version);
      const [job, jobs] = await Promise.all([
        id ? this.api.request<Job>("/jobs/" + id) : Promise.resolve(null),
        this.api.request<Publication[]>("/publications?version_id=" + version),
      ]);
      if (
        version !== this.api.versionId() ||
        this.api.scopeLoading() ||
        request !== this.pollRequest
      )
        return;
      if (job) this.uploadJob.set(job);
      this.jobs.set(jobs);
      this.monitorError.set("");
    } catch (error) {
      if (version !== this.api.versionId() || this.api.scopeLoading()) return;
      if (request === this.pollRequest)
        this.monitorError.set(
          "Status monitoring unavailable for the selected version. Last known job states may be outdated. " +
            (error instanceof Error
              ? error.message
              : "Unable to fetch job status."),
        );
      if (strict) throw error;
    }
  }

  refreshStatus() {
    void this.api.run(() => this.poll(true));
  }

  publish() {
    void this.api.run(async () => {
      const body: Schema<"PublishInput"> = {
        profile_id: this.api.profileId(),
        version_id: this.api.versionId(),
        candidates: [...this.selected].map(([candidate_id, revision]) => ({
          candidate_id,
          revision,
        })),
        idempotency_key: crypto.randomUUID(),
      };
      const job = await this.api.request<Publication>(
        "/publications",
        "POST",
        body,
      );
      if (body.version_id !== this.api.versionId() || this.api.scopeLoading())
        return;
      this.jobs.update((js) => [job, ...js]);
      this.api.notice.set(
        "Publication queued. Approval remains separate from verified publication.",
      );
    });
  }
  retry(job: Publication) {
    void this.api.run(async () => {
      await this.api.request("/publications/" + job.id + "/retry", "POST");
      await this.poll(true);
    });
  }
}
