import { Component, effect, inject, signal, untracked } from "@angular/core";
import { FormsModule } from "@angular/forms";
import { Api } from "../core/api";
import { Model, Entity, Relation, Concept, Schema } from "../core/contracts";
@Component({
  selector: "ka-models",
  imports: [FormsModule],
  templateUrl: "./models.html",
})
export class Models {
  api = inject(Api);
  models = signal<Model[]>([]);
  model = signal<Model | null>(null);
  description = "";
  entityId = "";
  entityName = "";
  attributes: { name: string; data_type: string; description: string }[] = [];
  scores: Record<string, string> = {};
  scoreFields = [
    "identity",
    "lifecycle",
    "relationships",
    "own_attributes",
    "reuse",
    "retrieval_rationale",
  ];
  qualification = "";
  relationId = "";
  relationName = "";
  sourceType = "";
  targetType = "";
  conceptId = "";
  conceptName = "";
  aliases = "";
  links: string[] = [];
  linkModels = signal<(Model & { profileName: string })[]>([]);
  private loadRequest = 0;
  constructor() {
    effect(() => {
      const id = this.api.profileId();
      const loading = this.api.scopeLoading();
      untracked(() => {
        this.loadRequest++;
        this.models.set([]);
        this.linkModels.set([]);
        this.select(null);
        if (!loading && id) void this.api.run(() => this.load(id), false);
      });
    });
  }
  get editable() {
    return this.api.canEdit && this.model()?.status === "draft";
  }
  async load(id = this.api.profileId()) {
    const request = ++this.loadRequest;
    const selectedId = this.model()?.id;
    try {
      const models = id
        ? await this.api.request<Model[]>("/profiles/" + id + "/models")
        : [];
      if (
        request !== this.loadRequest ||
        id !== this.api.profileId() ||
        this.api.scopeLoading()
      )
        return;
      this.models.set(models);
      this.select(
        models.find((m) => m.id === selectedId) || models.at(-1) || null,
      );
      const lists = await Promise.all(
        this.api
          .profiles()
          .filter((p) => p.id !== id)
          .map(async (p) =>
            (await this.api.request<Model[]>("/profiles/" + p.id + "/models"))
              .filter((m) => m.status === "published")
              .map((m) => ({ ...m, profileName: p.name })),
          ),
      );
      if (
        request === this.loadRequest &&
        id === this.api.profileId() &&
        !this.api.scopeLoading()
      )
        this.linkModels.set(lists.flat());
    } catch (error) {
      if (
        request === this.loadRequest &&
        id === this.api.profileId() &&
        !this.api.scopeLoading()
      )
        throw error;
    }
  }

  select(m: Model | null) {
    this.model.set(m);
    this.description = m?.semantic_description || "";
    this.links = m?.target_model_revision_ids || [];
    this.resetEntity();
    this.relationId = "";
    this.relationName = "";
    this.sourceType = "";
    this.targetType = "";
    this.conceptId = "";
    this.conceptName = "";
    this.aliases = "";
  }
  refresh() {
    void this.api.run(() => this.load());
  }
  create() {
    void this.api.run(async () => {
      if (!this.api.canEdit)
        throw new Error("Select a fully loaded editable profile.");
      const profile = this.api.profileId();
      const body: Schema<"ModelInput"> = {
        semantic_description: this.description,
      };
      const m = await this.api.request<Model>(
        "/profiles/" + profile + "/models",
        "POST",
        body,
      );
      if (profile !== this.api.profileId() || this.api.scopeLoading()) return;
      this.models.update((ms) => [...ms, m]);
      this.select(m);
    });
  }
  async mutation(path: string, method: string, body?: unknown) {
    const model = this.model();
    const profile = this.api.profileId();
    if (!model || model.profile_id !== profile || !this.api.canEdit)
      throw new Error("Select a fully loaded model in the current profile.");
    const updated = await this.api.request<Model>(
      "/models/" + model.id + path,
      method,
      body,
    );
    if (
      profile !== this.api.profileId() ||
      this.api.scopeLoading() ||
      this.model()?.id !== model.id
    )
      return;
    this.model.set(updated);
    this.models.update((ms) =>
      ms.map((m) => (m.id === updated.id ? updated : m)),
    );
  }

  saveDescription() {
    void this.api.run(async () => {
      const body: Schema<"ModelInput"> = {
        semantic_description: this.description,
      };
      await this.mutation("", "PATCH", body);
    });
  }
  resetEntity() {
    this.entityId = "";
    this.entityName = "";
    this.attributes = [];
    this.scores = {};
    this.qualification = "";
  }
  editEntity(e: Entity) {
    this.entityId = e.id;
    this.entityName = e.name;
    this.attributes = structuredClone(e.attributes);
    this.scores = Object.fromEntries(
      Object.entries(e.scores).map(([k, v]) => [k, String(v)]),
    );
    this.qualification = e.qualification || "";
  }
  saveEntity() {
    void this.api.run(async () => {
      const scores = Object.fromEntries(
        Object.entries(this.scores)
          .filter(([, v]) => v.trim())
          .map(([k, v]) => [
            k,
            k !== "retrieval_rationale" && Number.isFinite(Number(v))
              ? Number(v)
              : v,
          ]),
      );
      const body: Schema<"EntityInput"> = {
        name: this.entityName,
        attributes: this.attributes,
        scores,
      };
      await this.mutation(
        "/entities" + (this.entityId ? "/" + this.entityId : ""),
        this.entityId ? "PUT" : "POST",
        body,
      );
      this.resetEntity();
    });
  }
  qualify(e: Entity) {
    void this.api.run(async () => {
      const body: Schema<"Qualification"> = {
        qualification: this.qualification,
      };
      await this.mutation("/entities/" + e.id + "/qualification", "PUT", body);
    });
  }
  editRelation(r: Relation) {
    this.relationId = r.id;
    this.relationName = r.name;
    this.sourceType = r.source_type_id;
    this.targetType = r.target_type_id;
  }
  saveRelation() {
    void this.api.run(async () => {
      const body: Schema<"RelationInput"> = {
        name: this.relationName,
        source_type_id: this.sourceType,
        target_type_id: this.targetType,
      };
      await this.mutation(
        "/relations" + (this.relationId ? "/" + this.relationId : ""),
        this.relationId ? "PUT" : "POST",
        body,
      );
      this.relationId = "";
      this.relationName = "";
    });
  }
  editConcept(c: Concept) {
    this.conceptId = c.id;
    this.conceptName = c.name;
    this.aliases = c.aliases.join("\n");
  }
  saveConcept() {
    void this.api.run(async () => {
      const old = this.model()?.concepts.find((c) => c.id === this.conceptId);
      const body: Schema<"ConceptInput"> = {
        name: this.conceptName,
        aliases: this.aliases
          .split("\n")
          .map((x) => x.trim())
          .filter(Boolean),
        provenance: old?.provenance || {},
      };
      await this.mutation(
        "/concepts" + (this.conceptId ? "/" + this.conceptId : ""),
        this.conceptId ? "PUT" : "POST",
        body,
      );
      this.conceptId = "";
      this.conceptName = "";
      this.aliases = "";
    });
  }
  remove(kind: string, id: string) {
    void this.api.run(() => this.mutation("/" + kind + "/" + id, "DELETE"));
  }
  toggleLink(id: string) {
    this.links = this.links.includes(id)
      ? this.links.filter((x) => x !== id)
      : [...this.links, id];
  }
  saveLinks() {
    void this.api.run(async () => {
      const body: Schema<"Links"> = { target_model_revision_ids: this.links };
      await this.mutation("/links", "PUT", body);
    });
  }
  publish() {
    void this.api.run(async () => {
      await this.mutation("/publish", "POST");
      this.api.notice.set(
        "Knowledge model published. Bind it to a draft knowledge version.",
      );
    });
  }
  bind() {
    void this.api.run(async () => {
      const model = this.model();
      const version = this.api.version;
      if (
        this.api.scopeLoading() ||
        !model ||
        model.profile_id !== this.api.profileId() ||
        !version ||
        version.profile_id !== model.profile_id
      )
        throw new Error(
          "Select a fully loaded model and knowledge version from the same profile.",
        );
      const body: Schema<"Binding"> = { model_revision_id: model.id };
      await this.api.request("/versions/" + version.id + "/model", "PUT", body);
      await this.api.reload();
      this.api.notice.set(
        "Published model bound to selected knowledge version.",
      );
    });
  }
  findModel(id: string) {
    return (m: Model) => m.id === id;
  }
  typeName(id: string) {
    return this.model()?.entities.find((e) => e.id === id)?.name || id;
  }
}
