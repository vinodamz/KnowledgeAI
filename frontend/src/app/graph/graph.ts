import { Component, inject, signal } from "@angular/core";
import { FormsModule } from "@angular/forms";
import { Api } from "../core/api";
import { Graph, Schema } from "../core/contracts";
import { Citations } from "../core/citations";
type Item = Schema<"ItemResponse">;
@Component({
  selector: "ka-graph",
  imports: [FormsModule, Citations],
  template: `
    <div class="page-heading">
      <div>
        <p class="eyebrow">CENTRAL PUBLISHED GRAPH</p>
        <h1>Central Graph</h1>
        <p class="muted">
          Original typed, directed relationships from verified publication
          generations.
        </p>
      </div>
    </div>
    <section class="panel">
      <h2>Profile & version filters</h2>
      <div class="context-options">
        @for (c of api.contexts(); track c.version_id) {
          <label class="check"
            ><input
              type="checkbox"
              [checked]="versionIds.includes(c.version_id)"
              (change)="toggle(c.version_id)"
            />{{ c.profile_name }} / {{ c.version_label }} ·
            {{ c.version_status }}</label
          >
        } @empty {
          <p>No authorized versions available.</p>
        }
      </div>
      <button
        class="primary"
        (click)="load()"
        [disabled]="!versionIds.length || api.busy()"
      >
        Load published graph
      </button>
    </section>
    @if (graph(); as g) {
      <section class="panel">
        <div class="section-heading">
          <h2>
            {{ g.nodes.length }} entities · {{ g.edges.length }} relations
          </h2>
          <div>
            <button (click)="zoom = zoom + 0.2" aria-label="Zoom in">+</button
            ><button
              (click)="zoom = Math.max(0.4, zoom - 0.2)"
              aria-label="Zoom out"
            >
              −</button
            ><button (click)="zoom = 1">Reset view</button>
          </div>
        </div>
        @if (g.nodes.length) {
          <div class="graph-scroll">
            <svg
              class="graph-canvas"
              [attr.viewBox]="'0 0 ' + width + ' ' + height"
              [style.width.px]="width * zoom"
              [style.height.px]="height * zoom"
              aria-label="Published directed knowledge graph"
            >
              <defs>
                <marker
                  id="arrow"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="8"
                  markerHeight="8"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="#69788e" />
                </marker>
              </defs>
              @for (e of g.edges; track e.id) {
                <g
                  class="graph-edge"
                  tabindex="0"
                  role="button"
                  [attr.aria-label]="'Inspect relation ' + e.claim"
                  (click)="inspect(e)"
                  (keydown.enter)="inspect(e)"
                  (keydown.space)="$event.preventDefault(); inspect(e)"
                >
                  <line
                    [attr.x1]="point(e.source).x"
                    [attr.y1]="point(e.source).y"
                    [attr.x2]="point(e.target).x"
                    [attr.y2]="point(e.target).y - 24"
                    marker-end="url(#arrow)"
                  />
                  <text
                    [attr.x]="(point(e.source).x + point(e.target).x) / 2"
                    [attr.y]="(point(e.source).y + point(e.target).y) / 2 - 8"
                  >
                    {{ e.payload["type_name"] }}
                  </text>
                </g>
              }
              @for (n of g.nodes; track n.id) {
                <g
                  class="graph-node"
                  tabindex="0"
                  role="button"
                  [attr.aria-label]="'Inspect entity ' + name(n)"
                  (click)="inspect(n)"
                  (keydown.enter)="inspect(n)"
                  (keydown.space)="$event.preventDefault(); inspect(n)"
                  [attr.transform]="
                    'translate(' + point(n.id).x + ',' + point(n.id).y + ')'
                  "
                >
                  <circle r="25" />
                  <text y="48">{{ name(n) }}</text>
                  <text class="node-type" y="65">
                    {{ n.payload["type_name"] }}
                  </text>
                </g>
              }
            </svg>
          </div>
        } @else {
          <div class="empty">
            <h3>No published facts in these versions</h3>
            <p>
              Review and publish source candidates before exploring the graph.
            </p>
          </div>
        }
        <details>
          <summary>Accessible relation list</summary>
          <ul class="rows">
            @for (e of g.edges; track e.id) {
              <li>
                <button (click)="inspect(e)">{{ e.claim }}</button>
              </li>
            }
          </ul>
        </details>
      </section>
    }
    @if (selected(); as n) {
      <section class="panel">
        <p class="eyebrow">{{ n.kind }} · PUBLISHED</p>
        <h2>{{ n.claim }}</h2>
        <p>Original type: {{ n.payload["type_name"] }}</p>
        <ka-citations [items]="[n.attribution]" />
      </section>
    }
  `,
})
export class GraphPage {
  api = inject(Api);
  Math = Math;
  versionIds: string[] = [];
  graph = signal<Graph | null>(null);
  selected = signal<Item | null>(null);
  zoom = 1;
  width = 900;
  height = 520;
  constructor() {
    const id = this.api.versionId();
    if (this.api.contexts().some((c) => c.version_id === id))
      this.versionIds = [id];
  }
  toggle(id: string) {
    this.versionIds = this.versionIds.includes(id)
      ? this.versionIds.filter((x) => x !== id)
      : [...this.versionIds, id];
  }
  load() {
    void this.api.run(async () => {
      this.selected.set(null);
      this.graph.set(
        await this.api.request<Graph>(
          "/graph?" +
            this.versionIds
              .map((id) => "version_ids=" + encodeURIComponent(id))
              .join("&"),
        ),
      );
    });
  }
  name(n: Item) {
    return String(n.payload["name"] || n.payload["type_name"] || n.kind);
  }
  point(id: string) {
    const nodes = this.graph()?.nodes || [];
    const i = Math.max(
      0,
      nodes.findIndex((n) => n.id === id),
    );
    const angle = (2 * Math.PI * i) / Math.max(nodes.length, 1) - Math.PI / 2;
    return { x: 450 + 300 * Math.cos(angle), y: 240 + 160 * Math.sin(angle) };
  }
  inspect(n: Item) {
    this.selected.set(n);
  }
}
