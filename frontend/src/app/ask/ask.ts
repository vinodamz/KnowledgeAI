import { Component, effect, inject, signal, untracked } from "@angular/core";
import { FormsModule } from "@angular/forms";
import { Api } from "../core/api";
import { Answer, Schema } from "../core/contracts";
import { Citations } from "../core/citations";
@Component({
  selector: "ka-ask",
  imports: [FormsModule, Citations],
  template: `
    <div class="page-heading">
      <div>
        <p class="eyebrow">APPROVED KNOWLEDGE ONLY</p>
        <h1>Ask Knowledge AI</h1>
        <p class="muted">
          Answers stay within the selected version and its exact authorized
          dependencies.
        </p>
      </div>
    </div>
    <section class="panel ask-form">
      <form (ngSubmit)="ask()">
        <label
          >Answer context<select
            name="context"
            [(ngModel)]="contextId"
            (ngModelChange)="answer.set(null)"
          >
            <option value="">Choose an authorized version</option>
            @for (c of api.contexts(); track c.version_id) {
              <option [value]="c.version_id">
                {{ c.profile_name }} / {{ c.version_label }} ·
                {{
                  c.version_status === "draft"
                    ? "Published facts in authoring version"
                    : c.version_status
                }}
              </option>
            }
          </select></label
        >
        <p class="muted small">Draft candidates are never an answer context.</p>
        <label
          >Your question<textarea
            name="question"
            [value]="question()"
            (input)="question.set($any($event.target).value)"
            maxlength="4000"
            rows="4"
            placeholder="Ask about approved entities, relationships or implementation details"
            required
          ></textarea></label
        ><button
          class="primary"
          [disabled]="!contextId || !question().trim() || api.busy()"
        >
          Ask selected context
        </button>
      </form>
    </section>
    @if (answer(); as a) {
      <section class="panel answer" aria-live="polite">
        <div class="section-heading">
          <h2>
            {{
              a.status === "answered"
                ? "Answer"
                : "Insufficient approved knowledge"
            }}
          </h2>
          <span class="tag">Approved only</span>
        </div>
        <p class="answer-text">{{ a.text }}</p>
        <p class="muted">
          Pinned generation
          <code>{{ a.context.policy_context.generation_id || "None" }}</code> ·
          {{ a.context.policy_context.allowed_version_ids.length }} authorized
          version(s)
        </p>
        @if (a.context.policy_context.conflicts.length) {
          <div class="alert warning">
            Approved sources contain differing claims. Compare the cited
            evidence before deciding.
          </div>
        }
        @if (a.context.policy_context.implementation_overrides.length) {
          <div class="alert">
            Project implementation differs from linked product knowledge. Both
            attributions are preserved.
          </div>
        }
        <h3>Citations</h3>
        <ka-citations [items]="a.citations" />
        @if (!a.citations.length) {
          <p>
            No approved supporting citations were found. Publish relevant
            reviewed knowledge before asking again.
          </p>
        }
      </section>
    } @else if (!api.contexts().length) {
      <div class="empty">
        <h2>No authorized answer contexts</h2>
        <p>
          Ask an owner to publish and release a version, and an administrator to
          grant access.
        </p>
      </div>
    }
  `,
})
export class Ask {
  api = inject(Api);
  contextId = "";
  question = signal("");
  answer = signal<Answer | null>(null);
  constructor() {
    effect(() => {
      const id = this.api.versionId();
      untracked(() => {
        this.answer.set(null);
        this.contextId = this.api.contexts().some((c) => c.version_id === id)
          ? id
          : "";
      });
    });
  }
  ask() {
    void this.api.run(async () => {
      const c = this.api
        .contexts()
        .find((c) => c.version_id === this.contextId);
      if (!c) return;
      const body: Schema<"AskInput"> = {
        profile_id: c.profile_id,
        version_id: c.version_id,
        query: this.question(),
      };
      const answer = await this.api.request<Answer>("/ask", "POST", body);
      if (c.version_id === this.contextId && !this.api.scopeLoading())
        this.answer.set(answer);
    });
  }
}
